"""Mesure du rattachement par pays — ce qu'un filtre par pays voit, et ce qu'il ne voit pas.

Un chiffre « Burkina Faso » n'est juste que si l'on sait quelle part des objets
a pu être rattachée à un pays. Cette mesure le dit, module par module : nombre
et montant par pays, part non rattachée, et répartition par règle
(`entite_source`, cf. core/services/entites.py). C'est aussi l'outil pour voir
progresser la qualité des données (une équipe Odoo renseignée, un N° DC saisi).

Les contradictions sont comptées à part : une créance dont l'équipe Odoo
désigne un autre pays que sa facture nt360. La facture l'emporte (ordre des
règles), mais l'écart mérite d'être vu.
"""
from __future__ import annotations

from sqlalchemy import text

from core.services.entites import ENTITES, sql_equipe_vers_pays
from db.database import AsyncSessionLocal

# (module, vue, colonne de montant, filtre) — le filtre restreint au périmètre
# que les écrans lisent réellement (ex. les créances OUVERTES).
MODULES: list[tuple[str, str, str, str]] = [
    ("commandes", "v_sale_orders", "amount", "state IN ('sale', 'done')"),
    ("lignes_commande", "v_lignes_commande", "montant_ht", "1 = 1"),
    ("factures", "v_factures", "amount", "1 = 1"),
    ("creances_ouvertes", "v_creances", "amount_residual", "status = 'pending' AND amount_residual > 0"),
    ("dossiers", "v_dossiers", "backlog", "1 = 1"),
    ("achats", "v_purchase_orders", "amount", "1 = 1"),
    ("opportunites", "v_opportunities", "expected_revenue", "1 = 1"),
    ("opportunites_ouvertes", "v_opportunities", "expected_revenue", "stage_num BETWEEN 1 AND 5"),
    ("jalons", "v_jalons", "amount", "1 = 1"),
    ("consultations", "v_consultations", "montant", "1 = 1"),
]


async def mesurer(session_factory=None) -> dict:
    session_factory = session_factory or AsyncSessionLocal
    resultat: dict = {"modules": {}}
    async with session_factory() as session:
        for module, vue, montant, filtre in MODULES:
            lignes = (await session.execute(text(f"""
                SELECT entite, entite_source, COUNT(*), COALESCE(SUM({montant}), 0)
                FROM {vue} WHERE {filtre}
                GROUP BY entite, entite_source
            """))).all()
            total_nb = sum(r[2] for r in lignes)
            total_mt = sum(float(r[3]) for r in lignes)
            par_pays = {e: {"nb": 0, "montant_xof": 0.0} for e in ENTITES}
            non_rattache = {"nb": 0, "montant_xof": 0.0}
            par_source: dict[str, int] = {}
            for entite, source, nb, mt in lignes:
                cible = par_pays.get(entite) if entite else non_rattache
                if cible is None:           # valeur hors liste : traitée comme non rattachée
                    cible = non_rattache
                cible["nb"] += nb
                cible["montant_xof"] += float(mt)
                par_source[source or "non_rattache"] = par_source.get(source or "non_rattache", 0) + nb
            resultat["modules"][module] = {
                "vue": vue,
                "total_nb": total_nb,
                "total_montant_xof": round(total_mt),
                "taux_rattachement_pct": round((total_nb - non_rattache["nb"]) / total_nb * 100, 1) if total_nb else None,
                "par_pays": {e: {"nb": v["nb"], "montant_xof": round(v["montant_xof"])} for e, v in par_pays.items()},
                "non_rattache": {"nb": non_rattache["nb"], "montant_xof": round(non_rattache["montant_xof"])},
                "par_source": par_source,
            }

        equipe = sql_equipe_vers_pays("c.equipe")
        contradictions = (await session.execute(text(f"""
            SELECT COUNT(*) FROM v_creances c
            WHERE c.entite_source = 'facture' AND {equipe} IS NOT NULL AND {equipe} != c.entite
        """))).scalar() or 0
    resultat["contradictions"] = {
        "creances_equipe_vs_facture": contradictions,
        "regle": "la facture nt360 l'emporte sur l'équipe Odoo",
    }
    return resultat
