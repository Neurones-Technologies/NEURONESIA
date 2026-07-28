"""Détection de dossiers d'arbitrage réels.

Un dossier naît quand deux lectures indépendantes du même client pointent
dans des directions opposées — typiquement la Direction Financière qui
identifie un débiteur en retard pendant que le Commercial y voit un
renouvellement ou un cross-sell en cours. Jamais de conflit inventé :
uniquement des recoupements entre agrégats déjà calculés par les modules
existants (unpaid, crosssell, clients). Le calcul de mandat/coût du report
reste une estimation d'ordre de grandeur, explicitement documentée comme
telle — jamais présentée comme un fait mesuré.
"""
from __future__ import annotations

# Au-delà de ce seuil d'enjeu, aucune direction ne tranche seule (cf. mockup —
# "au-delà de 150 M, aucune direction ne tranche seule").
ENJEU_MANDAT_DG_XOF = 150_000_000

# Estimation d'ordre de grandeur du coût d'un report d'une semaine, en
# proportion de l'enjeu — pas une mesure, un repère pour trier les dossiers.
COUT_REPORT_RATIO_SEMAINE = 0.02

_TYPE_TO_ROLE = {
    "Renouvellement": "commercial",
    "Obsolescence": "commercial",
    "Cross-sell": "dir_commercial",
    "Up-sell": "dir_commercial",
}


def _m(xof: float) -> int:
    return round(xof / 1_000_000)


def _mandat(enjeu_xof: float, profils: list[str]) -> str:
    if enjeu_xof >= ENJEU_MANDAT_DG_XOF:
        return "dg"
    return profils[0] if profils else "dg"


def detect_client_conflicts(
    unpaid_top_debiteurs: list[dict],
    crosssell_signals: dict,
    portfolio_by_client: dict[str, dict],
) -> list[dict]:
    """Recoupe les débiteurs en retard (signal Direction Financière) avec les
    signaux commerciaux actifs sur le même client (signal DC/AM) — c'est ce
    recoupement, et lui seul, qui constitue une tension réelle à arbitrer."""
    debtors = {d["client"]: d for d in unpaid_top_debiteurs if d.get("retard_max_jours", 0) > 0}
    if not debtors:
        return []

    commercial_signals: dict[str, list[dict]] = {}
    for key, label in (
        ("renouvellement", "Renouvellement"),
        ("obsolete", "Obsolescence"),
        ("cross_sell", "Cross-sell"),
        ("up_sell", "Up-sell"),
    ):
        for item in crosssell_signals.get(key, []):
            commercial_signals.setdefault(item["client"], []).append({**item, "type": label})

    dossiers: list[dict] = []
    for client, debt in debtors.items():
        signals = commercial_signals.get(client)
        if not signals:
            continue
        best = max(signals, key=lambda s: s["montant_xof"])
        enjeu = float(best["montant_xof"])
        role_commercial = _TYPE_TO_ROLE.get(best["type"], "dir_commercial")
        profils = ["dir_financier", role_commercial]
        portfolio = portfolio_by_client.get(client, {})

        dossiers.append({
            "subject_ref": client,
            "subject_label": f"{client} — {debt['nb_factures']} facture(s) échue(s) contre {best['type'].lower()} en cours",
            "profils_impliques": profils,
            "enjeu_xof": enjeu,
            "echeance": "aucune",
            "cout_report_xof_semaine": round(enjeu * COUT_REPORT_RATIO_SEMAINE),
            "mandat_role": _mandat(enjeu, profils),
            "positions": [
                {
                    "role": "dir_financier",
                    "text": f"{debt['nb_factures']} facture(s) impayée(s) pour {_m(debt['montant_total_xof'])} M FCFA, retard maximum {debt['retard_max_jours']} j.",
                },
                {
                    "role": role_commercial,
                    "text": f"{best['type']} détecté sur {best['titre']} : {best['detail']}",
                },
            ],
            "backlog_xof": portfolio.get("backlog_xof"),
            "reste_a_encaisser_xof": portfolio.get("reste_a_encaisser_xof"),
            "signaux_portefeuille": portfolio.get("signaux", []),
        })

    return sorted(dossiers, key=lambda d: d["enjeu_xof"], reverse=True)


_ROLE_LABELS = {
    "dg": "Direction générale",
    "dir_commercial": "Direction commerciale",
    "dir_operations": "Direction des opérations",
    "dir_financier": "Direction financière",
    "commercial": "Compte (account manager)",
}


def build_options(dossier: dict) -> list[dict]:
    """Deux options déterministes, toujours les mêmes structure de compromis —
    seuls les chiffres varient. Le LLM n'intervient jamais ici : uniquement
    pour l'avocat du contraire (cf. narratif.py), qui est un exercice de
    plaidoyer et non un fait à calculer."""
    enjeu_m = _m(dossier["enjeu_xof"])
    role_financier, role_commercial = dossier["profils_impliques"][0], dossier["profils_impliques"][1]

    return [
        {
            "code": "A",
            "titre": "Conditionner l'engagement commercial au recouvrement",
            "description": (
                f"Aucune nouvelle proposition ({enjeu_m} M FCFA) tant que les factures échues ne sont pas régularisées."
            ),
            "recommandee": True,
            "consequences": [
                {"role": role_financier, "text": "Levier de négociation sur l'impayé, recouvrement prioritaire.", "variant": "s"},
                {"role": role_commercial, "text": f"Risque de perdre les {enjeu_m} M FCFA au profit d'un concurrent pendant le blocage.", "variant": "r"},
            ],
        },
        {
            "code": "B",
            "titre": "Poursuivre l'engagement commercial, accepter le risque",
            "description": f"Le dossier commercial ({enjeu_m} M FCFA) avance sans attendre l'apurement de l'impayé.",
            "recommandee": False,
            "consequences": [
                {"role": role_commercial, "text": "Relation commerciale préservée, dossier maintenu en vie.", "variant": "s"},
                {"role": role_financier, "text": "Exposition qui continue de courir sans contrepartie.", "variant": "r"},
            ],
        },
    ]


def missing_info(dossier: dict) -> list[dict]:
    """Ce qu'il faut vérifier avant de trancher — générique mais réel : ce sont
    exactement les données que le miroir Odoo ne contient pas (motif du
    retard, échanges avec le client), pas une liste inventée par dossier."""
    return [
        {"text": "Motif du retard de paiement — aucune donnée du miroir ne l'explique, seul un appel client le donnerait.", "owner": _ROLE_LABELS.get(dossier["profils_impliques"][1], "Compte"), "delay": "2 jours"},
        {"text": "Confirmation que le dossier commercial est toujours d'actualité côté client.", "owner": _ROLE_LABELS.get(dossier["profils_impliques"][1], "Compte"), "delay": "2 jours"},
    ]
