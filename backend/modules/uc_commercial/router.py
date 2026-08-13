"""Endpoints du pilotage commercial — un endpoint par ÉCRAN, pas par calcul.

Le découpage suit les onglets du cockpit DC et non les fonctions du module : un
onglet qui affiche trois blocs paie un appel, pas trois. C'est le même arbitrage
que `/dashboard/account-activity`, qui sert la segmentation, les décrochages et
les totaux d'un coup.

Les agrégations sont déportées par `_hors_boucle` : ce sont des boucles Python
pures sur la totalité du pipe (9 475 opportunités, 3 154 commandes), qui gèleraient
le worker si elles étaient appelées en ligne dans un `async def`. Même raison et
mêmes limites que le déport de `api/v1/dashboard.py` — il empêche le gel, il ne
rend pas la concurrence saine.

Gating : les vues existantes de `config/permissions.py` sont réutilisées telles
quelles (`forecast`, `performance`, `clients`, `dashboard`). Aucune vue nouvelle
n'est créée : la matrice est éditable en base par la page Paramètres, et y ajouter
une ligne obligerait chaque installation à la re-régler.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from api.v1.dependencies import require_views
from modules.uc_commercial import alertes as mod_alertes
from modules.uc_commercial import comptes as mod_comptes
from modules.uc_commercial import cycle_vie as mod_cycle
from modules.uc_commercial import marche as mod_marche
from modules.uc_commercial import objectifs as mod_objectifs
from modules.uc_commercial import prospection as mod_prospection
from modules.uc_commercial import qualite_pipe as mod_qualite
from modules.uc_commercial import queries as q
from modules.uc_commercial import referentiel as mod_referentiel
from modules.uc_commercial import statique
from modules.uc_commercial import visites as mod_visites
from modules.uc_dormance.aggregation import build_suivi_dormance

router = APIRouter(prefix="/commercial", tags=["Pilotage commercial"])


def _crm(request: Request):
    return request.app.state.container.crm_repo


async def _hors_boucle(fn, *args, **kwargs):
    return await asyncio.to_thread(lambda: fn(*args, **kwargs))


def _annee(annee: int | None) -> int:
    return annee or datetime.now().year


async def _referentiel_resolu() -> tuple[dict, dict]:
    """Référentiel des commerciaux + index de résolution, semé en base au passage.

    La persistance est faite ici et non dans un job : le référentiel n'a de sens
    qu'au moment où on l'utilise, et l'écriture est idempotente (une ligne d'alias
    déjà confirmée par un humain n'est jamais retouchée).
    """
    noms = await q.fetch_noms_commerciaux()
    ref = await _hors_boucle(mod_referentiel.construire_referentiel, noms)
    await q.persist_referentiel(
        [{"salesperson_id": p["salesperson_id"], "display_name": p["display_name"]} for p in ref["personnes"]]
        + [
            {
                "salesperson_id": p["salesperson_id"],
                "display_name": p["display_name"],
                "is_active": False,
                "note": p["motif"],
            }
            for p in ref["porteurs_non_nominatifs"]
        ],
        ref["alias"],
    )
    return ref, mod_referentiel.index_resolution(ref)


# ── Onglet « Objectifs et Gap » ──────────────────────────────────────────────

@router.get("/objectifs", dependencies=[Depends(require_views("performance"))])
async def objectifs(
    request: Request,
    annee: int | None = Query(default=None),
    periode: str = Query(default="trimestre", pattern="^(mois|trimestre|annee)$"),
):
    """Gap vendu / objectif à la cadence demandée.

    Le réalisé est mesuré ; l'objectif vient de `commercial_objectives` s'il y est
    saisi, d'un gabarit sinon — `source` vaut alors "mixte" et le front l'affiche.
    """
    an = _annee(annee)
    objectifs_bdd, ca, ca_n1, annees = await asyncio.gather(
        q.fetch_objectifs(an),
        q.fetch_ca_mensuel_par_commercial(an),
        q.fetch_ca_mensuel_par_commercial(an - 1),
        q.fetch_annees_disponibles(),
    )
    _, index = await _referentiel_resolu()
    resultat = await _hors_boucle(
        mod_objectifs.build_objectifs_gap, objectifs_bdd, ca, ca_n1, index, an, periode,
    )
    resultat["annees_disponibles"] = annees
    return resultat


# ── Onglet « Comptes et animation » ──────────────────────────────────────────

@router.get("/comptes", dependencies=[Depends(require_views("clients"))])
async def comptes(request: Request, limit: int = Query(default=15, ge=5, le=50)):
    """Top comptes (quantité ET montant), pics d'activité, acquisition.

    Les trois blocs partagent la même lecture du portefeuille : les séparer en
    trois endpoints ferait payer trois fois `get_account_activity`.
    """
    crm = _crm(request)
    portefeuille, opportunites, series = await asyncio.gather(
        crm.get_account_activity(),
        q.fetch_opportunites(),
        q.fetch_series_mensuelles_par_compte(),
    )
    top, pics, acquisition = await asyncio.gather(
        _hors_boucle(mod_comptes.build_top_comptes, portefeuille, opportunites, None, limit),
        _hors_boucle(mod_comptes.build_pics_activite, series),
        _hors_boucle(mod_comptes.build_acquisition, portefeuille),
    )
    return {"top_comptes": top, "pics": pics, "acquisition": acquisition}


# ── Onglet « Pipeline » (complément : à closer / à compléter) ─────────────────

@router.get("/pipeline/qualite", dependencies=[Depends(require_views("forecast"))])
async def pipeline_qualite(request: Request, limit: int = Query(default=12, ge=5, le=50)):
    """Opportunités à closer, opportunités à compléter, et la règle appliquée."""
    opportunites = await q.fetch_opportunites()
    return await _hors_boucle(mod_qualite.build_qualite_pipe, opportunites, None, limit)


# ── Onglet « Cycle de vie » ──────────────────────────────────────────────────

@router.get("/cycle-vie", dependencies=[Depends(require_views("forecast"))])
async def cycle_vie(
    request: Request,
    seuil_xof: int | None = Query(default=None, ge=0),
    limit: int = Query(default=15, ge=5, le=50),
):
    """Traçage des affaires au-dessus du seuil, et profondeur réelle de l'historique."""
    opportunites, dates = await asyncio.gather(q.fetch_opportunites(), q.fetch_dates_snapshots())
    # Les deux instantanés comparés sont les EXTRÊMES disponibles : c'est la plus
    # longue fenêtre observable, et donc la mesure la plus favorable au mouvement.
    # Si rien ne bouge sur cette fenêtre, rien ne bouge du tout.
    mouvements = await q.fetch_mouvements_pipe(dates[0], dates[-1]) if len(dates) >= 2 else None
    return await _hors_boucle(
        mod_cycle.build_cycle_vie, opportunites, mouvements, dates, seuil_xof, None, limit,
    )


# ── Onglet « Équipe » ────────────────────────────────────────────────────────

@router.get("/equipe", dependencies=[Depends(require_views("performance"))])
async def equipe(
    request: Request,
    annee: int | None = Query(default=None),
    periode: str = Query(default="mois", pattern="^(mois|trimestre|annee)$"),
    limit: int = Query(default=20, ge=5, le=50),
):
    """Indice d'efficacité (mesuré), indice de prospection (gabarit), référentiel."""
    an = _annee(annee)
    opportunites, ca, sans_commercial = await asyncio.gather(
        q.fetch_opportunites(),
        q.fetch_ca_mensuel_par_commercial(an),
        q.fetch_lignes_sans_commercial(),
    )
    ref, index = await _referentiel_resolu()
    _, alias_bdd = await q.fetch_referentiel_commerciaux()
    ref_avec_etat = {**ref, "alias": alias_bdd or ref["alias"]}
    efficacite, prospection = await asyncio.gather(
        _hors_boucle(
            mod_prospection.build_efficacite,
            opportunites, ca, index, ref_avec_etat, sans_commercial, an, limit,
        ),
        _hors_boucle(mod_prospection.build_indice_prospection, an, periode),
    )
    return {
        "efficacite": efficacite,
        "prospection": prospection,
        "referentiel": {
            "personnes": ref["personnes"][:limit],
            "porteurs_non_nominatifs": ref["porteurs_non_nominatifs"],
            "doublons_orthographe": ref["doublons_orthographe"],
            "totaux": ref["totaux"],
        },
    }


# ── Onglet « Secteurs et marché » ────────────────────────────────────────────

@router.get("/marche", dependencies=[Depends(require_views("dashboard"))])
async def marche(request: Request, limit: int = Query(default=12, ge=5, le=40)):
    """Axes stratégiques (mesurés), secteurs et part de marché (gabarit), veille (mesurée)."""
    await q.upsert_axes_mappings(mod_marche.AXES_DEFAUT, par="uc_commercial:defaut")
    opportunites, mappings, couverture, veille = await asyncio.gather(
        q.fetch_opportunites(),
        q.fetch_axes_mappings(),
        q.fetch_couverture_secteur(),
        q.fetch_veille(),
    )
    axes, secteurs, signaux = await asyncio.gather(
        _hors_boucle(mod_marche.build_axes_strategiques, opportunites, mappings),
        _hors_boucle(mod_marche.build_secteurs, couverture),
        _hors_boucle(mod_marche.build_veille, veille, limit),
    )
    return {"axes": axes, "secteurs": secteurs, "veille": signaux}


# ── Onglet « Visites terrain » ───────────────────────────────────────────────

@router.get("/visites", dependencies=[Depends(require_views("clients"))])
async def visites(request: Request, limit: int = Query(default=12, ge=5, le=50)):
    """Fichier de visite (gabarit) et comptes à couvrir (réels)."""
    portefeuille = await _crm(request).get_account_activity()
    return await _hors_boucle(mod_visites.build_fichier_visites, portefeuille, None, limit)


# ── Alertes ──────────────────────────────────────────────────────────────────

@router.get("/alertes", dependencies=[Depends(require_views("clients"))])
async def liste_alertes(request: Request, limit: int = Query(default=25, ge=5, le=100)):
    """File d'alertes dérivée des signaux calculés, avec l'âge de chaque clé.

    L'appel ÉCRIT : la première apparition d'une clé est enregistrée pour que
    « ce compte alerte depuis 3 jours » soit calculable — impossible sur un miroir
    qui ne garde que l'état courant. Les alertes déjà écartées restent écartées.
    """
    crm = _crm(request)
    portefeuille, opportunites, series = await asyncio.gather(
        crm.get_account_activity(),
        q.fetch_opportunites(),
        q.fetch_series_mensuelles_par_compte(),
    )
    dormance, pics, qualite = await asyncio.gather(
        _hors_boucle(build_suivi_dormance, portefeuille),
        _hors_boucle(mod_comptes.build_pics_activite, series),
        _hors_boucle(mod_qualite.build_qualite_pipe, opportunites, None, 50),
    )
    resultat = await _hors_boucle(
        mod_alertes.build_alertes, pics, dormance, qualite, None, limit, statique.SEUIL_CYCLE_VIE_XOF,
    )
    avec_etat = await q.sync_alertes(resultat["alertes"])
    # Le comptage des écartées se fait AVANT le filtrage : c'est le seul endroit
    # où le volume réellement produit reste visible, et le DC a demandé à savoir
    # combien d'alertes le système génère, pas seulement combien il en montre.
    resultat["totaux"]["nb_ecartees"] = sum(1 for a in avec_etat if a.get("ecartee"))
    resultat["alertes"] = [a for a in avec_etat if not a.get("ecartee")]
    resultat["totaux"]["nb_affichees"] = len(resultat["alertes"])
    return resultat


class EcarterAlerte(BaseModel):
    alert_key: str
    motif: str = ""


@router.post("/alertes/ecarter", dependencies=[Depends(require_views("clients"))])
async def ecarter(body: EcarterAlerte):
    """Écarte une alerte durablement, avec son motif.

    Réponse du DC à sa propre crainte du bruit : une alerte traitée ne doit pas
    réapparaître le lendemain. Le motif est conservé — une alerte écartée sans
    raison connue ne s'audite pas.
    """
    ok = await q.ecarter_alerte(body.alert_key, body.motif)
    return {"ecartee": ok, "alert_key": body.alert_key, "at": date.today().isoformat()}
