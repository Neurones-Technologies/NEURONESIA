"""Faits réels du jour, par rôle — calcul déterministe pur Python (aucun LLM
ici). Réutilise les agrégations déjà exposées par CRMRepository (les mêmes
que les endpoints /v1/dashboard/*) : chaque rôle reçoit un sous-ensemble
pertinent, jamais l'intégralité brute.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from modules.uc_arbitrage import service as arbitrage_service
from modules.uc_briefing import analyses, evenements, indicateurs, preferences
from modules.uc_briefing import seuils as seuils_mod
from modules.uc_daf import situation as daf_situation
from modules.uc_forecast.aggregation import build_pipeline_forecast

logger = logging.getLogger(__name__)


def _m(xof: float | int | None) -> int:
    return round((xof or 0) / 1_000_000)


async def _safe(coro, default, label: str):
    """Une source indisponible retire son fait, jamais le panneau entier —
    contrairement à une exception non rattrapée dans un des `_FACTS_BUILDERS`,
    qui fait disparaître toute la section du rôle (cf. service.generate)."""
    try:
        return await coro
    except Exception as exc:
        logger.warning("Faits briefing — source « %s » indisponible, fait omis : %s", label, exc)
        return default


def _fr(iso: str | None) -> str:
    """'2026-04-01' -> '01/04/2026'."""
    if not iso or len(iso) < 10:
        return "date inconnue"
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"


def _taux_marge(margins: dict, volet: str) -> float | None:
    """Taux de marge recalculé sur les TOTAUX, jamais repris de
    `perc_marge_*_moyen`.

    Ces deux champs sont des AVG() non pondérés de pourcentages par dossier, et
    91 dossiers à dénominateur minuscule tirent la moyenne provisoire à -745 %.
    Le briefing affichait « marge provisoire moyenne -745,31 % », un chiffre que
    personne ne peut ni croire ni corriger. Le même piège était déjà désamorcé
    dans `ecart_marge_promise` : la parade est centralisée ici.
    """
    # `get_margin_stats` n'accorde pas ses clés de la même façon des deux côtés :
    # `ca_definitif_total` mais `marge_definitive_total`. Construire les noms par
    # interpolation donnait `marge_definitif_total`, absent du dictionnaire, donc
    # une marge de 0,0 % affichée sans la moindre erreur. La correspondance est
    # écrite en toutes lettres pour que la prochaine clé ajoutée se voie.
    cles = {
        "provisoire": ("ca_provisoire_total", "marge_provisoire_total"),
        "definitif": ("ca_definitif_total", "marge_definitive_total"),
    }[volet]
    ca = margins.get(cles[0]) or 0
    marge = margins.get(cles[1]) or 0
    return round(marge / ca * 100, 1) if ca else None


def _mm(xof: float | int | None) -> str:
    """Montant en millions, ou « moins de 1 M » — jamais « 0 M FCFA ».

    `_m` arrondit : une commande d'achat de 400 000 F sort à « 0 M FCFA », ce qui
    se lit comme un montant nul et discrédite la puce qui l'entoure. Réservé aux
    puces d'événements, où les montants unitaires sont parfois petits ; les
    agrégats de direction restent sur `_m`.
    """
    millions = _m(xof)
    return "moins de 1 M FCFA" if not millions and (xof or 0) else f"{millions} M FCFA"


def _var(deltas: dict | None, cle: str, horizon: str = "j1") -> str:
    """Suffixe de variation à coller à une puce : « (▲ 85 M FCFA vs hier) ».

    Rend "" dès que la variation n'est pas mesurable — pas d'historique, pas de
    point de comparaison dans la tolérance, ou franchissement d'une remise à
    zéro. Une puce sans delta reste une puce juste ; c'est la seule dégradation
    acceptable, et elle est silencieuse par construction.
    """
    if not deltas:
        return ""
    bloc = deltas.get(cle)
    return indicateurs.formater(bloc, horizon) if bloc else ""


async def _deltas(cles: list[str], arret: datetime | None = None) -> dict:
    """Variations des indicateurs demandés. Une historisation absente ou en
    panne retire les suffixes, jamais les puces."""
    try:
        return await indicateurs.delta(cles, as_of=(arret.date() if arret else None))
    except Exception as exc:
        logger.warning("Faits briefing — deltas indisponibles, puces sans variation : %s", exc)
        return {}


class Puces:
    """Puces d'un briefing, restituées dans l'ORDRE DE LECTURE et non dans
    l'ordre du code.

    L'ordre du code suit les dépendances de calcul : une source partagée est
    résolue avant ses consommateurs, un repli est calculé avant son test. Rien
    de tout cela ne dit ce qu'un directeur doit lire en premier. Tant que les
    puces sortaient dans cet ordre, la hiérarchie du briefing n'existait
    nulle part — et c'est le LLM qui, faute de mieux, choisissait lui-même les
    cinq lignes affichées en tête de cockpit. Un modèle de langage décidait donc
    chaque matin de ce que lit une direction.

    Ici l'ordre vient du catalogue du rôle : d'abord le chiffre et son
    mouvement, puis les exceptions, puis ce qu'on fait aujourd'hui, et les
    compléments hors trame en dernier. `narratif` n'a plus qu'à prendre les
    premières lignes, sans arbitrer.

    À rang égal, l'ordre d'insertion départage : deux puces du même élément
    (le mix sectoriel en produit une ou l'autre selon la qualité des données)
    restent dans l'ordre où elles ont été écrites.
    """
    __slots__ = ("_role", "_items")

    def __init__(self, role: str):
        self._role = role
        self._items: list[tuple[tuple[int, int], int, str]] = []

    def ajouter(self, element_id: str, texte: str) -> None:
        self._items.append((preferences.rang(self._role, element_id), len(self._items), texte))

    def pour(self, element_id: str) -> "_Sortie":
        """Sortie nommée, à passer aux helpers qui écrivent plusieurs puces.

        Les helpers continuent d'appeler `.append(...)` sans rien savoir du
        catalogue : c'est l'appelant, seul à connaître l'élément qu'il sert, qui
        les attribue.
        """
        return _Sortie(self, element_id)

    def liste(self) -> list[str]:
        return [texte for _, _, texte in sorted(self._items, key=lambda item: (item[0], item[1]))]

    def par_bloc(self) -> dict[str, list[str]]:
        """Puces groupées par bloc de lecture, dans l'ordre.

        Sert la rédaction : un chiffre, une exception et une décision ne
        s'écrivent pas de la même façon, et un rédacteur à qui l'on ne donne
        qu'une liste plate les traite tous comme des constats.
        """
        groupes: dict[str, list[str]] = {}
        for (rang_bloc, _), _, texte in sorted(self._items, key=lambda item: (item[0], item[1])):
            groupes.setdefault(preferences.ORDRE_BLOCS[rang_bloc], []).append(texte)
        return groupes

    def __len__(self) -> int:
        return len(self._items)


class _Sortie:
    """Vue d'une seule puce du collecteur, compatible avec `list.append`."""
    __slots__ = ("_puces", "_id")

    def __init__(self, puces: Puces, element_id: str):
        self._puces, self._id = puces, element_id

    def append(self, texte: str) -> None:
        self._puces.ajouter(self._id, texte)


class Composition:
    """Ce que le rôle a décidé d'inclure dans son débrief (cf. uc_briefing.preferences).

    `None` — aucune préférence — signifie « tout est actif ». C'est ce qui permet
    aux appelants qui ne connaissent rien aux préférences (tests, scripts) de
    continuer à appeler `build_dg_facts(crm)` nu, et garantit qu'un déploiement
    sans ligne en base produit exactement le briefing d'avant.

    Le gating est appliqué à la SOURCE, pas sur la liste de puces en sortie :
    filtrer après coup laisserait tourner les requêtes CRM d'un élément décoché,
    et laisserait `facts` complet alors que le cockpit le lit (DgVision lit
    `facts.ca_ytd_xof`) — d'où un titre nourri d'un chiffre dont plus aucune
    puce ne parle.

    `pilote` — mode « consigne pilote » (rien de coché, consigne posée) : la
    consigne choisit le CONTENU du briefing et non plus seulement le ton. Le
    drapeau ne change RIEN au gating — l'appelant passe alors `ids=None` pour
    ouvrir tout le pool de faits — il ne sert qu'au choix du bloc de prompt en
    aval (cf. narratif._CONSIGNE_PILOTE_BLOC).
    """
    __slots__ = ("_ids", "consigne", "pilote", "_seuils")

    def __init__(self, ids: list[str] | None = None, consigne: str = "",
                 pilote: bool = False, seuils: dict[str, float] | None = None):
        self._ids = None if ids is None else set(ids)
        self.consigne = consigne
        self.pilote = pilote
        # `None` = les défauts du catalogue de seuils. Même contrat que `ids` :
        # un appelant qui ne connaît rien aux seuils (test, script) reste
        # capable d'appeler `build_dg_facts(crm)` nu et obtient exactement le
        # briefing d'avant.
        self._seuils = seuils or {}

    def actif(self, element_id: str) -> bool:
        return self._ids is None or element_id in self._ids

    def seuil(self, cle: str) -> float:
        """Seuil réglé pour ce rôle, à défaut celui du catalogue.

        Passe par la composition et non par un appel direct à `seuils.charger`
        pour que les faits restent une fonction PURE de leurs entrées : un
        builder qui lirait la base au milieu de son calcul ne serait ni testable
        ni reproductible, et `service.generate` ferait cinq lectures là où il en
        fait une (cf. `preferences.load_all`).
        """
        if cle in self._seuils:
            return self._seuils[cle]
        return seuils_mod.CATALOGUE[cle].defaut


# Repli de `get_account_rhythm_breaks` : sert de valeur par défaut à `_safe` ET
# de valeur d'une source non demandée. Extrait en constante depuis qu'il a deux
# usages — inline, il fallait le tenir synchronisé à la main.
_RUPTURE_VIDE: dict = {
    "comptes": [], "dormants": [], "nb_comptes_rompus": 0, "nb_comptes_dormants": 0,
    "ca_annuel_historique_xof": 0.0, "ca_ytd_xof": 0.0, "impaye_cumule_xof": 0.0,
    "ca_annuel_historique_dormants_xof": 0.0,
}

# Quels éléments ont besoin de quelle source. Une source n'est interrogée que si
# au moins un élément actif la réclame.
#
# Déclaré ici plutôt qu'inline dans le `gather` : « margins sert le bloc 5 ET le
# bloc 7 », « rupture sert 2, 3 et l'action du jour » sont des faits métier qui
# doivent se lire d'un coup d'œil, pas se reconstituer en parcourant 150 lignes
# de conditions. Une erreur ici est parfaitement silencieuse — une source
# manquante retombe sur son défaut et la puce disparaît sans un mot — d'où le
# test dédié qui compte les appels au CRM.
_DG_SOURCES: dict[str, tuple[str, ...]] = {
    "ytd": ("ca_ytd", "concentration"),
    "ytd_n1": ("ca_ytd",),
    "rupture": ("rupture_rythme", "croisement_impaye_rupture"),
    "margins": ("position_tresorerie", "taux_materialisation"),
    "top_clients": ("concentration",),
    "exposure": ("croisement_impaye_rupture",),
    "arbitrage": ("file_arbitrage",),
    "retention": ("retention_clients",),
    "fournisseurs": ("engagement_fournisseurs",),
    # Vue 360 — `margins` (toutes années) et `marge_exercice` (année en cours)
    # sont deux sources distinctes : la trésorerie se lit sur le stock complet,
    # la marge de l'exercice sur l'exercice seul.
    "pluriannuel": ("ca_pluriannuel",),
    "marge_exercice": ("marge_exercice",),
    "forecast": ("prevision_atterrissage",),
    "win_rate": ("taux_transformation",),
    "lost": ("taux_transformation",),
    "opportunites": ("echeances_affaires",),
    "collecte": ("delai_encaissement",),
    "par_commercial": ("performance_commerciaux",),
    "secteurs": ("mix_sectoriel",),
    "mensuel": ("rythme_mensuel",),
    "hot_leads": ("affaires_imminentes",),
    "situation_factures": ("factures_echues",),
    "visibilite": ("visibilite_carnet",),
    "btb": ("book_to_bill",),
}

# Indicateurs dont le DG cite la VARIATION. Chargés en un appel, indépendamment
# du gating : un delta absent ne retire qu'un suffixe, jamais une puce, donc la
# liste n'a pas à suivre les cases cochées.
_DG_DELTAS = ["ca_commande_ytd", "ca_facture_ytd", "impayes_echus", "backlog",
              "pipe_actif_brut", "reste_a_encaisser"]

_MOIS = ("", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre")


async def _ca_pluriannuel(crm, annee: int, nb: int = 5) -> list[dict]:
    """CA commandé des `nb` derniers exercices, du plus ancien au plus récent.

    Séquentiel et non `gather` : sur le miroir SQLite, le parallélisme est
    mesuré plus lent que l'enchaînement (cf. api/v1/dashboard.py), et un
    exercice en échec fait échouer toute la série — une série incomplète
    mentirait, une année absente se lisant comme une année sans ventes.
    """
    serie = []
    for a in range(annee - nb + 1, annee + 1):
        stats = await crm.get_year_stats(a)
        serie.append({"annee": a, "ca_xof": stats["revenue_xof"], "nb_commandes": stats["orders_count"]})
    return serie


async def _resoudre(sources: dict, besoins: dict[str, tuple[str, ...]], c: Composition) -> dict:
    """Interroge les sources réclamées par au moins un élément actif, en parallèle.

    Les sources écartées prennent la même valeur que si elles avaient échoué, si
    bien que le code aval (`if ytd and ytd_n1:`) n'a pas à distinguer « non
    demandé » de « indisponible » — dans les deux cas, la puce ne sort pas.

    `sources` : nom -> (fabrique de coroutine, valeur par défaut).
    """
    retenues = [nom for nom in sources if any(c.actif(e) for e in besoins[nom])]
    valeurs = await asyncio.gather(
        *(_safe(sources[nom][0](), sources[nom][1], nom) for nom in retenues)
    )
    resolues = {nom: defaut for nom, (_, defaut) in sources.items()}
    resolues.update(zip(retenues, valeurs))
    return resolues


def _action_du_jour(croisement_top, arb_top, rupture_top, position_nette_xof) -> str | None:
    """La décision du jour, choisie par une échelle de priorité déterministe —
    jamais par le LLM. C'est cette valeur qui occupe la 5e ligne du résumé.

    `None` quand aucun rang de l'échelle n'est chiffrable : le repli de dernier
    rang cite la position nette, qui n'existe pas si la trésorerie n'a pas été
    interrogée. Mieux vaut cinq constats qu'une action affirmant « 0 M FCFA de
    découvert » sur un chiffre jamais mesuré.
    """
    if croisement_top:
        return (
            f"Trancher aujourd'hui le cas {croisement_top['client']} : "
            f"{_m(croisement_top['impaye_xof'])} M FCFA échus depuis {croisement_top['retard_max_jours']} j "
            f"sur un compte silencieux depuis {croisement_top['jours_silence']} j — recouvrer ou "
            f"réengager, pas les deux."
        )
    if arb_top:
        return (
            f"Trancher aujourd'hui {arb_top['subject_ref']} ({_m(arb_top['enjeu_xof'])} M FCFA) : "
            f"chaque semaine de report coûte {_m(arb_top['cout_report_xof_semaine'])} M FCFA."
        )
    if rupture_top:
        return (
            f"Appeler {rupture_top['client']} cette semaine : {rupture_top['jours_silence']} j de silence "
            f"sur {_m(rupture_top['ca_annuel_moyen_xof'])} M FCFA/an historiques, avant l'arrêté budgétaire."
        )
    if position_nette_xof is None:
        return None
    return (
        f"Arbitrer aujourd'hui l'échéancier fournisseurs : {_m(abs(position_nette_xof))} M FCFA de "
        f"découvert net entre ce qui est dû et ce qui est encaissable."
    )


async def build_dg_facts(crm, composition: Composition | None = None) -> dict:
    role = "dg"
    """Sept faits nommés, datés et seuillés — le mandat du DG est l'arbitrage
    et l'atterrissage de l'exercice, pas la lecture d'agrégats de stock sans
    contrepartie."""
    c = composition or Composition()
    y = datetime.now().year
    arret = datetime.now().date()

    src = await _resoudre(
        {
            "ytd": (lambda: crm.get_ytd_stats(y), None),
            "ytd_n1": (lambda: crm.get_ytd_stats(y - 1), None),
            "rupture": (lambda: crm.get_account_rhythm_breaks(), _RUPTURE_VIDE),
            "margins": (lambda: crm.get_margin_stats(), None),
            "top_clients": (lambda: crm.get_top_clients(limit=10, year=y), []),
            "exposure": (lambda: crm.get_unpaid_exposure(), None),
            "arbitrage": (lambda: arbitrage_service.compute_file(crm, exclude_internal=True), None),
            "retention": (lambda: crm.get_client_retention(year=y), None),
            "fournisseurs": (lambda: crm.get_supplier_intelligence(limit=5), None),
            "pluriannuel": (lambda: _ca_pluriannuel(crm, y), []),
            "marge_exercice": (lambda: crm.get_margin_stats(year=y), None),
            "forecast": (lambda: crm.get_quarterly_forecast(), None),
            "win_rate": (lambda: crm.get_win_rate(), None),
            "lost": (lambda: crm.get_lost_deals(limit=5), None),
            "opportunites": (lambda: crm.list_opportunities(limit=500), []),
            "collecte": (lambda: crm.get_invoice_collection_stats(), None),
            "par_commercial": (lambda: crm.get_revenue_by_salesperson(year=y), []),
            "secteurs": (lambda: crm.get_revenue_by_sector(year=y, limit=10), []),
            "mensuel": (lambda: crm.get_monthly_revenue(y), []),
            "hot_leads": (lambda: crm.get_hot_leads(limit=5), []),
            # Comme la file d'arbitrage : un module voisin, pas une méthode du
            # CRM — mêmes chiffres que l'écran Relation commerciale du DAF.
            "situation_factures": (lambda: daf_situation.situation_factures(), None),
            "visibilite": (lambda: analyses.visibilite_carnet(), None),
            "btb": (lambda: analyses.book_to_bill(), None),
        },
        _DG_SOURCES,
        c,
    )
    deltas = await _deltas(_DG_DELTAS)
    ytd, ytd_n1, rupture = src["ytd"], src["ytd_n1"], src["rupture"]
    margins, top_clients, exposure, arb = src["margins"], src["top_clients"], src["exposure"], src["arbitrage"]
    retention, fournisseurs = src["retention"], src["fournisseurs"]

    # `date_arret` est posé hors de tout élément : le cockpit s'en sert pour dater
    # ses propres chiffres (DgVision), il ne peut pas dépendre d'une case cochée.
    facts: dict = {"date_arret": arret.isoformat()}
    puces = Puces(role)
    rupture_comptes = rupture.get("comptes", [])

    # 1 — atterrissage à date comparable (remplace la comparaison YTD/année pleine)
    #     [élément : ca_ytd]
    if c.actif("ca_ytd") and ytd and ytd_n1:
        ecart = ytd["revenue_xof"] - ytd_n1["revenue_xof"]
        ecart_pct = (ecart / ytd_n1["revenue_xof"] * 100) if ytd_n1["revenue_xof"] else None
        facts.update({
            "ca_ytd_xof": ytd["revenue_xof"],
            "ca_ytd_n1_xof": ytd_n1["revenue_xof"],
            "ca_ytd_ecart_xof": ecart,
            "ca_ytd_ecart_pct": round(ecart_pct, 1) if ecart_pct is not None else None,
            "nb_commandes_ytd": ytd["orders_count"],
            "nb_commandes_ytd_n1": ytd_n1["orders_count"],
        })
        puces.pour("ca_ytd").append(
            f"CA commandé au {_fr(arret.isoformat())} : {_m(ytd['revenue_xof'])} M FCFA contre "
            f"{_m(ytd_n1['revenue_xof'])} M FCFA à la même date en {y - 1} "
            f"({'▲' if ecart >= 0 else '▼'} {_m(abs(ecart))} M FCFA"
            + (f", {ecart_pct:+.0f}%" if ecart_pct is not None else "")
            + f"), sur {ytd['orders_count']} commandes contre {ytd_n1['orders_count']}"
            + _var(deltas, "ca_commande_ytd", "semaine") + "."
        )

    # 2 — rupture de rythme des comptes majeurs (M1)  [élément : rupture_rythme]
    if c.actif("rupture_rythme"):
        facts.update({
            "rupture_nb_comptes": rupture.get("nb_comptes_rompus", 0),
            "rupture_ca_annuel_historique_xof": rupture.get("ca_annuel_historique_xof", 0),
            "rupture_ca_ytd_xof": rupture.get("ca_ytd_xof", 0),
            "rupture_impaye_cumule_xof": rupture.get("impaye_cumule_xof", 0),
            "rupture_comptes": rupture_comptes[:3],
            "dormants_nb_comptes": rupture.get("nb_comptes_dormants", 0),
            "dormants_ca_annuel_historique_xof": rupture.get("ca_annuel_historique_dormants_xof", 0),
        })
        if rupture_comptes:
            cites = ", ".join(
                f"{cpt['client']} silencieux depuis {cpt['jours_silence']} j (dernière commande le "
                f"{_fr(cpt['derniere_commande'])}, {_m(cpt['ca_annuel_moyen_xof'])} M FCFA/an historiques)"
                for cpt in rupture_comptes[:3]
            )
            puces.pour("rupture_rythme").append(
                f"{rupture['nb_comptes_rompus']} comptes majeurs en rupture de rythme : {cites} — "
                f"{_m(rupture['ca_annuel_historique_xof'])} M FCFA/an historiques réduits à "
                f"{_m(rupture['ca_ytd_xof'])} M FCFA depuis janvier."
            )

    # 3 — croisement impayé × rupture de rythme (le fait décidable)
    #     [élément : croisement_impaye_rupture]
    croises = sorted(
        (cpt for cpt in rupture_comptes if cpt.get("croise_impaye")),
        key=lambda cpt: cpt["impaye_xof"], reverse=True,
    )
    croisement_top = croises[0] if croises else None
    croisement_impaye = rupture.get("impaye_cumule_xof", 0)
    exposition_totale = exposure["exposition_totale_xof"] if exposure else None
    part_pct = (
        round(croisement_impaye / exposition_totale * 100, 1)
        if exposition_totale else None
    )
    if c.actif("croisement_impaye_rupture"):
        facts.update({
            "croisement_nb_comptes": len(croises),
            "croisement_impaye_xof": croisement_impaye,
            "croisement_part_impaye_total_pct": part_pct,
            "croisement_top": croisement_top,
        })
    if c.actif("croisement_impaye_rupture") and croisement_top:
        puces.pour("croisement_impaye_rupture").append(
            f"{croisement_top['client']} croise les deux risques : {_m(croisement_top['impaye_xof'])} M FCFA "
            f"impayés à {croisement_top['retard_max_jours']} j de retard et {croisement_top['jours_silence']} j "
            f"sans commande. Au total {_m(croisement_impaye)} M FCFA d'impayés sur les comptes qui ont cessé "
            f"de commander" + (f", soit {part_pct:.0f}% de l'exposition." if part_pct is not None else ".")
        )

    # 4 — file d'arbitrage (le mandat du DG), hors entités du groupe
    #     [élément : file_arbitrage]
    arb_top = arb["candidats"][0] if arb and arb.get("candidats") else None
    if c.actif("file_arbitrage") and arb:
        facts.update({
            "arbitrage_dossiers_ouverts": arb["kpi"]["dossiers_ouverts"],
            "arbitrage_enjeu_xof": arb["kpi"]["enjeu_cumule_m_fcfa"] * 1_000_000,
            "arbitrage_cout_report_xof_semaine": arb["kpi"]["cout_report_m_fcfa_semaine"] * 1_000_000,
            "arbitrage_echeance_plus_proche_jours": arb["kpi"]["echeance_plus_proche_jours"],
            "arbitrage_revues_en_retard": arb["kpi"]["revues_en_retard"],
            "arbitrage_top_dossier": (
                {
                    "subject_ref": arb_top["subject_ref"],
                    "enjeu_xof": arb_top["enjeu_xof"],
                    "cout_report_xof_semaine": arb_top["cout_report_xof_semaine"],
                }
                if arb_top else None
            ),
        })
        if arb["kpi"]["dossiers_ouverts"]:
            puces.pour("file_arbitrage").append(
                f"File d'arbitrage : {arb['kpi']['dossiers_ouverts']} dossiers ouverts, "
                f"{arb['kpi']['enjeu_cumule_m_fcfa']} M FCFA d'enjeu, "
                f"{arb['kpi']['cout_report_m_fcfa_semaine']:.0f} M FCFA de coût par semaine de report"
                + (
                    f" — le premier est {arb_top['subject_ref']} ({_m(arb_top['enjeu_xof'])} M FCFA)."
                    if arb_top else "."
                )
            )

    # 5 — position nette de trésorerie (les deux côtés, jamais un seul)
    #     [élément : position_tresorerie]
    # `position_nette` est calculée même si l'élément est décoché : c'est le repli
    # de dernier rang de l'action du jour, qui doit rester chiffrable.
    position_nette = None
    if margins:
        four = margins["fournisseurs_restant"]
        reste = margins["reste_a_encaisser"]
        position_nette = reste - four
        couverture = (reste / four * 100) if four else None
        if c.actif("position_tresorerie"):
            facts.update({
                "fournisseurs_restant_xof": four,
                "reste_a_encaisser_xof": reste,
                "position_nette_xof": position_nette,
                "couverture_fournisseurs_pct": round(couverture, 1) if couverture is not None else None,
            })
            puces.pour("position_tresorerie").append(
                f"Position nette de trésorerie : {_m(four)} M FCFA dus aux fournisseurs contre "
                f"{_m(reste)} M FCFA à encaisser des clients, soit {_m(abs(position_nette))} M FCFA de "
                f"{'découvert' if position_nette < 0 else 'excédent'} structurel"
                + (f" ({couverture:.0f}% de couverture)" if couverture is not None else "")
                + _var(deltas, "reste_a_encaisser", "semaine") + "."
            )

    # 6 — concentration réelle de l'exercice (base = MÊME année que le numérateur)
    #     [élément : concentration]
    if c.actif("concentration") and top_clients and ytd:
        base = ytd["revenue_xof"]
        top5 = top_clients[:5]
        top5_sum = sum(c["ca_total_xof"] for c in top5)
        top1 = top_clients[0]
        top5_pct = (top5_sum / base * 100) if base else None
        top1_pct = (top1["ca_total_xof"] / base * 100) if base else None
        facts.update({
            "concentration_annee": y,
            "concentration_base_xof": base,
            "concentration_top5_pct": round(top5_pct, 1) if top5_pct is not None else None,
            "concentration_seuil_pct": c.seuil("concentration_top5_pct"),
            "concentration_top1_client": top1["client"],
            "concentration_top1_pct": round(top1_pct, 1) if top1_pct is not None else None,
        })
        if top5_pct is not None:
            puces.pour("concentration").append(
                f"Concentration {y} : le top 5 pèse {top5_pct:.0f}% des {_m(base)} M FCFA commandés "
                f"(seuil de vigilance {c.seuil('concentration_top5_pct'):g}%), "
                f"{top1['client']} premier à {top1_pct:.0f}%."
            )

    # 7 — taux de matérialisation (le seul pourcentage du miroir avec un seuil documenté)
    #     [élément : taux_materialisation]
    if c.actif("taux_materialisation") and margins and margins.get("ca_provisoire_total"):
        taux = margins["ca_definitif_total"] / margins["ca_provisoire_total"] * 100
        seuil = c.seuil("materialisation_pct")
        facts.update({
            "taux_materialisation_pct": round(taux, 1),
            "seuil_materialisation_pct": seuil,
            "backlog_xof": margins["backlog_total"],
        })
        puces.pour("taux_materialisation").append(
            f"Matérialisation du CA (définitif/provisoire) : {taux:.1f}%, "
            f"{'sous' if taux < seuil else 'au-dessus de'} le seuil d'alerte de {seuil:g}% — "
            f"{_m(margins['backlog_total'])} M FCFA de backlog non encore facturés"
            + _var(deltas, "backlog", "semaine") + "."
        )

    # 8 — rétention de la base cliente  [élément : retention_clients, décoché par défaut]
    if c.actif("retention_clients") and retention:
        facts.update({
            "retention_annee_cible": retention["annee_cible"],
            "retention_annee_reference": retention["annee_reference"],
            "retention_taux_pct": retention["taux_retention_pct"],
            "retention_nb_retenus": retention["clients_retenus"],
            "retention_nb_perdus": retention["clients_perdus_churn"],
            "retention_taux_churn_pct": retention["taux_churn_pct"],
            "retention_nb_nouveaux": retention["nouveaux_clients"],
            "retention_actifs_reference": retention["clients_actifs_annee_ref"],
        })
        puces.pour("retention_clients").append(
            f"Rétention {retention['annee_cible']} : {retention['taux_retention_pct']}% des "
            f"{retention['clients_actifs_annee_ref']} clients actifs en {retention['annee_reference']} ont "
            f"recommandé ({retention['clients_retenus']} retenus), {retention['clients_perdus_churn']} perdus "
            f"et {retention['nouveaux_clients']} nouveaux."
        )

    # 9 — engagement fournisseur  [élément : engagement_fournisseurs, décoché par défaut]
    # `get_supplier_intelligence` renvoie une LISTE triée par volume d'achat, pas
    # un agrégat : le total est recomposé ici sur les fournisseurs remontés, et la
    # puce le dit (« sur les N premiers ») plutôt que de laisser croire à un total
    # d'entreprise.
    if c.actif("engagement_fournisseurs") and fournisseurs:
        encours = [f for f in fournisseurs if f.get("encours_du_xof")]
        if encours:
            total_encours = sum(f["encours_du_xof"] for f in encours)
            top_f = max(encours, key=lambda f: f["encours_du_xof"])
            facts.update({
                "fournisseurs_encours_total_xof": total_encours,
                "fournisseurs_nb_suivis": len(fournisseurs),
                "fournisseurs_top_nom": top_f["name"],
                "fournisseurs_top_encours_xof": top_f["encours_du_xof"],
                "fournisseurs_top_dependance_pct": top_f.get("taux_dependance_pct"),
            })
            puces.pour("engagement_fournisseurs").append(
                f"Engagement fournisseurs : {_m(total_encours)} M FCFA d'encours dû sur les "
                f"{len(fournisseurs)} premiers fournisseurs, {top_f['name']} en tête à "
                f"{_m(top_f['encours_du_xof'])} M FCFA"
                + (f" ({top_f['taux_dependance_pct']:.0f}% des achats)."
                   if top_f.get("taux_dependance_pct") is not None else ".")
            )

    # ── Blocs 10-19 : vue 360 du pilotage, tous décochés par défaut ──────────
    # Servent le débrief ET l'onglet cockpit « Pilotage de l'activité ».

    # 10 — trajectoire pluriannuelle  [élément : ca_pluriannuel]
    pluriannuel = src["pluriannuel"]
    if c.actif("ca_pluriannuel") and pluriannuel:
        meilleure = max(pluriannuel, key=lambda a: a["ca_xof"])
        part_meilleure = (
            pluriannuel[-1]["ca_xof"] / meilleure["ca_xof"] * 100 if meilleure["ca_xof"] else None
        )
        facts.update({
            "pluriannuel_series": pluriannuel,
            "pluriannuel_meilleure_annee": meilleure["annee"],
            "pluriannuel_meilleure_ca_xof": meilleure["ca_xof"],
            "pluriannuel_part_meilleure_pct": round(part_meilleure, 1) if part_meilleure is not None else None,
        })
        serie = ", ".join(f"{a['annee']} : {_m(a['ca_xof'])}" for a in pluriannuel)
        puces.pour("ca_pluriannuel").append(
            f"CA commandé des {len(pluriannuel)} derniers exercices (M FCFA) — {serie} ; "
            f"meilleure année {meilleure['annee']}"
            + (f", l'exercice en cours (encore incomplet) en est à {part_meilleure:.0f}%."
               if part_meilleure is not None and meilleure["annee"] != y else ".")
        )

    # 11 — marge de l'exercice  [élément : marge_exercice]
    # Source distincte de `margins` : ici l'exercice seul, là le stock complet.
    marge = src["marge_exercice"]
    if c.actif("marge_exercice") and marge and marge.get("nb_dossiers"):
        facts.update({
            "marge_annee": y,
            "marge_nb_dossiers": marge["nb_dossiers"],
            "marge_provisoire_xof": marge["marge_provisoire_total"],
            "marge_definitive_xof": marge["marge_definitive_total"],
            "marge_provisoire_moy_pct": _taux_marge(marge, "provisoire"),
            "marge_definitive_moy_pct": _taux_marge(marge, "definitif"),
        })
        taux_prov, taux_def = _taux_marge(marge, "provisoire"), _taux_marge(marge, "definitif")
        puces.pour("marge_exercice").append(
            f"Marge {y} : {_m(marge['marge_provisoire_total'])} M FCFA provisoires sur "
            f"{marge['nb_dossiers']} dossiers"
            + (f" ({taux_prov:.1f}% du CA provisoire)" if taux_prov is not None else "")
            + f", {_m(marge['marge_definitive_total'])} M FCFA définitifs constatés"
            + (f" ({taux_def:.1f}% du CA définitif)" if taux_def is not None else "")
            + "."
        )

    # 12 — prévision d'atterrissage  [élément : prevision_atterrissage]
    forecast = src["forecast"]
    projection = (forecast or {}).get("projection_fin_trimestre", {})
    if c.actif("prevision_atterrissage") and projection.get("realiste_xof") is not None:
        facts.update({
            "atterrissage_trimestre": forecast.get("trimestre"),
            "atterrissage_realise_xof": forecast.get("realise_a_ce_jour_xof"),
            "atterrissage_realiste_xof": projection.get("realiste_xof"),
            "atterrissage_pessimiste_xof": projection.get("pessimiste_xof"),
            "atterrissage_optimiste_xof": projection.get("optimiste_xof"),
        })
        texte = f"Atterrissage {forecast.get('trimestre')} : "
        if forecast.get("realise_a_ce_jour_xof") is not None:
            texte += f"{_m(forecast['realise_a_ce_jour_xof'])} M FCFA déjà commandés, "
        texte += f"projection de fin de trimestre à {_m(projection['realiste_xof'])} M FCFA en scénario réaliste"
        if projection.get("pessimiste_xof") is not None and projection.get("optimiste_xof") is not None:
            texte += f" (fourchette {_m(projection['pessimiste_xof'])} à {_m(projection['optimiste_xof'])})"
        puces.pour("prevision_atterrissage").append(texte + ".")

    # 13 — taux de transformation  [élément : taux_transformation]
    win_rate, lost = src["win_rate"], src["lost"]
    if c.actif("taux_transformation") and win_rate:
        facts.update({
            "transformation_taux_nb_pct": win_rate["taux_nb_pct"],
            "transformation_taux_valeur_pct": win_rate["taux_valeur_pct"],
        })
        texte = (
            f"Transformation commerciale : {win_rate['taux_nb_pct']}% d'affaires gagnées en nombre, "
            f"{win_rate['taux_valeur_pct']}% en valeur"
        )
        perdant = lost["by_client"][0] if lost and lost.get("by_client") else None
        if perdant:
            facts.update({
                "transformation_nb_perdus": lost["nb_total"],
                "transformation_top_perdant": perdant,
            })
            texte += (
                f" ; {lost['nb_total']} affaires perdues, {perdant['client']} en concentre le plus "
                f"({_m(perdant['montant_xof'])} M FCFA sur {perdant['nb']})"
            )
        puces.pour("taux_transformation").append(texte + ".")

    # 14 — affaires à échéance sous 60 jours  [élément : echeances_affaires]
    # Même helper que le DC : la table `contracts` étant vide, ce sont les
    # opportunités ouvertes qui portent la notion d'échéance.
    if c.actif("echeances_affaires"):
        _echeances(facts, puces.pour("echeances_affaires"), src["opportunites"], jours=60)

    # 15 — délai d'encaissement  [élément : delai_encaissement]
    collecte = src["collecte"]
    if c.actif("delai_encaissement") and collecte and "error" not in collecte:
        delai_reel = collecte.get("delai_moyen_recouvrement_reel_jours")
        facts.update({
            "encaissement_delai_reel_jours": delai_reel,
            "encaissement_retard_impayes_jours": collecte.get("retard_moyen_impayes_jours"),
            "encaissement_taux_recouvrement_pct": collecte.get("taux_recouvrement_pct"),
            "encaissement_en_attente_xof": collecte.get("montant_en_attente_xof"),
            "encaissement_nb_souffrance": collecte.get("nb_impayes_en_souffrance"),
        })
        tete = (
            f"Encaissement : délai réel moyen de {delai_reel} j entre facture et paiement"
            if delai_reel is not None
            # L'absence de délai réel est une info de qualité de données, pas un zéro.
            else "Encaissement : délai réel non mesurable (dates de paiement non synchronisées)"
        )
        puces.pour("delai_encaissement").append(
            tete + f" ; {collecte.get('taux_recouvrement_pct', 0)}% des factures recouvrées, "
            f"{_m(collecte.get('montant_en_attente_xof'))} M FCFA en attente sur "
            f"{collecte.get('nb_impayes_en_souffrance', 0)} factures en souffrance "
            f"(retard moyen {collecte.get('retard_moyen_impayes_jours', 0)} j)."
        )

    # 16 — réalisé par commercial  [élément : performance_commerciaux]
    # Même helper que le DC : la table d'objectifs étant vide, la puce répartit
    # le réalisé et le dit.
    if c.actif("performance_commerciaux"):
        _couverture_objectifs(facts, puces.pour("performance_commerciaux"), src["par_commercial"], y)

    # 17 — mix sectoriel  [élément : mix_sectoriel]
    secteurs = src["secteurs"]
    if c.actif("mix_sectoriel") and secteurs:
        total_secteurs = sum(s["ca_total_xof"] for s in secteurs)
        tete_secteur = secteurs[0]
        part_secteur = (
            tete_secteur["ca_total_xof"] / total_secteurs * 100 if total_secteurs else None
        )
        facts.update({
            "secteurs_annee": y,
            "secteurs_nb": len(secteurs),
            "secteurs_ca_total_xof": total_secteurs,
            "secteurs_top": tete_secteur["secteur"],
            "secteurs_top_ca_xof": tete_secteur["ca_total_xof"],
            "secteurs_top_part_pct": round(part_secteur, 1) if part_secteur is not None else None,
        })
        # « Non renseigné » en tête n'est pas un secteur dominant, c'est un
        # défaut de qualification : la puce le dit plutôt que de l'affirmer.
        if tete_secteur["secteur"] == "Non renseigné":
            puces.pour("mix_sectoriel").append(
                f"Mix sectoriel {y} : le premier poste est « Non renseigné »"
                + (f" ({part_secteur:.0f}% des {_m(total_secteurs)} M FCFA commandés)"
                   if part_secteur is not None else "")
                + " — la qualification sectorielle des clients reste à faire avant toute lecture."
            )
        else:
            puces.pour("mix_sectoriel").append(
                f"Mix sectoriel {y} : {tete_secteur['secteur']} en tête à "
                f"{_m(tete_secteur['ca_total_xof'])} M FCFA"
                + (f" ({part_secteur:.0f}% des {_m(total_secteurs)} M FCFA commandés)"
                   if part_secteur is not None else "")
                + f", sur {len(secteurs)} secteurs suivis."
            )

    # 18 — rythme mensuel  [élément : rythme_mensuel]
    mensuel = src["mensuel"]
    if c.actif("rythme_mensuel") and mensuel:
        # Le mois en cours est incomplet : il n'entre dans la comparaison que
        # s'il est le seul disponible (janvier), et la moyenne reste alors la
        # sienne — jamais un « effondrement » calculé contre lui-même.
        complets = [m for m in mensuel if m["mois"] < arret.month] or mensuel
        moyenne = sum(m["ca_xof"] for m in complets) / len(complets)
        dernier = complets[-1]
        part_mois = (dernier["ca_xof"] / moyenne * 100) if moyenne else None
        facts.update({
            "mensuel_annee": y,
            "mensuel_series": mensuel,
            "mensuel_moyenne_xof": round(moyenne),
            "mensuel_dernier_mois": dernier["mois"],
            "mensuel_dernier_ca_xof": dernier["ca_xof"],
            "mensuel_dernier_vs_moyenne_pct": round(part_mois, 1) if part_mois is not None else None,
        })
        puces.pour("rythme_mensuel").append(
            f"Rythme mensuel {y} : {_MOIS[dernier['mois']]} à {_m(dernier['ca_xof'])} M FCFA contre "
            f"une moyenne de {_m(moyenne)} M FCFA sur les mois écoulés"
            + (f" ({part_mois:.0f}% de la moyenne)." if part_mois is not None else ".")
        )

    # 19 — affaires imminentes  [élément : affaires_imminentes]
    hot = src["hot_leads"]
    if c.actif("affaires_imminentes") and hot:
        total_pondere = sum(l.get("score_pondere_xof") or 0 for l in hot)
        tete_lead = hot[0]
        facts.update({
            "imminentes_nb": len(hot),
            "imminentes_pondere_xof": total_pondere,
            "imminentes_top": tete_lead,
        })
        puces.pour("affaires_imminentes").append(
            f"{len(hot)} affaires chaudes au pipeline pour {_m(total_pondere)} M FCFA pondérés — "
            f"la première : {tete_lead['opportunite']} ({tete_lead['client']}, "
            f"{_m(tete_lead['score_pondere_xof'])} M FCFA pondérés)."
        )

    # 20 — factures échues, clients ET fournisseurs  [élément : factures_echues]
    # Chiffres de uc_daf (amount_residual, hors annulées) — les mêmes que
    # l'écran Relation commerciale. `fournisseur` peut être None (aucune
    # facture synchronisée) : la puce le dit au lieu d'afficher un zéro.
    situation = src["situation_factures"]
    if c.actif("factures_echues") and situation:
        client_sit = situation["client"]
        fournisseur_sit = situation.get("fournisseur")
        facts.update({
            "factures_echues_clients_nb": client_sit["nb_echues"],
            "factures_echues_clients_xof": client_sit["montant_echu_xof"],
            "factures_echues_clients_90j_xof": client_sit["montant_contentieux_xof"],
        })
        tete_facture = (
            f"Factures échues : {client_sit['nb_echues']} factures clients non réglées pour "
            f"{_m(client_sit['montant_echu_xof'])} M FCFA, dont "
            f"{_m(client_sit['montant_contentieux_xof'])} M au-delà de 90 jours"
        )
        if fournisseur_sit:
            facts.update({
                "factures_echues_fournisseurs_nb": fournisseur_sit["nb_echues"],
                "factures_echues_fournisseurs_xof": fournisseur_sit["dette_echue_xof"],
            })
            puces.pour("factures_echues").append(
                tete_facture + f" ; côté fournisseurs, {fournisseur_sit['nb_echues']} factures "
                f"échues pour {_m(fournisseur_sit['dette_echue_xof'])} M FCFA dus — un stock de "
                "cette taille se traite en plan d'assainissement (provision, échéancier négocié), "
                "pas en relances au fil de l'eau."
            )
        else:
            puces.pour("factures_echues").append(
                tete_facture + " ; côté fournisseurs, aucune facture n'est synchronisée : "
                "la dette échue n'est pas mesurable."
            )

    # 21 — visibilité du carnet  [élément : visibilite_carnet]
    # « Combien de mois de visibilité j'ai ? » — backlog rapporté au facturé
    # mensuel moyen. Le dénominateur est un facturé RÉEL : aucun objectif n'est
    # saisi en base, et en dériver un ferait passer une hypothèse pour une cible.
    visibilite = src["visibilite"]
    if c.actif("visibilite_carnet") and visibilite:
        seuil_mois = c.seuil("visibilite_mois_min")
        if visibilite.get("mesurable"):
            mois = visibilite["mois_visibilite"]
            facts.update({
                "visibilite_mois": mois,
                "visibilite_seuil_mois": seuil_mois,
                "visibilite_backlog_xof": visibilite["backlog_xof"],
                "visibilite_facture_mensuel_xof": visibilite["facture_mensuel_moyen_xof"],
            })
            puces.pour("visibilite_carnet").append(
                f"Visibilité du carnet : {mois:.1f} mois de facturation couverts "
                f"({_m(visibilite['backlog_xof'])} M FCFA de backlog pour "
                f"{_m(visibilite['facture_mensuel_moyen_xof'])} M FCFA facturés par mois en "
                f"moyenne sur {visibilite['fenetre_mois']} mois), "
                f"{'sous le' if mois < seuil_mois else 'au-dessus du'} plancher de "
                f"{seuil_mois:g} mois."
            )
        else:
            puces.pour("visibilite_carnet").append(
                "Visibilité du carnet non mesurable : "
                f"{visibilite.get('raison', 'dénominateur indisponible')}."
            )

    # 22 — book-to-bill  [élément : book_to_bill]
    # « Est-ce que je remplis plus vite que je ne consomme ? »
    btb = src["btb"]
    if c.actif("book_to_bill") and btb and btb.get("mesurable"):
        plancher = c.seuil("book_to_bill_min")
        ratio = btb["ratio"]
        facts.update({
            "book_to_bill": ratio,
            "book_to_bill_plancher": plancher,
            "book_to_bill_commande_xof": btb["commande_xof"],
            "book_to_bill_facture_xof": btb["facture_xof"],
        })
        puces.pour("book_to_bill").append(
            f"Book-to-bill sur {btb['fenetre_mois']} mois : {ratio:.2f} "
            f"({_m(btb['commande_xof'])} M FCFA commandés pour {_m(btb['facture_xof'])} M "
            f"facturés) — le carnet se remplit "
            f"{'plus vite' if ratio >= plancher else 'moins vite'} qu'il ne se vide. "
            f"Réserve : {btb['reserve']}."
        )

    if c.actif("questions_sans_reponse"):
        _puce_couverture(facts, puces, role)

    # L'action du jour n'est PAS un élément décochable : elle est la 5e ligne
    # contractuelle du résumé (cf. narratif._SYSTEM_RESUME et _fallback_resume).
    # En revanche, ses entrées suivent les éléments actifs — une action qui cite
    # un dossier dont plus aucune puce ne parle serait indéfendable : le lecteur
    # ne saurait pas d'où elle sort. Le repli de dernier rang (échéancier
    # fournisseurs) reste toujours chiffrable.
    rupture_top = rupture_comptes[0] if rupture_comptes else None
    action = _action_du_jour(
        croisement_top if c.actif("croisement_impaye_rupture") else None,
        arb_top if c.actif("file_arbitrage") else None,
        rupture_top if c.actif("rupture_rythme") else None,
        # `None` et non `0` : une trésorerie non interrogée n'est pas une
        # trésorerie à l'équilibre (cf. _action_du_jour).
        position_nette,
    )

    return {"facts": facts, "bullets": puces.liste(), "blocs": puces.par_bloc(),
            "action": action}


# Étapes qui ferment une opportunité. `stade` est du texte libre venu d'Odoo et
# mélange deux nomenclatures (« 6-Gagné » / « Won », « 7-Perdu » / « Lost ») : on
# reconnaît donc par mot-clé, sans casse ni accent, plutôt que par égalité.
_STADES_FERMES = ("gagn", "won", "perdu", "lost", "annul", "cancel", "suspendu")


def _est_ouverte(opp: dict) -> bool:
    stade = (opp.get("stade") or "").lower()
    return not any(mot in stade for mot in _STADES_FERMES)


def _echeances(facts: dict, bullets: list[str], opportunities: list[dict], jours: int) -> None:
    """Opportunités encore ouvertes dont la date de clôture tombe dans la fenêtre.

    Comble la promesse de ROLE_FOCUS (« les renouvellements et échéances à
    venir ») que la table `contracts`, vide, ne peut pas tenir. Le filtre sur les
    étapes ouvertes est indispensable : `deadline` est renseignée sur 6401 des
    6675 opportunités, gagnées, perdues et annulées comprises.
    """
    aujourd_hui = datetime.now().date()
    limite = aujourd_hui + timedelta(days=jours)
    proches = []
    for opp in opportunities:
        brut = opp.get("deadline")
        if not brut or not _est_ouverte(opp):
            continue
        try:
            echeance = datetime.fromisoformat(str(brut)).date()
        except ValueError:
            continue
        if aujourd_hui <= echeance <= limite:
            proches.append((echeance, opp))

    facts["echeances_fenetre_jours"] = jours
    facts["echeances_nb"] = len(proches)
    if not proches:
        # Dit explicitement qu'il n'y a rien, plutôt que de laisser un trou : sur
        # un débrief, l'absence de puce se lit comme une donnée manquante.
        bullets.append(f"Aucune opportunité ouverte n'arrive à échéance dans les {jours} prochains jours.")
        return

    proches.sort(key=lambda p: p[0])
    montant = sum(o.get("revenu_attendu_xof") or 0 for _, o in proches)
    premiere, opp = proches[0]
    facts.update({
        "echeances_montant_xof": montant,
        "echeances_prochaine": {
            "opportunite": opp.get("opportunite"),
            "client": opp.get("client"),
            "deadline": premiere.isoformat(),
            "revenu_attendu_xof": opp.get("revenu_attendu_xof"),
        },
    })
    bullets.append(
        f"{len(proches)} opportunité(s) ouverte(s) à échéance sous {jours} j pour {_m(montant)} M FCFA — "
        f"la plus proche : {opp.get('opportunite')} ({opp.get('client')}) le {_fr(premiere.isoformat())}."
    )


def _couverture_objectifs(facts: dict, bullets: list[str], par_commercial: list[dict], annee: int) -> None:
    """Couverture de l'équipe commerciale, promise par ROLE_FOCUS et jamais tenue.

    ATTENTION — la table `commercial_objectives` est VIDE : il n'existe aucun
    objectif saisi. La puce ne compare donc pas à un objectif mais RÉPARTIT le
    réalisé, et le dit. Annoncer une « couverture » calculée sur un objectif
    dérivé sans le signaler reproduirait exactement le reproche que
    uc_commercial/objectifs.py documente à propos de ce briefing.
    """
    actifs = [c for c in (par_commercial or []) if c.get("ca_total_xof")]
    if not actifs:
        return
    total = sum(c["ca_total_xof"] for c in actifs)
    tete = max(actifs, key=lambda c: c["ca_total_xof"])
    part = (tete["ca_total_xof"] / total * 100) if total else None
    facts.update({
        "couverture_annee": annee,
        "couverture_nb_commerciaux": len(actifs),
        "couverture_ca_total_xof": total,
        "couverture_top_commercial": tete["commercial"],
        "couverture_top_ca_xof": tete["ca_total_xof"],
        "couverture_top_part_pct": round(part, 1) if part is not None else None,
        "couverture_objectif_saisi": False,
    })
    bullets.append(
        f"Réalisé {annee} par commercial : {_m(total)} M FCFA sur {len(actifs)} commerciaux, "
        f"{tete['commercial']} en tête à {_m(tete['ca_total_xof'])} M FCFA"
        + (f" ({part:.0f}% du total)" if part is not None else "")
        + " — aucun objectif n'étant saisi en base, c'est une répartition du réalisé, pas un taux d'atteinte."
    )


def _mix_offre(facts: dict, bullets: list[str], par_produit: list[dict], annee: int, cle: str) -> None:
    """Répartition du CA par famille d'offre. `cle` préfixe les faits, le DC et le
    DO lisant la même source pour deux lectures différentes (mix commercial /
    charge de production)."""
    lignes = [p for p in (par_produit or []) if p.get("ca_total_xof")]
    if not lignes:
        return
    total = sum(p["ca_total_xof"] for p in lignes)
    tete = lignes[0]
    part = (tete["ca_total_xof"] / total * 100) if total else None
    # Le libellé produit vient d'Odoo et contient référence + description
    # tabulées : on ne garde que la partie utile à l'oral.
    nom = str(tete["produit"]).split("\t")[0].strip()
    facts.update({
        f"{cle}_annee": annee,
        f"{cle}_nb_familles": len(lignes),
        f"{cle}_ca_total_xof": total,
        f"{cle}_top_produit": nom,
        f"{cle}_top_ca_xof": tete["ca_total_xof"],
        f"{cle}_top_part_pct": round(part, 1) if part is not None else None,
    })
    bullets.append(
        f"Mix d'offre {annee} : {_m(total)} M FCFA sur {len(lignes)} familles suivies, "
        f"{nom} en tête à {_m(tete['ca_total_xof'])} M FCFA"
        + (f" ({part:.0f}% du total)." if part is not None else ".")
    )


def _puce_mouvements(facts: dict, bullets: list[str], mvt: dict | None) -> None:
    """« Qu'est-ce qui a bougé depuis le dernier briefing ? »

    Dit toujours quelque chose, y compris quand rien n'a bougé : sur ce volume
    (environ 2 commandes par jour ouvré, un jour ouvré sur trois sans aucune),
    une puce absente se lirait comme une donnée manquante alors qu'elle est une
    information — la période a été calme.

    Le changement d'étape est traité à part parce qu'il n'est pas toujours
    mesurable : il se lit par différence entre deux snapshots du pipeline, et la
    puce le dit plutôt que d'annoncer « aucun mouvement » là où il n'y a
    simplement pas de point de comparaison.
    """
    if not mvt:
        return
    cmd, fact, regl = mvt["commandes_entrees"], mvt["factures_emises"], mvt["factures_reglees"]
    facts.update({
        "mouvements_depuis": mvt["depuis"],
        "mouvements_jusqu_a": mvt["jusqu_a"],
        "mouvements_nb_commandes": cmd["nb"],
        "mouvements_commandes_xof": cmd["montant_xof"],
        "mouvements_nb_factures": fact["nb"],
        "mouvements_nb_reglements": regl["nb"],
        "mouvements_reglements_xof": regl["montant_xof"],
    })
    if not mvt["total_evenements"]:
        bullets.append(
            f"Aucun mouvement enregistré entre le {_fr(mvt['depuis'])} et le "
            f"{_fr(mvt['jusqu_a'])} : ni commande, ni facture, ni retouche d'opportunité."
        )
        return

    morceaux = []
    if cmd["nb"]:
        tete = cmd["top"][0]
        morceaux.append(
            f"{cmd['nb']} commande(s) pour {_mm(cmd['montant_xof'])} "
            f"(la plus grosse : {tete['tiers']}, {_mm(tete['montant_xof'])})"
        )
    if fact["nb"]:
        morceaux.append(f"{fact['nb']} facture(s) émise(s) pour {_mm(fact['montant_xof'])}")
    if regl["nb"]:
        morceaux.append(f"{regl['nb']} règlement(s) reçu(s) pour {_mm(regl['montant_xof'])}")
    # Les retouches d'opportunité comptent dans `total_evenements` : les omettre
    # ici produisait une puce vide (« Depuis le 20/08 : . ») les périodes où
    # elles étaient le SEUL mouvement. Toute catégorie qui entre dans le
    # compteur doit pouvoir se dire.
    retouches = mvt["opportunites_retouchees"]
    if retouches["nb"]:
        facts["mouvements_nb_opportunites"] = retouches["nb"]
        morceaux.append(
            f"{retouches['nb']} opportunité(s) retouchée(s) pour "
            f"{_mm(retouches['montant_xof'])} espérés"
        )
    achats = mvt["achats_engages"]
    if achats["nb"]:
        facts["mouvements_nb_achats"] = achats["nb"]
        facts["mouvements_achats_xof"] = achats["montant_xof"]
        morceaux.append(
            f"{achats['nb']} commande(s) d'achat engagée(s) pour "
            f"{_mm(achats['montant_xof'])}"
        )

    etape = mvt["changements_etape"]
    if etape.get("mesurable") and etape["nb"]:
        facts["mouvements_nb_changements_etape"] = etape["nb"]
        premier = etape["top"][0]
        morceaux.append(
            f"{etape['nb']} changement(s) d'étape (dont {premier['client']} : "
            f"{premier['de']} vers {premier['vers']})"
        )
    elif not etape.get("mesurable"):
        morceaux.append(
            "les changements d'étape ne sont pas mesurables sur la période "
            f"({etape.get('raison', 'source indisponible')})"
        )

    bullets.append(f"Depuis le {_fr(mvt['depuis'])} : " + ", ".join(morceaux) + ".")


def _puce_hygiene_pipe(facts: dict, bullets: list[str], hyg: dict | None) -> None:
    """Les affaires à relancer, et le pipe à assainir — deux tas, une puce.

    Les deux tiennent dans la même phrase à dessein : le nombre « à relancer »
    est petit et le nombre « à assainir » est énorme, et c'est précisément leur
    rapport qui est l'information. Publier le second seul ferait fuir ; publier
    le premier seul laisserait croire que le montant de pipeline affiché
    ailleurs est sincère.
    """
    if not hyg:
        return
    relance, assainir = hyg["a_relancer"], hyg["a_assainir"]
    facts.update({
        "hygiene_seuil_jours": hyg["seuil_jours"],
        "hygiene_a_relancer_nb": relance["nb"],
        "hygiene_a_relancer_xof": relance["montant_xof"],
        "hygiene_a_assainir_nb": assainir["nb"],
        "hygiene_a_assainir_xof": assainir["montant_xof"],
        "hygiene_sans_echeance_nb": hyg["sans_echeance"]["nb"],
    })
    if relance["nb"]:
        tete = relance["top"][0]
        debut = (
            f"{relance['nb']} affaire(s) encore dans les temps pour "
            f"{_m(relance['montant_xof'])} M FCFA n'ont pas bougé depuis plus de "
            f"{hyg['seuil_jours']} j — la première : {tete['opportunite']} ({tete['client']}, "
            f"{_m(tete['revenu_attendu_xof'])} M FCFA, échéance le {_fr(tete['deadline'])}, "
            f"{tete['jours_silence']} j de silence)"
        )
    else:
        debut = (
            f"Aucune affaire encore dans les temps ne dort depuis plus de "
            f"{hyg['seuil_jours']} j"
        )
    bullets.append(
        debut + f". En regard, {assainir['nb']} opportunité(s) restées ouvertes pour "
        f"{_m(assainir['montant_xof'])} M FCFA ont une échéance déjà dépassée : tant "
        f"qu'elles ne sont pas clôturées, tout montant de pipeline publié les inclut."
    )


def _puce_couverture(facts: dict, puces: Puces, role: str) -> None:
    """Les questions de la trame que les données ne permettent pas de traiter.

    Une SEULE ligne, et non une puce d'aveu par question : la direction des
    opérations en compterait cinq sur huit, et le briefing deviendrait un
    constat d'échec avant d'être un outil.

    Elle est publiée plutôt que tue parce qu'un directeur qui ne voit pas ce qui
    manque croit voir un tableau complet. Et parce que c'est le seul endroit du
    produit où le coût de la qualité du référentiel Odoo revient chaque matin
    sous les yeux de celui qui peut le faire corriger.
    """
    manquantes = preferences.SANS_REPONSE.get(role, [])
    if not manquantes:
        return
    facts["questions_couvertes"] = len(preferences.questions_de(role))
    facts["questions_sans_reponse"] = [
        {"question": question, "cause": cause} for question, cause in manquantes
    ]
    citees = " ; ".join(f"« {question} » — {cause}" for question, cause in manquantes)
    puces.ajouter(
        "questions_sans_reponse",
        f"{len(manquantes)} question(s) du briefing restent sans réponse aujourd'hui : {citees}.",
    )


def _puce_ca_periode(facts: dict, puces: Puces, element: str, deltas: dict,
                     cle_mois: str, cle_ytd: str, libelle: str,
                     cle_nb: str | None = None) -> None:
    """« Combien j'ai commandé / facturé hier, et depuis le 1er ? »

    Le cumul du mois porte la variation à un jour, le cumul de l'exercice celle
    à trente : à deux commandes par jour ouvré, un delta quotidien sur l'année
    entière serait invisible, et un delta mensuel sur la journée, du bruit.

    La puce ne sort PAS si l'indicateur du mois est introuvable : c'est le seul
    cas où l'historisation n'a jamais tourné, et une puce annonçant « 0 M FCFA
    commandés » vaudrait moins que son absence.
    """
    mois = deltas.get(cle_mois) or {}
    ytd = deltas.get(cle_ytd) or {}
    if mois.get("valeur") is None:
        return
    facts[f"{element}_mois_xof"] = mois["valeur"]
    facts[f"{element}_ytd_xof"] = ytd.get("valeur")
    texte = (
        f"{libelle} : {_m(mois['valeur'])} M FCFA depuis le 1er du mois"
        + _var(deltas, cle_mois, "j1")
    )
    if ytd.get("valeur") is not None:
        texte += (
            f", {_m(ytd['valeur'])} M FCFA depuis le 1er janvier"
            + _var(deltas, cle_ytd, "mois")
        )
    if cle_nb:
        nb = (deltas.get(cle_nb) or {}).get("valeur")
        if nb is not None:
            facts[f"{element}_nb"] = int(nb)
            texte += f", sur {int(nb)} commandes"
    puces.ajouter(element, texte + ".")


def _puce_carnet(facts: dict, puces: Puces, element: str, deltas: dict,
                 margins: dict | None) -> None:
    """« Où en est mon carnet de commandes ? » — le vendu pas encore facturé.

    Lu sur `dossiers.backlog` et non sur `invoice_status` : ce champ Odoo n'est
    pas synchronisé, et le reste-à-facturer ligne à ligne est hors d'atteinte
    (`qty_invoiced` vaut zéro sur les 19 510 lignes du miroir).
    """
    backlog = (deltas.get("backlog") or {}).get("valeur")
    if backlog is None and margins:
        backlog = margins.get("backlog_total")
    if backlog is None:
        return
    facts["carnet_backlog_xof"] = backlog
    texte = f"Carnet de commandes : {_m(backlog)} M FCFA vendus et pas encore facturés"
    texte += _var(deltas, "backlog", "semaine")
    reste = (deltas.get("reste_a_encaisser") or {}).get("valeur")
    if reste is not None:
        facts["carnet_reste_a_encaisser_xof"] = reste
        texte += f", dont {_m(reste)} M FCFA restent à encaisser sur les dossiers ouverts"
    puces.ajouter(element, texte + ".")


def _puce_concentration_clients(facts: dict, puces: Puces, element: str,
                                top_clients: list[dict], ytd: dict | None,
                                seuil_pct: float) -> None:
    """« Suis-je trop dépendant d'un client ? » — top 3 ET top 5.

    Le top 3 vient de la trame, le top 5 est le seuil de vigilance déjà en
    usage côté direction générale : les publier ensemble évite que les deux
    directions s'alertent sur des bases différentes du même risque.

    Réserve non dite dans la puce mais structurante : le groupe Orange est
    éclaté en dix tiers sans lien de parenté dans Odoo. Le premier client réel
    du portefeuille n'apparaît donc dans aucun classement (anomalie A16).
    """
    if not top_clients or not ytd or not ytd.get("revenue_xof"):
        return
    base = ytd["revenue_xof"]
    top3 = top_clients[:3]
    top5 = top_clients[:5]
    part3 = sum(c["ca_total_xof"] for c in top3) / base * 100
    part5 = sum(c["ca_total_xof"] for c in top5) / base * 100
    tete = top_clients[0]
    facts.update({
        "dependance_top3_pct": round(part3, 1),
        "dependance_top5_pct": round(part5, 1),
        "dependance_seuil_pct": seuil_pct,
        "dependance_top1_client": tete["client"],
        "dependance_top1_pct": round(tete["ca_total_xof"] / base * 100, 1),
    })
    puces.ajouter(
        element,
        f"Dépendance clients : le top 3 pèse {part3:.0f}% des {_m(base)} M FCFA commandés, "
        f"le top 5 {part5:.0f}% face au seuil de vigilance de {seuil_pct:g}% — "
        f"{tete['client']} premier à {tete['ca_total_xof'] / base * 100:.0f}%."
    )


def _puce_attente_facturation(facts: dict, puces: Puces, element: str,
                              visibilite: dict | None) -> None:
    """« Combien de CA dort en attente de facturation ? »

    Le backlog seul ne dit rien : 9 175 M FCFA sont un chiffre, pas un
    diagnostic. Rapporté au facturé mensuel moyen, il devient un délai — et un
    délai se compare à ce qu'on juge acceptable.

    Le WIP de production (temps saisis non facturés) n'y entre pas : aucune
    saisie des temps n'est synchronisée.
    """
    if not visibilite:
        return
    backlog = visibilite.get("backlog_xof")
    if backlog is None:
        return
    facts["attente_facturation_xof"] = backlog
    texte = f"En attente de facturation : {_m(backlog)} M FCFA vendus non facturés"
    if visibilite.get("mesurable"):
        facts["attente_facturation_mois"] = visibilite["mois_visibilite"]
        texte += (
            f", soit {visibilite['mois_visibilite']:.1f} mois au rythme de facturation "
            f"actuel ({_m(visibilite['facture_mensuel_moyen_xof'])} M FCFA par mois)"
        )
    else:
        texte += (
            f" — non convertibles en délai : {visibilite.get('raison', 'rythme indisponible')}"
        )
    puces.ajouter(element, texte + ". Les temps non facturés n'y entrent pas, "
                           "aucune saisie des temps n'étant synchronisée.")


_DC_SOURCES: dict[str, tuple[str, ...]] = {
    "pipeline": ("pipeline_ouvert",),
    "opportunites": ("pipeline_ouvert", "forecast_scenarios", "echeances_opportunites"),
    "win_rate": ("taux_victoire",),
    "lost": ("pertes_par_client",),
    "hot_leads": ("top_lead",),
    "par_commercial": ("couverture_objectifs",),
    "par_produit": ("mix_offre",),
    "mouvements": ("mouvements_recents",),
    "hygiene": ("hygiene_pipe",),
    "margins": ("carnet_commandes",),
    "top_clients": ("concentration_clients",),
    "ytd": ("concentration_clients",),
}

_DC_DELTAS = ["ca_commande_ytd", "ca_commande_mois", "pipe_brut", "pipe_actif_brut",
              "pipe_actif_pondere", "nb_commandes_ytd", "nb_opportunites_ouvertes",
              "backlog", "reste_a_encaisser"]


async def build_dir_commercial_facts(crm, composition: Composition | None = None) -> dict:
    role = "dir_commercial"
    c = composition or Composition()
    y = datetime.now().year

    src = await _resoudre(
        {
            "pipeline": (lambda: crm.get_pipeline_stats(), None),
            "opportunites": (lambda: crm.list_opportunities(limit=500), []),
            "win_rate": (lambda: crm.get_win_rate(), None),
            "lost": (lambda: crm.get_lost_deals(limit=5), None),
            "hot_leads": (lambda: crm.get_hot_leads(limit=5), []),
            "par_commercial": (lambda: crm.get_revenue_by_salesperson(year=y), []),
            "par_produit": (lambda: crm.get_revenue_by_product(year=y, limit=10), []),
            # Fenêtre de 7 jours et non « hier » : à deux commandes par jour
            # ouvré et un jour sur trois sans mouvement, un briefing qui ne
            # regarde que la veille est vide deux matins sur trois.
            "mouvements": (
                lambda: evenements.mouvements(datetime.now().date() - timedelta(days=7)), None),
            "hygiene": (
                lambda: evenements.hygiene_pipe(seuil_jours=int(c.seuil("dormance_jours"))), None),
            "margins": (lambda: crm.get_margin_stats(), None),
            "top_clients": (lambda: crm.get_top_clients(limit=10, year=y), []),
            "ytd": (lambda: crm.get_ytd_stats(y), None),
        },
        _DC_SOURCES,
        c,
    )
    deltas = await _deltas(_DC_DELTAS)
    pipeline, opportunities = src["pipeline"], src["opportunites"]
    win_rate, lost, hot_leads = src["win_rate"], src["lost"], src["hot_leads"]
    scen = build_pipeline_forecast(opportunities)["scenarios"]

    facts: dict = {}
    puces = Puces(role)

    if c.actif("pipeline_ouvert") and pipeline:
        facts.update({
            "pipeline_total_xof": pipeline["ca_potentiel_brut_xof"],
            "pipeline_pondere_xof": pipeline["ca_potentiel_pondéré_xof"],
            "nb_opportunites_ouvertes": scen["nb_opportunites"],
        })
        # Le pipe « encore dans les temps » accompagne systématiquement le pipe
        # brut : sur le miroir, 82 % du montant ouvert porte une échéance déjà
        # dépassée. Publier le brut seul, c'est publier un chiffre douze fois
        # trop grand, sans que le décideur ait le moyen de s'en apercevoir.
        # Brut ET actif viennent tous deux des indicateurs quand ils sont
        # disponibles : les mélanger avec `get_pipeline_stats` dans une même
        # phrase juxtaposerait deux définitions du mot « ouvert » sans que rien
        # ne le signale. Une phrase, une source.
        actif = (deltas.get("pipe_actif_brut") or {}).get("valeur")
        brut = (deltas.get("pipe_brut") or {}).get("valeur")
        if brut is None:
            brut = pipeline["ca_potentiel_brut_xof"]
        if actif is not None:
            facts["pipeline_actif_xof"] = actif
            facts["pipeline_actif_pondere_xof"] = (
                deltas.get("pipe_actif_pondere") or {}).get("valeur")
        # `scen["nb_opportunites"]` compte ce qui a été RAMENÉ, pas ce qui
        # existe : `list_opportunities(limit=500)` plafonne à 500, et la puce
        # annonçait « 500 opportunités » alors que le pipe en porte 3 969. Un
        # nombre qui vaut exactement la limite de la requête est une troncature
        # déguisée en mesure.
        nb_ouvertes = (deltas.get("nb_opportunites_ouvertes") or {}).get("valeur")
        nb = int(nb_ouvertes) if nb_ouvertes is not None else scen["nb_opportunites"]
        facts["nb_opportunites_ouvertes"] = nb
        puces.pour("pipeline_ouvert").append(
            f"Pipeline ouvert : {_m(brut)} M FCFA brut, "
            f"{_m(pipeline['ca_potentiel_pondéré_xof'])} M FCFA pondéré "
            f"({nb} opportunités)"
            + (
                f" — dont {_m(actif)} M FCFA seulement sur des affaires dont "
                f"l'échéance n'est pas encore passée"
                + _var(deltas, "pipe_actif_brut", "semaine")
                if actif is not None else ""
            )
            + "."
        )

    if c.actif("forecast_scenarios") and opportunities:
        facts.update({
            "forecast_realiste_xof": scen["realiste_xof"],
            "forecast_pessimiste_xof": scen["pessimiste_xof"],
            "forecast_optimiste_xof": scen["optimiste_xof"],
        })
        puces.pour("forecast_scenarios").append(
            f"Forecast 6 mois : {_m(scen['pessimiste_xof'])} à {_m(scen['optimiste_xof'])} M FCFA "
            f"(réaliste {_m(scen['realiste_xof'])} M FCFA)."
        )

    if c.actif("taux_victoire") and win_rate:
        facts.update({
            "taux_victoire_nb_pct": win_rate["taux_nb_pct"],
            "taux_victoire_valeur_pct": win_rate["taux_valeur_pct"],
        })
        puces.pour("taux_victoire").append(
            f"Taux de victoire : {win_rate['taux_nb_pct']}% en nombre, {win_rate['taux_valeur_pct']}% en valeur."
        )

    if c.actif("pertes_par_client") and lost:
        top_client_perdant = lost["by_client"][0] if lost["by_client"] else None
        facts.update({"nb_deals_perdus": lost["nb_total"], "top_client_perdant": top_client_perdant})
        if top_client_perdant:
            puces.pour("pertes_par_client").append(
                f"Client concentrant le plus de pertes : {top_client_perdant['client']} "
                f"({_m(top_client_perdant['montant_xof'])} M FCFA sur {top_client_perdant['nb']} opportunités)."
            )

    if c.actif("top_lead") and hot_leads:
        facts["top_lead"] = hot_leads[0]
        puces.pour("top_lead").append(
            f"Lead le plus chaud : {hot_leads[0]['opportunite']} ({hot_leads[0]['client']}), "
            f"{_m(hot_leads[0]['score_pondere_xof'])} M FCFA pondérés."
        )

    if c.actif("echeances_opportunites"):
        _echeances(facts, puces.pour("echeances_opportunites"), opportunities, jours=int(c.seuil("echeance_fenetre_jours")))

    if c.actif("couverture_objectifs"):
        _couverture_objectifs(facts, puces.pour("couverture_objectifs"), src["par_commercial"], y)

    if c.actif("mix_offre"):
        _mix_offre(facts, puces.pour("mix_offre"), src["par_produit"], y, cle="mix")

    if c.actif("mouvements_recents"):
        _puce_mouvements(facts, puces.pour("mouvements_recents"), src["mouvements"])

    if c.actif("hygiene_pipe"):
        _puce_hygiene_pipe(facts, puces.pour("hygiene_pipe"), src["hygiene"])

    if c.actif("ca_commande_periode"):
        _puce_ca_periode(facts, puces, "ca_commande_periode", deltas,
                         "ca_commande_mois", "ca_commande_ytd", "CA commandé",
                         cle_nb="nb_commandes_ytd")

    if c.actif("carnet_commandes"):
        _puce_carnet(facts, puces, "carnet_commandes", deltas, src["margins"])

    if c.actif("concentration_clients"):
        _puce_concentration_clients(facts, puces, "concentration_clients",
                                    src["top_clients"], src["ytd"],
                                    c.seuil("concentration_top5_pct"))

    if c.actif("questions_sans_reponse"):
        _puce_couverture(facts, puces, role)

    return {"facts": facts, "bullets": puces.liste(), "blocs": puces.par_bloc()}


def _puce_ca_facture(facts: dict, puces: Puces, deltas: dict) -> None:
    """« Où en est le CA facturé du mois ? » — facturé, encaissé, et commandé.

    Les trois ensemble parce qu'ils ne disent la même chose qu'assemblés :
    facturer sans encaisser est un problème de recouvrement, facturer moins
    qu'on ne commande est un problème de production. Séparés, chacun se lit
    comme une performance.

    L'objectif manque au tableau, et il manquera tant que
    `commercial_objectives` sera vide — le dériver du réalisé ferait passer une
    hypothèse pour une cible votée. La puce le dit plutôt que de le taire.

    Réserve portée dans le texte : les avoirs ne sont pas déduits, et leur poids
    est passé de 1 % à 28 % du facturé brut entre 2019 et 2026.
    """
    facture = deltas.get("ca_facture_mois") or {}
    if facture.get("valeur") is None:
        return
    encaisse = deltas.get("encaissements_mois") or {}
    facture_ytd = deltas.get("ca_facture_ytd") or {}
    commande_ytd = deltas.get("ca_commande_ytd") or {}
    facts.update({
        "facture_mois_xof": facture["valeur"],
        "facture_ytd_xof": facture_ytd.get("valeur"),
        "encaisse_mois_xof": encaisse.get("valeur"),
        "commande_ytd_xof": commande_ytd.get("valeur"),
        "objectif_saisi": False,
    })
    texte = (
        f"CA facturé : {_m(facture['valeur'])} M FCFA sur le mois"
        + _var(deltas, "ca_facture_mois", "j1")
    )
    if facture_ytd.get("valeur") is not None:
        texte += f", {_m(facture_ytd['valeur'])} M FCFA depuis janvier"
        if commande_ytd.get("valeur") is not None:
            texte += f" contre {_m(commande_ytd['valeur'])} M FCFA commandés sur la même période"
    if encaisse.get("valeur") is not None:
        # Un encaissement nul se dit, il ne s'affiche pas en montant : « 0 M FCFA
        # encaissés » se lit comme une performance catastrophique alors que la
        # cause est ailleurs — aucun règlement n'est daté après le 05/06 dans le
        # miroir. La phrase pointe le fait, pas le chiffre.
        if encaisse["valeur"]:
            texte += f" ; {_m(encaisse['valeur'])} M FCFA encaissés sur le mois"
        else:
            texte += " ; aucun règlement enregistré ce mois-ci"
    puces.ajouter(
        "ca_facture_periode",
        texte + ". Aucun objectif n'étant saisi en base, il n'y a pas de taux "
                "d'atteinte ; et les avoirs ne sont pas déduits."
    )


def _puce_balance_agee(facts: dict, bullets: list[str], bal: dict | None) -> None:
    """« Qu'est-ce qui reste dû, et depuis quand ? » — la créance par tranche.

    Les cinq tranches sont énumérées parce qu'elles PARTITIONNENT l'encours ; le
    contentieux arrive ensuite par un « dont », parce que son seuil est réglable
    et qu'il recoupe les tranches au lieu de s'y ajouter (cf. `analyses`).
    """
    if not bal or not bal.get("mesurable"):
        return
    t, cont = bal["tranches"], bal["contentieux"]
    facts.update({
        "balance_total_xof": bal["montant_total_xof"],
        "balance_nb_factures": bal["nb_total"],
        "balance_a_echoir_xof": t["a_echoir"]["montant_xof"],
        "balance_0_30_xof": t["j0_30"]["montant_xof"],
        "balance_30_60_xof": t["j30_60"]["montant_xof"],
        "balance_60_90_xof": t["j60_90"]["montant_xof"],
        "balance_90_plus_xof": t["j90_plus"]["montant_xof"],
        "balance_contentieux_xof": cont["montant_xof"],
        "balance_contentieux_pct": cont["part_pct"],
        "balance_contentieux_jours": cont["seuil_jours"],
        "balance_intragroupe_xof": bal["intragroupe"]["montant_xof"],
    })
    texte = (
        f"Balance âgée : {_m(bal['montant_total_xof'])} M FCFA dus sur "
        f"{bal['nb_total']} factures — {_m(t['a_echoir']['montant_xof'])} M à échoir, "
        f"{_m(t['j0_30']['montant_xof'])} M à 0-30 j, {_m(t['j30_60']['montant_xof'])} M à "
        f"30-60 j, {_m(t['j60_90']['montant_xof'])} M à 60-90 j et "
        f"{_m(t['j90_plus']['montant_xof'])} M au-delà de 90 j"
    )
    # Le « dont » n'a de sens que si le seuil de contentieux tombe AILLEURS que
    # sur la borne des 90 jours déjà énumérée : à 90, il répéterait mot pour mot
    # la tranche qui précède. Seule la part, elle, reste utile dans les deux cas.
    if cont["part_pct"] is not None:
        if cont["seuil_jours"] == 90:
            texte += f", soit {cont['part_pct']:.0f}% du total"
        else:
            texte += (
                f", dont {_m(cont['montant_xof'])} M échus depuis plus de "
                f"{cont['seuil_jours']:g} j ({cont['part_pct']:.0f}% du total)"
            )
    # `_m` arrondit au million : une créance intragroupe de 400 000 F sortirait
    # « 0 M d'intragroupe sont inclus », une phrase qui n'apprend rien et occupe
    # la ligne la plus dense du briefing DAF.
    if _m(bal["intragroupe"]["montant_xof"]):
        texte += (
            f" ; {_m(bal['intragroupe']['montant_xof'])} M d'intragroupe sont inclus et "
            "restent à isoler de toute lecture du risque"
        )
    bullets.append(texte + f". Réserve : {bal['reserve']}.")


def _puce_relances(facts: dict, bullets: list[str], rel: dict | None) -> None:
    """« Qui dois-je relancer aujourd'hui ? » — par client, pas par facture.

    Groupé par débiteur parce qu'on ne passe pas cinq appels au même client pour
    cinq factures. L'intragroupe est signalé sur la ligne où il apparaît : une
    relance interne ne se traite pas comme une relance client.
    """
    if not rel or not rel.get("mesurable"):
        return
    facts.update({
        "relances_nb_clients": rel["nb_clients"],
        "relances_montant_xof": rel["montant_xof"],
        "relances_retard_min_jours": rel["retard_min_jours"],
        "relances_top": rel["top"],
    })
    cites = "; ".join(
        f"{ligne['client']} ({_m(ligne['montant_xof'])} M FCFA sur {ligne['nb_factures']} "
        f"factures, jusqu'à {ligne['retard_max_jours']} j de retard"
        + (", intragroupe" if ligne["intragroupe"] else "") + ")"
        for ligne in rel["top"][:3]
    )
    bullets.append(
        f"Relances du jour : {rel['nb_clients']} clients portent "
        f"{_m(rel['montant_xof'])} M FCFA échus depuis plus de "
        f"{rel['retard_min_jours']:g} j — les trois premiers : {cites}."
    )


def _puce_dso(facts: dict, bullets: list[str], dso: dict | None) -> None:
    """DSO glissant contre la période précédente.

    `robuste` gouverne la formulation : un DSO calculé sur une poignée de
    factures n'est pas un DSO, et l'annoncer en amélioration de quarante jours
    serait le type même du chiffre crédible et faux. Le ratio encours/CA n'est
    jamais affiché sur l'exercice en cours (257 j d'artefact, cf. audit §3).
    """
    if not dso or not dso.get("mesurable"):
        if dso:
            bullets.append(f"DSO non mesurable : {dso.get('raison', 'source indisponible')}.")
        return
    facts.update({
        "dso_jours": dso["dso_jours"],
        "dso_precedent_jours": dso["dso_precedent_jours"],
        "dso_ecart_jours": dso["ecart_jours"],
        "dso_nb_factures": dso["nb_factures"],
        "dso_robuste": dso["robuste"],
    })
    texte = (
        f"DSO sur {dso['fenetre_mois']} mois glissants : {dso['dso_jours']:.0f} j, "
        f"mesuré sur {dso['nb_factures']} règlements"
    )
    if dso["ecart_jours"] is not None:
        sens = "dégradation" if dso["ecart_jours"] > 0 else "amélioration"
        texte += (
            f" — {sens} de {abs(dso['ecart_jours']):.0f} j face aux "
            f"{dso['dso_precedent_jours']:.0f} j de la période précédente"
        )
    if not dso["robuste"]:
        texte += (
            " ; l'échantillon est trop mince pour conclure, le chiffre est indicatif"
        )
    bullets.append(texte + ".")


_DF_SOURCES: dict[str, tuple[str, ...]] = {
    "exposure": ("exposition_impayes", "retard_90j", "top_debiteur"),
    "margins": ("marge_definitive", "encaissable_vs_du", "ecart_marge_promise"),
    "forecast": ("forecast_trimestre",),
    "fournisseurs": ("echeancier_fournisseurs",),
    "balance": ("balance_agee",),
    "relances": ("relances_du_jour",),
    "dso": ("dso_glissant",),
    "visibilite": ("attente_facturation",),
}

_DF_DELTAS = ["impayes_echus", "impayes_echus_90j", "ca_facture_ytd",
              "ca_facture_mois", "encaissements_ytd", "encaissements_mois",
              "ca_commande_ytd"]


async def build_dir_financier_facts(crm, composition: Composition | None = None) -> dict:
    role = "dir_financier"
    c = composition or Composition()

    src = await _resoudre(
        {
            "exposure": (lambda: crm.get_unpaid_exposure(), None),
            "margins": (lambda: crm.get_margin_stats(), None),
            "forecast": (lambda: crm.get_quarterly_forecast(), None),
            "fournisseurs": (lambda: crm.get_supplier_intelligence(limit=10), None),
            "balance": (
                lambda: analyses.balance_agee(
                    contentieux_jours=int(c.seuil("contentieux_jours"))), None),
            "relances": (
                lambda: analyses.relances_du_jour(
                    retard_min_jours=int(c.seuil("retard_relance_jours"))), None),
            "dso": (lambda: analyses.dso_glissant(), None),
            "visibilite": (lambda: analyses.visibilite_carnet(), None),
        },
        _DF_SOURCES,
        c,
    )
    deltas = await _deltas(_DF_DELTAS)
    exposure, margins, forecast = src["exposure"], src["margins"], src["forecast"]

    facts: dict = {}
    puces = Puces(role)

    if c.actif("exposition_impayes") and exposure:
        facts.update({
            "exposition_totale_xof": exposure["exposition_totale_xof"],
            "nb_factures_impayees": exposure["nb_factures_impayees"],
        })
        puces.pour("exposition_impayes").append(
            f"Exposition totale aux impayés : {_m(exposure['exposition_totale_xof'])} M FCFA "
            f"sur {exposure['nb_factures_impayees']} factures"
            + _var(deltas, "impayes_echus", "semaine") + "."
        )

    if c.actif("retard_90j") and exposure:
        facts["retard_90j_montant_xof"] = exposure["retard_90j_montant_xof"]
        puces.pour("retard_90j").append(
            f"Retard de plus de 90 jours : {_m(exposure['retard_90j_montant_xof'])} M FCFA"
            + _var(deltas, "impayes_echus_90j", "mois") + "."
        )

    if c.actif("marge_definitive") and margins:
        taux_def = _taux_marge(margins, "definitif")
        facts["marge_definitive_moyenne_pct"] = taux_def
        puces.pour("marge_definitive").append(
            f"Marge définitive : {taux_def:.1f}% du CA définitif constaté."
            if taux_def is not None
            else "Marge définitive non mesurable : aucun CA définitif constaté."
        )

    if c.actif("encaissable_vs_du") and margins:
        facts.update({
            "reste_a_encaisser_xof": margins["reste_a_encaisser"],
            "fournisseurs_restant_xof": margins["fournisseurs_restant"],
        })
        puces.pour("encaissable_vs_du").append(
            f"Reste à encaisser : {_m(margins['reste_a_encaisser'])} M FCFA. "
            f"Fournisseurs restant à payer : {_m(margins['fournisseurs_restant'])} M FCFA."
        )

    if c.actif("top_debiteur") and exposure:
        top_debiteur = exposure["top_10_debiteurs"][0] if exposure["top_10_debiteurs"] else None
        facts["top_debiteur"] = top_debiteur
        if top_debiteur:
            puces.pour("top_debiteur").append(
                f"Plus gros débiteur : {top_debiteur['client']} "
                f"({_m(top_debiteur['montant_total_xof'])} M FCFA, {top_debiteur['retard_max_jours']} jours de retard)."
            )

    if c.actif("forecast_trimestre") and forecast:
        proj = forecast.get("projection_fin_trimestre", {})
        facts.update({
            "forecast_trimestre": forecast.get("trimestre"),
            "forecast_realiste_xof": proj.get("realiste_xof"),
        })
        puces.pour("forecast_trimestre").append(
            f"Prévision {forecast.get('trimestre')} : {_m(proj.get('realiste_xof'))} M FCFA (scénario réaliste)."
        )

    # Répare ROLE_FOCUS["dir_financier"] : « la marge réelle par rapport à la
    # marge annoncée en début de dossier ».
    #
    # Les taux sont recalculés sur les TOTAUX, jamais repris de
    # `perc_marge_*_moyen` : ces deux champs sont des AVG() non pondérés sur des
    # pourcentages par dossier, et 91 dossiers à dénominateur minuscule (jusqu'à
    # -85 034 %) tirent la moyenne provisoire à -756 %. Un briefing annonçant
    # « 791 points de mieux que promis » serait faux et indéfendable.
    if c.actif("ecart_marge_promise") and margins:
        ca_prov = margins.get("ca_provisoire_total") or 0
        ca_def = margins.get("ca_definitif_total") or 0
        if ca_prov and ca_def:
            prevue = margins["marge_provisoire_total"] / ca_prov * 100
            reelle = margins["marge_definitive_total"] / ca_def * 100
            ecart = reelle - prevue
            facts.update({
                "marge_promise_pct": round(prevue, 1),
                "marge_constatee_pct": round(reelle, 1),
                "marge_ecart_points": round(ecart, 1),
            })
            puces.pour("ecart_marge_promise").append(
                f"Marge annoncée à l'ouverture {prevue:.1f}% du CA contre {reelle:.1f}% constatés à l'arrêté, "
                f"soit {abs(ecart):.1f} point(s) {'de mieux' if ecart >= 0 else 'de moins'} que promis."
            )

    if c.actif("echeancier_fournisseurs"):
        _echeancier_fournisseurs(facts, puces.pour("echeancier_fournisseurs"), src["fournisseurs"])

    if c.actif("balance_agee"):
        _puce_balance_agee(facts, puces.pour("balance_agee"), src["balance"])

    if c.actif("relances_du_jour"):
        _puce_relances(facts, puces.pour("relances_du_jour"), src["relances"])

    if c.actif("dso_glissant"):
        _puce_dso(facts, puces.pour("dso_glissant"), src["dso"])

    if c.actif("ca_facture_periode"):
        _puce_ca_facture(facts, puces, deltas)

    if c.actif("attente_facturation"):
        _puce_attente_facturation(facts, puces, "attente_facturation", src["visibilite"])

    if c.actif("questions_sans_reponse"):
        _puce_couverture(facts, puces, role)

    return {"facts": facts, "bullets": puces.liste(), "blocs": puces.par_bloc()}


def _echeancier_fournisseurs(facts: dict, bullets: list[str], fournisseurs: list[dict] | None) -> None:
    """Décaissements fournisseurs à 30/60/90 jours — la contrepartie de
    l'encaissement, que le briefing DAF ne portait pas."""
    lignes = fournisseurs or []
    if not lignes:
        return
    c30 = sum(f.get("cash_30j_xof") or 0 for f in lignes)
    c60 = sum(f.get("cash_60j_xof") or 0 for f in lignes)
    c90 = sum(f.get("cash_90j_xof") or 0 for f in lignes)
    if not (c30 or c60 or c90):
        return
    facts.update({
        "echeancier_30j_xof": c30, "echeancier_60j_xof": c60, "echeancier_90j_xof": c90,
        "echeancier_nb_fournisseurs": len(lignes),
    })
    bullets.append(
        f"Échéancier fournisseurs sur les {len(lignes)} premiers : {_m(c30)} M FCFA à 30 j, "
        f"{_m(c60)} M FCFA à 60 j, {_m(c90)} M FCFA à 90 j."
    )


_DO_SOURCES: dict[str, tuple[str, ...]] = {
    "margins": ("volume_marges", "backlog"),
    "top_dossiers": ("top_dossier_marge", "dossiers_marge_faible"),
    "par_produit": ("charge_par_practice",),
    "fournisseurs": ("fiabilite_fournisseurs", "risque_rupture_fournisseur"),
    "commandes": ("commandes_recentes",),
    "derive": ("derive_budgetaire",),
    "sous_traitance": ("sous_traitance_dossiers",),
}

_DO_DELTAS = ["backlog", "reste_a_encaisser", "achats_engages_ytd"]


async def build_dir_operations_facts(crm, composition: Composition | None = None) -> dict:
    role = "dir_operations"
    c = composition or Composition()
    y = datetime.now().year

    src = await _resoudre(
        {
            "margins": (lambda: crm.get_margin_stats(), None),
            "top_dossiers": (lambda: crm.get_top_margin_dossiers(limit=10, metric="marge_provisoire"), []),
            "par_produit": (lambda: crm.get_revenue_by_product(year=y, limit=10), []),
            "fournisseurs": (lambda: crm.get_supplier_intelligence(limit=10), None),
            "commandes": (lambda: crm.get_recent_orders(limit=5), []),
            "derive": (lambda: analyses.derive_budgetaire(), None),
            "sous_traitance": (lambda: analyses.sous_traitance_par_dossier(), None),
        },
        _DO_SOURCES,
        c,
    )
    deltas = await _deltas(_DO_DELTAS)
    margins, top_dossiers = src["margins"], src["top_dossiers"]

    facts: dict = {}
    puces = Puces(role)

    if c.actif("volume_marges") and margins:
        taux_prov, taux_def = _taux_marge(margins, "provisoire"), _taux_marge(margins, "definitif")
        facts.update({
            "nb_dossiers": margins["nb_dossiers"],
            "marge_provisoire_moyenne_pct": taux_prov,
            "marge_definitive_moyenne_pct": taux_def,
        })
        puces.pour("volume_marges").append(
            f"{margins['nb_dossiers']} dossiers en base — marge provisoire "
            + (f"{taux_prov:.1f}%" if taux_prov is not None else "non mesurable")
            + " du CA provisoire, marge définitive "
            + (f"{taux_def:.1f}%" if taux_def is not None else "non mesurable")
            + " du CA définitif."
        )

    if c.actif("backlog") and margins:
        facts.update({
            "backlog_total_xof": margins["backlog_total"],
            "fournisseurs_restant_xof": margins["fournisseurs_restant"],
        })
        puces.pour("backlog").append(
            f"Backlog non facturé : {_m(margins['backlog_total'])} M FCFA"
            + _var(deltas, "backlog", "semaine")
            + f". Fournisseurs restant à payer : {_m(margins['fournisseurs_restant'])} M FCFA."
        )

    if c.actif("top_dossier_marge") and top_dossiers:
        top_dossier = top_dossiers[0]
        facts["top_dossier"] = top_dossier
        puces.pour("top_dossier_marge").append(
            f"Dossier le plus margé : {top_dossier['ref']} ({top_dossier['client']}), "
            f"{_m(top_dossier['marge_provisoire'])} M FCFA de marge provisoire ({top_dossier['perc_marge_prov']}%)."
        )

    if c.actif("dossiers_marge_faible") and top_dossiers:
        # L'inverse du palmarès : la source est triée par marge décroissante, le
        # dernier rang est donc le plus dégradé des dossiers suivis.
        pire = min(top_dossiers, key=lambda d: d.get("perc_marge_prov") or 0)
        facts["dossier_marge_faible"] = pire
        puces.pour("dossiers_marge_faible").append(
            f"Dossier à la marge la plus basse : {pire['ref']} ({pire['client']}), "
            f"{pire['perc_marge_prov']}% de marge provisoire pour {_m(pire['marge_provisoire'])} M FCFA."
        )

    # Répare ROLE_FOCUS["dir_operations"] : « la visibilité de charge par practice ».
    if c.actif("charge_par_practice"):
        _mix_offre(facts, puces.pour("charge_par_practice"), src["par_produit"], y, cle="charge")

    if c.actif("fiabilite_fournisseurs"):
        _fiabilite_fournisseurs(facts, puces.pour("fiabilite_fournisseurs"), src["fournisseurs"])

    if c.actif("risque_rupture_fournisseur"):
        _concentration_fournisseur(facts, puces.pour("risque_rupture_fournisseur"), src["fournisseurs"])

    if c.actif("derive_budgetaire"):
        _puce_derive(facts, puces.pour("derive_budgetaire"), src["derive"])

    if c.actif("sous_traitance_dossiers"):
        _puce_sous_traitance(facts, puces.pour("sous_traitance_dossiers"), src["sous_traitance"])

    if c.actif("questions_sans_reponse"):
        _puce_couverture(facts, puces, role)

    if c.actif("commandes_recentes") and src["commandes"]:
        recentes = src["commandes"]
        montant = sum(o.get("montant_xof") or 0 for o in recentes)
        tete = recentes[0]
        facts.update({"commandes_recentes_nb": len(recentes), "commandes_recentes_montant_xof": montant})
        puces.pour("commandes_recentes").append(
            f"{len(recentes)} dernières commandes entrées pour {_m(montant)} M FCFA — la plus récente : "
            f"{tete.get('client')} ({_m(tete.get('montant_xof'))} M FCFA)."
        )

    return {"facts": facts, "bullets": puces.liste(), "blocs": puces.par_bloc()}


def _puce_derive(facts: dict, bullets: list[str], der: dict | None) -> None:
    """Dossiers dont la dépense constatée dévore la dépense prévue.

    C'est la seule lecture de « mission qui dérive » que les données autorisent.
    La lecture canonique — quantité livrée contre quantité vendue sur la ligne de
    commande — est impossible : `qty_delivered` et `qty_invoiced` valent 0 sur
    les 19 510 lignes du miroir. La réserve le dit dans la puce, faute de quoi le
    lecteur croirait à un suivi d'avancement qui n'existe pas.
    """
    if not der or not der.get("mesurable"):
        return
    facts.update({
        "derive_nb_dossiers": der["nb"],
        "derive_seuil_pct": der["seuil_consommation_pct"],
        "derive_depense_engagee_xof": der["depense_engagee_xof"],
        "derive_top": der["top"],
    })
    tete = der["top"][0]
    ecart = tete["marge_constatee_pct"] - tete["marge_prevue_pct"]
    bullets.append(
        f"{der['nb']} dossiers ont consommé au moins {der['seuil_consommation_pct']:g}% de leur "
        f"budget de dépense, pour {_m(der['depense_engagee_xof'])} M FCFA engagés — le plus "
        f"exposé : {tete['ref']} ({tete['client']}) à {tete['consommation_pct']:.0f}% de "
        f"consommation, marge passée de {tete['marge_prevue_pct']:.1f}% annoncés à "
        f"{tete['marge_constatee_pct']:.1f}% constatés ({ecart:+.1f} point(s)). "
        f"Réserve : {der['reserve']}."
    )


def _puce_sous_traitance(facts: dict, bullets: list[str], st: dict | None) -> None:
    """Engagement fournisseur rapporté au dossier servi.

    `dossier_id` tient lieu de compte analytique, faute d'accès à
    `account.analytic.line` : la couverture est publiée avec le chiffre, parce
    qu'un engagement « total » calculé sur 71 % des achats n'est pas un total.
    """
    if not st or not st.get("mesurable"):
        return
    facts.update({
        "sous_traitance_nb_dossiers": st["nb_dossiers"],
        "sous_traitance_engagement_xof": st["engagement_xof"],
        "sous_traitance_couverture_pct": st["couverture_pct"],
        "sous_traitance_orphelins": st["nb_achats_orphelins"],
        "sous_traitance_depassements": st["nb_engagement_depasse_ca"],
        "sous_traitance_top": st["top"],
    })
    tete = st["top"][0]
    texte = (
        f"Sous-traitance : {_m(st['engagement_xof'])} M FCFA engagés sur "
        f"{st['nb_dossiers']} dossiers — en tête {tete['ref']} ({tete['client']}, "
        f"{_m(tete['engagement_xof'])} M FCFA"
        + (f", soit {tete['poids_sur_ca_pct']:.0f}% du CA {tete['base_ca']} du dossier"
           if tete["poids_sur_ca_pct"] is not None else "")
        + ")"
    )
    if st["nb_engagement_depasse_ca"]:
        texte += (
            f". {st['nb_engagement_depasse_ca']} dossier(s) ont engagé plus d'achats que "
            f"le CA qu'ils rapportent"
        )
    bullets.append(
        texte + f". Le rattachement couvre {st['couverture_pct']:.0f}% des commandes "
        f"d'achat, {st['nb_achats_orphelins']} restant imputées à aucun dossier."
    )


def _fiabilite_fournisseurs(facts: dict, bullets: list[str], fournisseurs: list[dict] | None) -> None:
    """Retard moyen de livraison/paiement par fournisseur. Un retard négatif est
    une avance : le libellé le dit, sinon « -17 jours de retard » se lit mal."""
    lignes = [f for f in (fournisseurs or []) if f.get("retard_moyen_jours") is not None]
    if not lignes:
        return
    pire = max(lignes, key=lambda f: f["retard_moyen_jours"])
    facts.update({
        "fiabilite_nb_fournisseurs": len(lignes),
        "fiabilite_pire_fournisseur": pire["name"],
        "fiabilite_pire_retard_jours": pire["retard_moyen_jours"],
    })
    retard = pire["retard_moyen_jours"]
    bullets.append(
        f"Fiabilité fournisseurs sur {len(lignes)} suivis : {pire['name']} est le moins ponctuel avec "
        + (f"{retard:.0f} j de retard moyen." if retard > 0 else f"{abs(retard):.0f} j d'avance moyenne.")
    )


def _concentration_fournisseur(facts: dict, bullets: list[str], fournisseurs: list[dict] | None) -> None:
    """Fournisseurs sur lesquels l'engagement se concentre, et dossiers qui n'ont
    qu'une seule source d'approvisionnement."""
    lignes = [f for f in (fournisseurs or []) if f.get("taux_dependance_pct")]
    if not lignes:
        return
    tete = max(lignes, key=lambda f: f["taux_dependance_pct"])
    a_risque = sum(f.get("dossiers_a_risque_fournisseur_unique") or 0 for f in lignes)
    facts.update({
        "concentration_fournisseur_top": tete["name"],
        "concentration_fournisseur_top_pct": tete["taux_dependance_pct"],
        "concentration_dossiers_source_unique": a_risque,
    })
    bullets.append(
        f"Concentration fournisseur : {tete['name']} porte {tete['taux_dependance_pct']:.0f}% des achats"
        + (f", et {a_risque} dossier(s) dépendent d'une source unique." if a_risque else ".")
    )


_AM_SOURCES: dict[str, tuple[str, ...]] = {
    "opportunites": ("pipeline_perso", "echeances_opportunites"),
    "win_rate": ("taux_victoire_nb",),
    "hot_leads": ("top_lead",),
    "rupture": ("comptes_silencieux",),
    "exposure": ("impayes_portefeuille",),
    "lost": ("deals_perdus",),
    "mouvements": ("mouvements_recents",),
    "hygiene": ("hygiene_pipe",),
}


async def build_commercial_facts(crm, composition: Composition | None = None) -> dict:
    role = "commercial"
    """ATTENTION — périmètre : aucune de ces sources n'est filtrée par commercial.
    `get_account_rhythm_breaks` et `get_unpaid_exposure` renvoient l'entreprise
    entière. Les puces nomment donc leur périmètre et ne disent jamais « vos
    comptes » (cf. la note de uc_briefing.preferences)."""
    c = composition or Composition()

    src = await _resoudre(
        {
            "opportunites": (lambda: crm.list_opportunities(limit=500), []),
            "win_rate": (lambda: crm.get_win_rate(), None),
            "hot_leads": (lambda: crm.get_hot_leads(limit=5), []),
            "rupture": (lambda: crm.get_account_rhythm_breaks(), _RUPTURE_VIDE),
            "exposure": (lambda: crm.get_unpaid_exposure(), None),
            "lost": (lambda: crm.get_lost_deals(limit=5), None),
            "mouvements": (
                lambda: evenements.mouvements(datetime.now().date() - timedelta(days=7)), None),
            "hygiene": (
                lambda: evenements.hygiene_pipe(seuil_jours=int(c.seuil("dormance_jours"))), None),
        },
        _AM_SOURCES,
        c,
    )
    deltas_am = await _deltas(["nb_opportunites_ouvertes"])
    opportunities, win_rate, hot_leads = src["opportunites"], src["win_rate"], src["hot_leads"]
    scen = build_pipeline_forecast(opportunities)["scenarios"]

    facts: dict = {}
    puces = Puces(role)

    if c.actif("pipeline_perso") and opportunities:
        # Même troncature que côté DC : `list_opportunities` plafonne à 500 et
        # `scen["nb_opportunites"]` compte ce qui a été ramené. L'indicateur
        # historisé porte le compte réel ; le repli reste le compte ramené,
        # qui vaut mieux que rien tant que l'historisation n'a pas tourné.
        nb_ouvertes = (deltas_am.get("nb_opportunites_ouvertes") or {}).get("valeur")
        nb = int(nb_ouvertes) if nb_ouvertes is not None else scen["nb_opportunites"]
        facts.update({
            "nb_opportunites_ouvertes": nb,
            "forecast_realiste_xof": scen["realiste_xof"],
        })
        puces.pour("pipeline_perso").append(
            f"Pipeline ouvert : {nb} opportunités, "
            f"{_m(scen['realiste_xof'])} M FCFA pondérés (scénario réaliste)."
        )

    if c.actif("taux_victoire_nb") and win_rate:
        facts["taux_victoire_nb_pct"] = win_rate["taux_nb_pct"]
        puces.pour("taux_victoire_nb").append(f"Taux de victoire en nombre : {win_rate['taux_nb_pct']}%.")

    if c.actif("top_lead"):
        facts["nb_hot_leads"] = len(hot_leads)
        if hot_leads:
            top_lead = hot_leads[0]
            facts["top_lead"] = top_lead
            puces.pour("top_lead").append(
                f"Lead le plus chaud du pipeline : {top_lead['opportunite']} ({top_lead['client']}), "
                f"{_m(top_lead['score_pondere_xof'])} M FCFA pondérés, étape {top_lead['stade']}."
            )
        else:
            puces.pour("top_lead").append("Aucun lead chaud identifié actuellement.")

    if c.actif("echeances_opportunites"):
        _echeances(facts, puces.pour("echeances_opportunites"), opportunities, jours=int(c.seuil("echeance_fenetre_jours")))

    if c.actif("comptes_silencieux"):
        comptes = src["rupture"].get("comptes", [])
        facts["silencieux_nb_comptes"] = src["rupture"].get("nb_comptes_rompus", 0)
        if comptes:
            tete = comptes[0]
            facts["silencieux_top"] = tete
            puces.pour("comptes_silencieux").append(
                f"{src['rupture']['nb_comptes_rompus']} comptes ont décroché sur l'ensemble du portefeuille "
                f"S2I — {tete['client']} en tête, silencieux depuis {tete['jours_silence']} j "
                f"({_m(tete['ca_annuel_moyen_xof'])} M FCFA/an historiques)."
            )

    if c.actif("impayes_portefeuille") and src["exposure"]:
        exposure = src["exposure"]
        top_debiteur = exposure["top_10_debiteurs"][0] if exposure["top_10_debiteurs"] else None
        facts["impayes_exposition_xof"] = exposure["exposition_totale_xof"]
        if top_debiteur:
            facts["impayes_top_debiteur"] = top_debiteur
            puces.pour("impayes_portefeuille").append(
                f"Impayés en cours sur le portefeuille S2I : {_m(exposure['exposition_totale_xof'])} M FCFA, "
                f"{top_debiteur['client']} en tête à {_m(top_debiteur['montant_total_xof'])} M FCFA "
                f"({top_debiteur['retard_max_jours']} j de retard)."
            )

    if c.actif("deals_perdus") and src["lost"]:
        lost = src["lost"]
        top_perdant = lost["by_client"][0] if lost["by_client"] else None
        facts["nb_deals_perdus"] = lost["nb_total"]
        if top_perdant:
            facts["top_client_perdant"] = top_perdant
            puces.pour("deals_perdus").append(
                f"{lost['nb_total']} affaires perdues récemment — {top_perdant['client']} en concentre "
                f"{top_perdant['nb']} pour {_m(top_perdant['montant_xof'])} M FCFA."
            )

    if c.actif("mouvements_recents"):
        _puce_mouvements(facts, puces.pour("mouvements_recents"), src["mouvements"])

    if c.actif("hygiene_pipe"):
        _puce_hygiene_pipe(facts, puces.pour("hygiene_pipe"), src["hygiene"])

    if c.actif("questions_sans_reponse"):
        _puce_couverture(facts, puces, role)

    return {"facts": facts, "bullets": puces.liste(), "blocs": puces.par_bloc()}
