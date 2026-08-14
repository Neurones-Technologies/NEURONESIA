"""Endpoints du pilotage financier — un endpoint par ÉCRAN, pas par calcul.

Le découpage suit les trois tableaux de bord de la note DAF : un onglet qui
affiche cinq blocs paie un appel, pas cinq. Même arbitrage que
`uc_commercial/router.py` et que `/dashboard/account-activity`.

Les agrégations sont déportées par `_hors_boucle` : ce sont des boucles Python
pures sur 2 957 factures, 2 133 achats et 2 408 dossiers, qui gèleraient le worker
si elles étaient appelées en ligne dans un `async def`. Même raison et mêmes
limites que le déport de `api/v1/dashboard.py`.

Gating : les vues existantes de `config/permissions.py` sont réutilisées telles
quelles (`tresorerie`, `couts`, `dashboard`). Aucune vue nouvelle n'est créée — la
matrice est éditable en base par la page Paramètres, et y ajouter une ligne
obligerait chaque installation à la re-régler. Le profil DAF (`dir_financier`) a
`tresorerie`, `couts` et `dashboard` par défaut ; le DG a `tresorerie` et
`dashboard` et voit donc lui aussi ces écrans, ce qui est voulu.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request

from api.v1.dependencies import require_views
from modules.uc_daf import budget as mod_budget
from modules.uc_daf import queries as q
from modules.uc_daf import relation_commerciale as mod_relation
from modules.uc_daf import series as mod_series
from modules.uc_daf import statique
from modules.uc_daf import tresorerie_prev as mod_tresorerie

router = APIRouter(prefix="/daf", tags=["Pilotage financier"])


async def _hors_boucle(fn, *args, **kwargs):
    return await asyncio.to_thread(lambda: fn(*args, **kwargs))


def _annee(annee: int | None) -> int:
    return annee or datetime.now().year


def _aujourdhui() -> date:
    return date.today()


def _jours_ecoules(annee: int, aujourdhui: date) -> int:
    """Jours d'exercice écoulés — 365 (ou 366) sur un exercice révolu.

    Le DSO bilanciel divise par un nombre de jours : prendre 365 sur un exercice en
    cours diviserait un encours de huit mois par une année pleine et diviserait le
    délai par deux.
    """
    debut = date(annee, 1, 1)
    if aujourdhui.year > annee:
        return (date(annee, 12, 31) - debut).days + 1
    if aujourdhui.year < annee:
        return 0
    return (aujourdhui - debut).days + 1


async def _socle_creances(factures: list[dict], annee: int, aujourdhui: date) -> dict:
    """Socle de créances mesuré, partagé par les trois tableaux de bord."""
    ca = await q.fetch_ca_mensuel(annee)
    ca_exercice = sum(m["ca_xof"] for m in ca)
    return await _hors_boucle(
        mod_relation.mesurer_creances, factures, aujourdhui, ca_exercice, _jours_ecoules(annee, aujourdhui),
    )


# ── Tableau de bord n°1 — Budget ─────────────────────────────────────────────

@router.get("/budget", dependencies=[Depends(require_views("couts", "dashboard"))])
async def tableau_budget(
    request: Request,
    annee: int | None = Query(default=None),
    limit: int = Query(default=mod_budget.TOP_CHARGES, ge=5, le=30),
):
    """Performance, résultat net projeté, marge brute réalisée, top des charges, lignes budgétaires.

    Les cinq blocs partagent la même lecture des achats et des dossiers : les
    séparer en cinq endpoints ferait payer cinq fois les mêmes 4 500 lignes.
    """
    an = _annee(annee)
    aujourdhui = _aujourdhui()
    achats, dossiers, factures, ca_mensuel, annees = await asyncio.gather(
        q.fetch_achats(), q.fetch_dossiers(), q.fetch_factures_clients(),
        q.fetch_ca_mensuel(an), q.fetch_annees_disponibles(),
    )
    socle = await _socle_creances(factures, an, aujourdhui)

    marge, charges, lignes = await asyncio.gather(
        _hors_boucle(mod_budget.build_marge_brute, dossiers, achats, ca_mensuel, an, aujourdhui),
        _hors_boucle(mod_budget.build_top_charges, achats, an, aujourdhui, limit),
        _hors_boucle(mod_budget.build_lignes_budgetaires, achats, an, aujourdhui),
    )
    resultat, performance, burn_down, marge_annuelle = await asyncio.gather(
        _hors_boucle(mod_budget.build_resultat_net, marge, an, aujourdhui),
        _hors_boucle(mod_budget.build_performance, marge, socle, lignes, an, aujourdhui),
        _hors_boucle(
            mod_series.build_burn_down, achats, ca_mensuel,
            lignes["totaux"]["budget_total_xof"], an, aujourdhui,
        ),
        _hors_boucle(
            mod_series.build_marge_annuelle, dossiers, aujourdhui,
            statique.CIBLES_PERFORMANCE["marge_brute_pct"],
        ),
    )
    return {
        "annee": an,
        "as_of": aujourdhui.isoformat(),
        "annees_disponibles": annees,
        "performance": performance,
        "resultat_net": resultat,
        "marge_brute": marge,
        "top_charges": charges,
        "lignes_budgetaires": lignes,
        # Séries temporelles : la pente, que les blocs ci-dessus ne donnent pas.
        "burn_down": burn_down,
        "marge_annuelle": marge_annuelle,
    }


# ── Tableau de bord n°2 — Relation commerciale ───────────────────────────────

@router.get("/relation-commerciale", dependencies=[Depends(require_views("tresorerie"))])
async def tableau_relation_commerciale(
    request: Request,
    annee: int | None = Query(default=None),
    limit: int = Query(default=15, ge=5, le=50),
):
    """DSO (deux lectures), DPO, balance âgée et suivi des mauvais payeurs."""
    an = _annee(annee)
    aujourdhui = _aujourdhui()
    factures, factures_fournisseurs, achats, delais, annees = await asyncio.gather(
        q.fetch_factures_clients(),
        q.fetch_factures_fournisseurs(),
        q.fetch_achats(),
        q.fetch_delais_negocies(),
        q.fetch_annees_disponibles(),
    )
    socle = await _socle_creances(factures, an, aujourdhui)

    dso, dpo, balance, payeurs, serie_encours, serie_dso = await asyncio.gather(
        _hors_boucle(mod_relation.build_dso, factures, socle, aujourdhui, an),
        _hors_boucle(mod_relation.build_dpo, factures_fournisseurs, achats, delais, aujourdhui, an),
        _hors_boucle(mod_relation.build_balance_agee, factures, aujourdhui),
        _hors_boucle(mod_relation.build_mauvais_payeurs, factures, aujourdhui, limit),
        _hors_boucle(mod_series.build_serie_encours, factures, aujourdhui),
        _hors_boucle(
            mod_series.build_serie_dso, factures, aujourdhui,
            statique.CIBLES_PERFORMANCE["dso_jours"],
        ),
    )
    return {
        "annee": an,
        "as_of": aujourdhui.isoformat(),
        "annees_disponibles": annees,
        "dso": dso,
        "dpo": dpo,
        "balance_agee": balance,
        "mauvais_payeurs": payeurs,
        # Séries temporelles : le niveau affiché plus haut masque une tendance —
        # 65,9 jours de délai moyen cachent un doublement sur deux trimestres.
        "serie_encours": serie_encours,
        "serie_dso": serie_dso,
        # Écart DSO / DPO : ce que l'entreprise finance sur sa propre trésorerie. Le
        # calcul reste ici et non dans un module, parce qu'il croise deux blocs de
        # provenance différente et que sa fiabilité est celle du plus faible des deux.
        "cycle_cash": {
            "source": dpo["source"],
            "dso_jours": dso["delai_encaissement_moyen_jours"],
            "dpo_jours": dpo["dpo_jours"],
            "ecart_jours": (
                round(dso["delai_encaissement_moyen_jours"] - dpo["dpo_jours"], 1)
                if dso["delai_encaissement_moyen_jours"] is not None and dpo["dpo_jours"] is not None
                else None
            ),
            "lecture": (
                "Un DSO supérieur au DPO signifie que l'entreprise paie ses fournisseurs avant "
                "d'être payée par ses clients : l'écart, multiplié par le chiffre d'affaires "
                "journalier, est le besoin de trésorerie que ce décalage impose."
            ),
            "fiabilite": (
                "Le DPO étant posé faute de factures fournisseurs, cet écart est indicatif : il "
                "montre la forme de l'indicateur, pas le besoin de financement réel."
                if dpo["source"] != statique.SOURCE_REELLE
                else "Les deux délais sont mesurés."
            ),
        },
    }


# ── Tableau de bord n°3 — Trésorerie prévisionnelle ──────────────────────────

@router.get("/tresorerie-previsionnelle", dependencies=[Depends(require_views("tresorerie"))])
async def tableau_tresorerie_previsionnelle(
    request: Request,
    annee: int | None = Query(default=None),
    horizon_jours: int = Query(default=statique.HORIZON_VIGILANCE_JOURS, ge=7, le=120),
    horizon_mois: int = Query(default=statique.HORIZON_ATTERRISSAGE_MOIS, ge=1, le=12),
    limit: int = Query(default=20, ge=5, le=60),
):
    """Vigilance sur les créances proches de l'échéance et atterrissage mensuel calendaire."""
    an = _annee(annee)
    aujourdhui = _aujourdhui()
    factures, achats, dossiers, annees = await asyncio.gather(
        q.fetch_factures_clients(), q.fetch_achats(), q.fetch_dossiers(), q.fetch_annees_disponibles(),
    )
    socle = await _socle_creances(factures, an, aujourdhui)

    vigilance, atterrissage = await asyncio.gather(
        _hors_boucle(mod_tresorerie.build_vigilance, factures, aujourdhui, horizon_jours, limit),
        _hors_boucle(mod_tresorerie.build_atterrissage, factures, achats, aujourdhui, an, horizon_mois),
    )
    return {
        "annee": an,
        "as_of": aujourdhui.isoformat(),
        "annees_disponibles": annees,
        "vigilance": vigilance,
        "atterrissage": atterrissage,
        # Position : ce qui est réellement connu du bilan à date. Le reste à
        # encaisser des dossiers est servi à côté de l'encours facturé — ce n'est
        # pas la même chose, et le confondre compterait deux fois la même créance.
        "position": {
            "source": statique.SOURCE_REELLE,
            "encours_facture_xof": socle["encours_xof"],
            "encours_echu_xof": socle["encours_echu_xof"],
            "nb_factures_ouvertes": socle["nb_factures_ouvertes"],
            "reste_a_encaisser_dossiers_xof": sum(d["reste_a_encaisser_xof"] for d in dossiers),
            "backlog_dossiers_xof": sum(d["backlog_xof"] for d in dossiers),
            "fournisseurs_restant_dossiers_xof": sum(d["fournisseurs_restant_xof"] for d in dossiers),
            "note": (
                "L'encours facturé vient des factures clients ; le reste à encaisser des dossiers "
                "vient du suivi de projet et inclut du non encore facturé. Les additionner "
                "compterait deux fois la même créance. Aucun solde bancaire n'existe dans le "
                "système : il n'y a pas de position de trésorerie à afficher."
            ),
        },
    }
