"""
Endpoints REST agrégés pour le cockpit frontend.

Réutilisent les agrégations du LocalCRMAdapter (les mêmes que celles servies
au copilote comme outils LLM) — aucune logique métier nouvelle ici, juste
l'exposition JSON. Chaque endpoint est gated par vue via require_views()
(matrice config/permissions.py) : la protection est côté serveur, pas un
simple masquage de menu.
"""
import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.v1.dependencies import require_views
from modules.uc_crosssell.signals import get_signals as crosssell_signals
from modules.uc_daily_analysis import computations as daily_comp
from modules.uc_daily_analysis.store import daily_cached
from modules.uc_forecast.aggregation import build_pipeline_forecast, month_labels
from modules.uc_dormance.aggregation import build_suivi_dormance
from modules.uc_offermix.aggregation import build_offer_mix
from modules.uc_forecast.decision_client import build_client_decision
from modules.uc_tresorerie.decision_recouvrement import build_recouvrement_decision

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


def _annee(annee: int | None) -> int:
    """Exercice de lecture d'un endpoint de FLUX, l'année en cours par défaut.

    Même convention que `uc_commercial.router._annee` et `uc_daf.router._annee` :
    un indicateur d'activité (CA, marge, performance commerciale) se lit sur un
    exercice, et l'exercice par défaut est celui en cours. Sans ce défaut, un
    appel sans `year` cumulait tout l'historique du miroir — huit exercices
    confondus sur un écran qui annonce « l'exercice ».

    À n'appliquer qu'aux flux. Les endpoints de STOCK (`/unpaid`, exposition
    impayés, backlog) n'ont délibérément pas de borne : une créance de 2024 est
    toujours due aujourd'hui, et la masquer serait perdre l'essentiel.

    Cette convention vaut pour la couche HTTP seulement. Les appelants internes
    (briefing, arbitrage, outils du copilote) passent par l'adaptateur, dont le
    défaut reste « tous exercices » — leur portée est choisie appel par appel.
    """
    return annee or datetime.now().year


async def _hors_boucle(fn, *args):
    """Exécute une agrégation Python synchrone HORS de la boucle d'événements.

    Les `build_*` de modules/ ne font aucune I/O : ce sont des boucles Python sur
    la totalité des lignes remontées (`build_offer_mix` lit tout le pipe, sans
    plafond — c'est une nécessité métier, cf. son endpoint). Appelées en ligne
    dans un `async def`, elles monopolisaient le worker pendant toute leur durée
    — jusqu'à ~330 ms pour le mix d'offre — et aucune autre requête ne
    progressait entre-temps.

    Symptôme mesuré côté cockpit : les 6 appels de la vue DG lancés en
    `Promise.all` coûtaient 238 ms quand le plus lent seul en coûtait 96, soit un
    parallélisme non seulement nul mais négatif (la somme séquentielle valait
    215 ms). Avec 2 workers uvicorn, le backend ne servait que deux agrégations
    à la fois, l'une après l'autre.

    Ce que ce déport apporte, mesuré (build_offer_mix sur 9475 opportunités, 6
    passages en ordre alterné) — un « tour » = une reprise de main de la boucle :

      inline    : 318 ms ·  2 tours sur ~317 possibles (1 % du nominal)
      to_thread : 329 ms · 12 tours sur ~328 possibles (4 % du nominal)

    À lire honnêtement : le coût unitaire est négligeable (+11 ms) et la boucle
    reprend la main 6 fois plus souvent, mais elle reste affamée 96 % du temps —
    le GIL n'est pas relâché par du Python pur. Ce déport empêche une agrégation
    de GELER complètement son worker ; il ne rend PAS la concurrence saine.

    Le vrai correctif pour `offer-mix` est ailleurs : 318 ms de boucles Python sur
    tout le pipe, recalculés à chaque affichage, pour un agrégat qui ne bouge
    qu'aux syncs Odoo. Il faut le figer, comme les narrations du jour
    (modules/uc_daily_analysis/store.py), pas le déplacer de thread.
    """
    return await asyncio.to_thread(fn, *args)


# ---------- Vue Tableau de bord ----------

@router.get("/kpis", dependencies=[Depends(require_views("dashboard"))])
async def kpis(
    request: Request,
    year: int | None = Query(default=None),
):
    """Bloc complet du cockpit : CA annuel N/N-1 + séries mensuelles N/N-1
    (les filtres période du front se calculent client-side, comme le mockup),
    pipeline OUVERT (stades normalisés), taux de transformation réel, marges.
    """
    crm = _crm(request)
    y = year or datetime.now().year
    # NE PAS remplacer ces await par un asyncio.gather. C'est tentant — les 9
    # agrégats sont indépendants et chaque méthode du LocalCRMAdapter ouvre sa
    # propre session — et c'est mesuré comme PIRE. Sur le miroir local, 8 mesures
    # en ordre alterné après préchauffage :
    #
    #   séquentiel : min 85 · médiane  91 · max 112 ms
    #   gather     : min 87 · médiane 100 · max 188 ms   → 1,10x plus lent
    #
    # Le goulot n'est pas la latence d'aller-retour mais le travail de requête
    # lui-même, que SQLite sérialise de toute façon : neuf connexions
    # concurrentes sur un fichier unique n'achètent rien et dégradent la queue de
    # distribution. Le jour où le miroir passera sur Postgres, la mesure vaudra
    # d'être refaite.
    #
    # `get_ytd_stats` : CA arrêté au même jour calendaire dans les deux années —
    # seul agrégat comparable à N-1 en cours d'exercice (year/previous_year
    # comparent une année partielle à une année pleine, cf. build_dg_facts).
    current = await crm.get_year_stats(y)
    previous = await crm.get_year_stats(y - 1)
    ytd = await crm.get_ytd_stats(y)
    previous_ytd = await crm.get_ytd_stats(y - 1)
    monthly = await crm.get_monthly_revenue(y)
    monthly_previous = await crm.get_monthly_revenue(y - 1)
    open_pipeline = await crm.get_open_pipeline_stats()
    win_rate = await crm.get_win_rate()
    # Borné sur `y` comme le reste de l'endpoint : le bloc « marges » voisine des
    # agrégats d'exercice, un cumul de huit exercices à côté d'eux ne se lit pas.
    # Les stocks qu'il porte (backlog, reste à encaisser) restent hors borne —
    # c'est `get_margin_stats` qui le garantit, pas l'appelant.
    margins = await crm.get_margin_stats(year=y)
    return {
        "year": current,
        "previous_year": previous,
        "ytd": ytd,
        "previous_ytd": previous_ytd,
        "monthly": monthly,
        "monthly_previous": monthly_previous,
        "open_pipeline": open_pipeline,
        "win_rate": win_rate,
        "marges": {
            "nb_dossiers": margins["nb_dossiers"],
            # Moyennes de pourcentages par dossier : conservées pour les
            # appelants existants, mais à ne PAS afficher (-745 % sur ce miroir).
            "perc_marge_provisoire_moyen": margins["perc_marge_provisoire_moyen"],
            "perc_marge_definitive_moyen": margins["perc_marge_definitive_moyen"],
            # Ratios agrégés : ce sont ceux-là qui se publient. Le définitif est
            # mesuré sur le périmètre imputé et n'a de sens qu'accompagné de sa
            # couverture (cf. LocalCRMAdapter.get_margin_stats).
            "taux_marge_provisoire_pct": margins["taux_marge_provisoire_pct"],
            "taux_marge_definitive_pct": margins["taux_marge_definitive_pct"],
            "couverture_marge_definitive_pct": margins["couverture_marge_definitive_pct"],
            "marge_definitive_exploitable": margins["marge_definitive_exploitable"],
            "backlog_total": margins["backlog_total"],
            "reste_a_encaisser": margins["reste_a_encaisser"],
            "total_encaisse": margins["total_encaisse"],
            "ca_definitif_total": margins["ca_definitif_total"],
            "marge_definitive_total": margins["marge_definitive_total"],
            "fournisseurs_restant": margins["fournisseurs_restant"],
        },
    }


class TrendAnalysisRequest(BaseModel):
    months: list[str]
    values_m_fcfa: list[float]


def _llm_sonnet(request: Request):
    return getattr(request.app.state.container, "llm_sonnet", None)


@router.post("/analysis", dependencies=[Depends(require_views("dashboard"))])
async def dashboard_analysis(request: Request, body: TrendAnalysisRequest):
    """Analyse de la courbe CA réellement affichée (mois/valeurs déjà calculés
    côté client selon le filtre de période actif) — figée pour la journée par le
    job du matin, jamais recalculée par le LLM à l'affichage."""
    months, values = body.months, body.values_m_fcfa
    return await daily_cached(
        daily_comp.KEY_TREND,
        daily_comp.trend_variant(months),
        lambda: daily_comp.trend_analysis(_llm_sonnet(request), months, values),
    )


@router.get("/clients-by-country", dependencies=[Depends(require_views("dashboard"))])
async def clients_by_country(request: Request):
    """Répartition des clients par pays (doughnut du cockpit)."""
    return await _crm(request).get_clients_by_country()


@router.get("/monthly-revenue", dependencies=[Depends(require_views("dashboard"))])
async def monthly_revenue(request: Request, year: int | None = Query(default=None)):
    """Série CA commandé par mois (graphe d'évolution)."""
    y = year or datetime.now().year
    return {"year": y, "months": await _crm(request).get_monthly_revenue(y)}


@router.get("/monthly-clients", dependencies=[Depends(require_views("dashboard"))])
async def monthly_clients(request: Request, year: int | None = Query(default=None), limit: int = Query(default=10, ge=1, le=50)):
    """Pour chaque mois de l'année, les clients ayant le plus commandé (détail au clic sur un mois)."""
    y = year or datetime.now().year
    return {"year": y, "months": await _crm(request).get_clients_by_month(y, limit)}


@router.get("/revenue/by-salesperson", dependencies=[Depends(require_views("dashboard", "performance"))])
async def revenue_by_salesperson(
    request: Request,
    year: int | None = Query(default=None),
    quarter: int | None = Query(default=None, ge=1, le=4),
):
    """CA par commercial sur l'exercice (l'année en cours par défaut, cf. `_annee`).

    Sans borne, cet endpoint cumulait huit exercices : l'écran DC « Transformation »
    et le débrief DG — qui, lui, demandait déjà l'année en cours — affichaient deux
    chiffres différents pour le même commercial.
    """
    return await _crm(request).get_revenue_by_salesperson(year=_annee(year), quarter=quarter)


@router.get("/revenue/by-sector", dependencies=[Depends(require_views("dashboard"))])
async def revenue_by_sector(
    request: Request,
    year: int | None = Query(default=None),
    limit: int = Query(default=20, le=100),
):
    """CA par secteur sur l'exercice (l'année en cours par défaut)."""
    return await _crm(request).get_revenue_by_sector(year=_annee(year), limit=limit)


@router.get("/top-clients", dependencies=[Depends(require_views("dashboard", "clients"))])
async def top_clients(
    request: Request,
    year: int | None = Query(default=None),
    limit: int = Query(default=10, le=50),
):
    """Premiers comptes par CA de l'exercice (l'année en cours par défaut)."""
    return await _crm(request).get_top_clients(limit=limit, year=_annee(year))


@router.get("/top-orders", dependencies=[Depends(require_views("dashboard", "clients"))])
async def top_orders(
    request: Request,
    year: int | None = Query(default=None),
    limit: int = Query(default=10, le=50),
):
    """Les plus grosses commandes signées de l'exercice, par montant (et non par
    date). L'année en cours par défaut."""
    return await _crm(request).get_top_orders(limit=limit, year=_annee(year))


# ---------- Performance ----------

@router.get("/performance/summary", dependencies=[Depends(require_views("performance"))])
async def performance_summary(request: Request, limit: int = Query(default=20, le=100)):
    """Taux de victoire (historique) + opportunités perdues (top N, par client, par commercial)."""
    crm = _crm(request)
    return {
        "win_rate": await crm.get_win_rate(),
        "lost_deals": await crm.get_lost_deals(limit=limit),
    }


@router.post("/performance/analysis", dependencies=[Depends(require_views("performance"))])
async def performance_analysis(request: Request):
    """Lecture qualitative des performances, rédigée par Claude à partir des
    chiffres réels déjà calculés (jamais recalculés par le LLM) — figée pour la
    journée par le job du matin."""
    return await daily_cached(
        daily_comp.KEY_PERFORMANCE,
        "",
        lambda: daily_comp.performance_analysis(_crm(request), _llm_sonnet(request)),
    )


# ---------- Forecast ----------

@router.get("/forecast", dependencies=[Depends(require_views("forecast"))])
async def forecast(request: Request, year: int | None = Query(default=None)):
    return await _crm(request).get_quarterly_forecast(year=year)


@router.get("/forecast/pipeline-weighted", dependencies=[Depends(require_views("forecast"))])
async def forecast_pipeline_weighted(request: Request):
    """Forecast pondéré à partir des vraies opportunités ouvertes du pipeline
    (scénarios pessimiste/réaliste/optimiste, répartition mensuelle, par étape,
    par client) — remplace le calcul JS qui tournait sur des fixtures front.
    """
    opportunities = await _crm(request).list_opportunities(limit=500)
    result = await _hors_boucle(build_pipeline_forecast, opportunities)
    result["month_labels"] = month_labels()
    return result


@router.post("/forecast/analysis", dependencies=[Depends(require_views("forecast"))])
async def forecast_analysis(request: Request):
    """Lecture qualitative du forecast pondéré, rédigée par Claude à partir des
    chiffres réels déjà calculés (jamais recalculés par le LLM) — figée pour la
    journée par le job du matin."""
    return await daily_cached(
        daily_comp.KEY_FORECAST,
        "",
        lambda: daily_comp.forecast_analysis(_crm(request), _llm_sonnet(request)),
    )


# ---------- Mix d'offre (profil DC) ----------

@router.get("/offer-mix", dependencies=[Depends(require_views("forecast"))])
async def offer_mix(request: Request):
    """Répartition du pipeline par famille d'offre (logiciel / réseau /
    équipement / services) et mix d'atterrissage par trimestre d'échéance.

    Lit TOUT le pipe (`list_all_opportunities`, sans limite) et non le top 500
    pondéré : un plafond tronquerait le mix à 7 % des opportunités en base et
    rendrait faux le taux de couverture servi dans `coverage`.

    La famille est DÉDUITE du libellé faute de champ catégorie côté Odoo — d'où
    `coverage`, que le front doit afficher : les parts portent sur ~81 % du
    montant, pas sur 100 %.
    """
    opportunities = await _crm(request).list_all_opportunities()
    return await _hors_boucle(build_offer_mix, opportunities)


# ---------- Comptes dormants / actifs (profil DC) ----------

@router.get("/account-activity", dependencies=[Depends(require_views("clients"))])
async def account_activity(request: Request):
    """Segmentation du portefeuille par ancienneté de dernière commande signée :
    Actif / Ralentit / Dormant / Perdu / Prospect, seuils validés par la Direction
    Commerciale (6 / 12 / 24 mois).

    Gated par « clients » et non « tresorerie » : le profil DC n'a pas accès aux
    données de trésorerie (cf. config/permissions.py). L'impayé est donc servi en
    DRAPEAU et MONTANT AGRÉGÉ par compte, jamais en détail de factures — même
    arbitrage que la vue AM.

    La segmentation dépend de la date d'observation (~10 comptes changent de segment
    par mois) : `as_of` est dans la réponse et doit être affiché.
    """
    comptes = await _crm(request).get_account_activity()
    return await _hors_boucle(build_suivi_dormance, comptes)


class ClientDecisionRequest(BaseModel):
    client: str


@router.post("/forecast/client-decision", dependencies=[Depends(require_views("forecast"))])
async def forecast_client_decision(request: Request, body: ClientDecisionRequest):
    """Décision recommandée pour un client du forecast : risque calculé en
    Python (impayé connu + opportunité à échéance dépassée), Claude rédige
    uniquement la justification et l'action."""
    crm = _crm(request)
    opportunities = await crm.list_opportunities(limit=500)
    agg = await _hors_boucle(build_pipeline_forecast, opportunities)
    client_agg = next((c for c in agg["by_client"] if c["client"] == body.client), None)
    if client_agg is None:
        raise HTTPException(status_code=404, detail="Client introuvable dans le pipeline ouvert")

    exposure = await crm.get_unpaid_exposure()
    debiteur = next(
        (d for d in exposure["top_10_debiteurs"] if d["client"] == body.client), None
    )
    opp_risque = next((o for o in client_agg["opportunities"] if o["at_risk"]), None)

    llm = getattr(request.app.state.container, "llm_haiku", None)
    decision = await build_client_decision(
        llm,
        client=body.client,
        pondere_xof=client_agg["weighted_xof"],
        debiteur=debiteur,
        opp_risque=opp_risque,
    )
    return decision


# ---------- Marges / coûts ----------

@router.get("/margins", dependencies=[Depends(require_views("dashboard", "couts"))])
async def margins(
    request: Request,
    year: int | None = Query(default=None),
    limit: int = Query(default=10, le=50),
):
    """Marges de l'exercice (l'année en cours par défaut) et dossiers qui les portent.

    Attention à la lecture de `stats` : l'exercice ne borne que les flux (CA,
    marges, taux moyens). Les stocks du même bloc — `backlog_total`,
    `reste_a_encaisser`, `total_encaisse` — restent sur tous les exercices, et
    `stats.portee_stocks` le dit. C'est voulu : un dossier ouvert en 2025 et
    encore en cours de livraison est du backlog d'aujourd'hui.
    """
    crm = _crm(request)
    an = _annee(year)
    return {
        "stats": await crm.get_margin_stats(year=an),
        "top_dossiers": await crm.get_top_margin_dossiers(limit=limit, year=an),
    }


@router.post("/margins/analysis", dependencies=[Depends(require_views("dashboard", "couts"))])
async def margins_analysis(request: Request, year: int | None = Query(default=None)):
    """Lecture qualitative de l'écart marge provisoire/définitive (backlog, érosion),
    rédigée par Claude à partir des agrégats réels déjà calculés (jamais recalculés
    par le LLM) — figée pour la journée par le job du matin.

    Même exercice par défaut que `/margins` : la narration commente les chiffres
    affichés au-dessus d'elle, elle ne peut pas porter sur une autre période."""
    an = _annee(year)
    return await daily_cached(
        daily_comp.KEY_MARGINS,
        daily_comp.margins_variant(an),
        lambda: daily_comp.margins_analysis(_crm(request), _llm_sonnet(request), year=an),
    )


# ---------- Trésorerie (rôles finance uniquement) ----------

@router.get("/unpaid", dependencies=[Depends(require_views("tresorerie"))])
async def unpaid(request: Request, limit: int = Query(default=10, le=50)):
    """Exposition aux impayés — réservé aux profils avec accès Trésorerie."""
    crm = _crm(request)
    return {
        "exposure": await crm.get_unpaid_exposure(),
        "top_invoices": await crm.get_unpaid_invoices(limit=limit),
    }


@router.post("/unpaid/analysis", dependencies=[Depends(require_views("tresorerie"))])
async def unpaid_analysis(request: Request):
    """Lecture qualitative de l'exposition aux impayés, rédigée par Claude à
    partir des chiffres réels déjà calculés (jamais recalculés par le LLM) —
    figée pour la journée par le job du matin."""
    return await daily_cached(
        daily_comp.KEY_UNPAID,
        "",
        lambda: daily_comp.unpaid_analysis(_crm(request), _llm_sonnet(request)),
    )


class RecouvrementDecisionRequest(BaseModel):
    client: str


@router.post("/unpaid/recouvrement-decision", dependencies=[Depends(require_views("tresorerie"))])
async def unpaid_recouvrement_decision(request: Request, body: RecouvrementDecisionRequest):
    """Décision de recouvrement pour un débiteur : urgence calculée en Python
    (retard réel), Claude rédige uniquement la justification et l'action."""
    exposure = await _crm(request).get_unpaid_exposure()
    debiteur = next((d for d in exposure["top_10_debiteurs"] if d["client"] == body.client), None)
    if debiteur is None:
        raise HTTPException(status_code=404, detail="Client introuvable dans les impayés")

    llm = getattr(request.app.state.container, "llm_haiku", None)
    decision = await build_recouvrement_decision(
        llm,
        client=body.client,
        montant_xof=debiteur["montant_total_xof"],
        jours=debiteur["retard_max_jours"],
    )
    return decision


# ---------- DSO réel (délai de recouvrement) ----------

@router.get("/dso", dependencies=[Depends(require_views("tresorerie"))])
async def dso(
    request: Request,
    client: str = Query(default=""),
    year: int | None = Query(default=None),
):
    """Délai moyen réel de recouvrement (DSO) sur l'exercice — calculé sur les
    dates de paiement Odoo quand elles existent, sinon approximation balance sheet
    explicitement signalée comme telle (cf. LocalCRMAdapter.get_invoice_collection_stats).

    `year` désigne ici l'exercice d'OBSERVATION (l'année en cours par défaut) et
    part en `exercice=`, pas en `year=` : la borne porte sur les factures réglées
    pendant l'année, jamais sur celles émises pendant l'année. Filtrer sur
    l'émission ne retiendrait que les factures émises et encaissées dans le même
    exercice, c'est-à-dire les payeurs rapides — 29 jours au lieu de 71 sur le
    miroir d'août 2026. Le détail du biais est dans la docstring de l'adaptateur.

    Les montants (`montant_en_attente_xof`, `total_factures`) restent hors borne :
    ce sont des créances, pas l'activité de l'année."""
    return await _crm(request).get_invoice_collection_stats(
        client_name=client, exercice=_annee(year),
    )


# ---------- Écart budgétaire par effet clients (module 04) ----------

@router.get("/budget-variance", dependencies=[Depends(require_views("dashboard"))])
async def budget_variance(request: Request, year: int | None = Query(default=None)):
    """Décompose l'écart de CA vs N-1 par effet clients retenus/gagnés/perdus,
    calculé sur le CA réel par client (commandes confirmées). Le mockup
    d'origine promettait une décomposition volume/mix/prix — le miroir ne
    contient pas de référentiel produit normalisé permettant de l'isoler de
    façon fiable ; cette décomposition par clients est la plus rigoureuse que
    les données actuelles permettent (cf. note du payload)."""
    crm = _crm(request)
    y = year or datetime.now().year
    current_clients = await crm.get_top_clients(limit=10000, year=y)
    previous_clients = await crm.get_top_clients(limit=10000, year=y - 1)

    cur_by_name = {c["client"]: c["ca_total_xof"] for c in current_clients}
    prev_by_name = {c["client"]: c["ca_total_xof"] for c in previous_clients}

    retained = set(cur_by_name) & set(prev_by_name)
    gained = set(cur_by_name) - set(prev_by_name)
    lost = set(prev_by_name) - set(cur_by_name)

    effet_retenus = sum(cur_by_name[c] - prev_by_name[c] for c in retained)
    effet_gagnes = sum(cur_by_name[c] for c in gained)
    effet_perdus = -sum(prev_by_name[c] for c in lost)

    top_gagnes = sorted(gained, key=lambda c: cur_by_name[c], reverse=True)[:5]
    top_perdus = sorted(lost, key=lambda c: prev_by_name[c], reverse=True)[:5]

    return {
        "annee": y,
        "annee_precedente": y - 1,
        "ecart_total_xof": round(effet_retenus + effet_gagnes + effet_perdus),
        "effet_clients_retenus_xof": round(effet_retenus),
        "effet_clients_gagnes_xof": round(effet_gagnes),
        "effet_clients_perdus_xof": round(effet_perdus),
        "top_clients_gagnes": [{"client": c, "ca_xof": round(cur_by_name[c])} for c in top_gagnes],
        "top_clients_perdus": [{"client": c, "ca_xof": round(prev_by_name[c])} for c in top_perdus],
        "nb_clients_retenus": len(retained),
        "nb_clients_gagnes": len(gained),
        "nb_clients_perdus": len(lost),
        "note": (
            "Décomposition par effet clients (retenus/gagnés/perdus), pas par volume/mix/prix : le miroir "
            "ne contient pas de référentiel produit normalisé permettant d'isoler ces trois effets de façon "
            "fiable. C'est la décomposition la plus rigoureuse que les données actuelles permettent."
        ),
    }


# ---------- Fil d'actions prioritaires (module 22, transversal) ----------

@router.get("/next-actions", dependencies=[Depends(require_views("dashboard", "portefeuille"))])
async def next_actions(request: Request, limit: int = Query(default=10, le=50)):
    """Classement transversal des signaux déjà calculés par les autres
    modules (portefeuille clients, montée en valeur, impayés) — jamais une
    nouvelle heuristique, un simple tri par montant engagé décroissant."""
    crm = _crm(request)
    # Trois lectures indépendantes : simultanées plutôt qu'enchaînées. Les
    # signaux de montée en valeur passent par le calcul partagé et mis en cache
    # (cf. uc_crosssell/signals.py) au lieu d'être refaits ici pour ce seul écran.
    portfolio, crosssell, unpaid = await asyncio.gather(
        crm.get_client_portfolio(limit=200),
        crosssell_signals(crm),
        crm.get_unpaid_exposure(),
    )

    actions: list[dict] = []
    for c in portfolio:
        for signal in c.get("signaux", []):
            actions.append({
                "client": c["client"],
                "type": "Portefeuille",
                "texte": signal,
                "montant_xof": c.get("reste_a_encaisser_xof") or 0,
            })
    for key, label in (
        ("renouvellement", "Renouvellement"),
        ("cross_sell", "Cross-sell"),
        ("up_sell", "Up-sell"),
        ("obsolete", "Obsolescence"),
    ):
        for item in crosssell.get(key, []):
            actions.append({
                "client": item["client"],
                "type": label,
                "texte": item["detail"],
                "montant_xof": item["montant_xof"],
            })
    for d in unpaid.get("top_10_debiteurs", []):
        if d["retard_max_jours"] > 60:
            actions.append({
                "client": d["client"],
                "type": "Recouvrement",
                "texte": f"{d['nb_factures']} facture(s) impayée(s), retard maximum {d['retard_max_jours']} j.",
                "montant_xof": d["montant_total_xof"],
            })

    actions.sort(key=lambda a: a["montant_xof"], reverse=True)
    return {
        "actions": actions[:limit],
        "note": (
            "Classement par montant engagé décroissant, sur les signaux déjà calculés par les modules "
            "Portefeuille, Montée en valeur et Trésorerie — aucune nouvelle heuristique de scoring."
        ),
    }


# ---------- Vue Pilotage de l'activité (cockpit DG) ----------

# Étapes qui ferment une opportunité — même reconnaissance par mot-clé que
# modules/uc_briefing/facts.py : `stade` est du texte libre Odoo qui mélange
# deux nomenclatures (« 6-Gagné » / « Won »).
_STADES_FERMES = ("gagn", "won", "perdu", "lost", "annul", "cancel", "suspendu")


def _echeances_ouvertes(opportunities: list[dict], jours: int) -> dict:
    """Opportunités encore ouvertes dont la clôture tombe dans la fenêtre.

    `deadline` est renseignée aussi sur les affaires gagnées, perdues et
    annulées : sans le filtre d'étape, on compterait des affaires closes.
    """
    aujourd_hui = datetime.now().date()
    limite = aujourd_hui + timedelta(days=jours)
    proches = []
    for opp in opportunities:
        brut = opp.get("deadline")
        stade = (opp.get("stade") or "").lower()
        if not brut or any(mot in stade for mot in _STADES_FERMES):
            continue
        try:
            echeance = datetime.fromisoformat(str(brut)).date()
        except ValueError:
            continue
        if aujourd_hui <= echeance <= limite:
            proches.append((echeance, opp))
    proches.sort(key=lambda p: p[0])
    return {
        "fenetre_jours": jours,
        "nb": len(proches),
        "montant_xof": sum(o.get("revenu_attendu_xof") or 0 for _, o in proches),
        "prochaines": [
            {
                "opportunite": o.get("opportunite"),
                "client": o.get("client"),
                "deadline": e.isoformat(),
                "revenu_attendu_xof": o.get("revenu_attendu_xof"),
            }
            for e, o in proches[:5]
        ],
    }


@router.get("/pilotage", dependencies=[Depends(require_views("dashboard"))])
async def pilotage(request: Request, year: int | None = Query(default=None)):
    """Vue 360 de l'onglet DG « Pilotage de l'activité » : un appel pour
    l'onglet entier (doctrine des cockpits par persona, cf.
    modules/uc_commercial/router.py — un onglet qui affiche dix blocs paie un
    appel, pas dix).

    Mêmes agrégats que les éléments « vue 360 » du débrief DG
    (modules/uc_briefing/facts.py, blocs 10-19) : l'onglet montre en permanence
    ce que le débrief raconte à la demande — jamais deux calculs différents
    pour le même indicateur.
    """
    crm = _crm(request)
    y = year or datetime.now().year
    # Séquentiel et non gather : voir la mesure détaillée sur /kpis.
    ca_annuel = []
    for a in range(y - 4, y + 1):
        stats = await crm.get_year_stats(a)
        ca_annuel.append({
            "annee": a, "ca_xof": stats["revenue_xof"], "nb_commandes": stats["orders_count"],
        })
    marge = await crm.get_margin_stats(year=y)
    atterrissage = await crm.get_quarterly_forecast()
    win_rate = await crm.get_win_rate()
    lost = await crm.get_lost_deals(limit=5)
    opportunites = await crm.list_opportunities(limit=500)
    # Délais mesurés sur les règlements de l'exercice, comme l'écran DAF : le
    # cockpit DG affiche par ailleurs le CA et la marge de `y`, un DSO cumulé sur
    # huit exercices à côté d'eux ne se lit pas.
    encaissement = await crm.get_invoice_collection_stats(exercice=y)
    commerciaux = await crm.get_revenue_by_salesperson(year=y)
    secteurs = await crm.get_revenue_by_sector(year=y, limit=10)
    mensuel = await crm.get_monthly_revenue(y)
    leads = await crm.get_hot_leads(limit=5)
    return {
        "annee": y,
        "ca_annuel": ca_annuel,
        "marge": marge,
        "atterrissage": atterrissage,
        "transformation": {"win_rate": win_rate, "pertes": lost},
        "echeances": _echeances_ouvertes(opportunites, jours=60),
        "encaissement": encaissement,
        "commerciaux": commerciaux,
        "secteurs": secteurs,
        "mensuel": mensuel,
        "leads_chauds": leads,
    }
