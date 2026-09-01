"""Ce qui a bougé depuis le dernier briefing — le deuxième mécanisme de la trame.

Un briefing qui reprend chaque matin les mêmes agrégats de stock n'est pas lu
deux fois. Ce qui se lit, c'est la liste courte de ce qui a changé : une commande
entrée, une facture réglée, une opportunité passée en négociation.

CE QUE LE MIROIR PERMET DE DÉTECTER, ET CE QU'IL NE PERMET PAS
──────────────────────────────────────────────────────────────
Détectable, parce que le fait porte sa date :
  - commande entrée          `sale_orders.date_order`
  - facture émise            `invoices.invoice_date`
  - facture réglée           `invoices.payment_date`
  - achat engagé             `purchase_orders.date_order`
  - opportunité retouchée    `opportunities.write_date`

NON détectable, et il faut le dire plutôt que de le simuler :
  - « opportunité CRÉÉE hier » — `create_date` est inexploitable : 4 927 des
    9 475 opportunités portent la même date du 07/04/2026, écrasée par la reprise
    de données (anomalie A1). Compter les créations du jour sur ce champ
    produirait 0 tous les jours, puis 4 927 le 7 avril.
  - « commande CONFIRMÉE hier » — `sale_orders.state` ne prend qu'une seule
    valeur dans tout le miroir (`sale`). Aucune transition n'y est observable.
  - le CHANGEMENT D'ÉTAPE d'une opportunité — Odoo ne remonte pas d'historique de
    stage, et `write_date` dit seulement « quelque chose a été retouché ».

Ce dernier point est le seul qui se rattrape : deux `pipeline_snapshots` pris à
deux dates différentes se soustraient. C'est la seule source de vérité sur les
mouvements d'étape, et elle ne remonte pas plus haut que le premier snapshot —
d'où `depuis_snapshot`, qui dit franchement à partir de quand la mesure existe.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import text

from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Une opportunité sans retouche depuis ce délai « dort ». Valeur par défaut
# seulement : le seuil réel se règle par rôle (cf. uc_briefing.seuils).
DORMANCE_JOURS = 15

_FLUX = {
    "commandes_entrees": (
        "sale_orders", "date_order", "amount", "client_name", "name",
        "state IN ('sale', 'done')",
    ),
    "factures_emises": (
        "invoices", "invoice_date", "amount", "client_id", "invoice_name",
        "status != 'cancelled'",
    ),
    "factures_reglees": (
        "invoices", "payment_date", "amount", "client_id", "invoice_name",
        "status != 'cancelled'",
    ),
    "achats_engages": (
        "purchase_orders", "date_order", "amount", "client_name", "name",
        "state = 'purchase'",
    ),
}


async def _mouvement(cle: str, depuis: date, jusqu_a: date, limite: int) -> dict:
    table, col_date, col_montant, col_tiers, col_ref, filtre = _FLUX[cle]
    sql = f"""
        SELECT {col_ref}, {col_tiers}, {col_montant}, date({col_date})
        FROM {table}
        WHERE {filtre} AND {col_date} IS NOT NULL
          AND date({col_date}) >= date(:depuis) AND date({col_date}) <= date(:jusqu_a)
        ORDER BY {col_montant} DESC
    """
    async with AsyncSessionLocal() as session:
        lignes = (await session.execute(
            text(sql), {"depuis": depuis.isoformat(), "jusqu_a": jusqu_a.isoformat()}
        )).all()
    return {
        "nb": len(lignes),
        "montant_xof": sum(float(l[2] or 0) for l in lignes),
        "top": [
            {"ref": l[0], "tiers": l[1], "montant_xof": float(l[2] or 0), "date": str(l[3])[:10]}
            for l in lignes[:limite]
        ],
    }


async def _opportunites_retouchees(depuis: date, jusqu_a: date, limite: int) -> dict:
    """Opportunités dont `write_date` tombe dans la fenêtre.

    Dit « retouchée » et jamais « avancée » : le champ ne distingue pas un
    changement d'étape d'une correction d'orthographe. Les vrais mouvements
    d'étape sortent de `changements_etape`.
    """
    async with AsyncSessionLocal() as session:
        lignes = (await session.execute(text("""
            SELECT name, client_name, expected_revenue, stage, date(write_date)
            FROM opportunities
            WHERE write_date IS NOT NULL
              AND date(write_date) >= date(:depuis) AND date(write_date) <= date(:jusqu_a)
            ORDER BY expected_revenue DESC
        """), {"depuis": depuis.isoformat(), "jusqu_a": jusqu_a.isoformat()})).all()
    return {
        "nb": len(lignes),
        "montant_xof": sum(float(l[2] or 0) for l in lignes),
        "top": [
            {"opportunite": l[0], "client": l[1], "revenu_attendu_xof": float(l[2] or 0),
             "stade": l[3], "date": str(l[4])[:10]}
            for l in lignes[:limite]
        ],
    }


async def _bornes_snapshot(depuis: date, jusqu_a: date) -> tuple[date, date] | None:
    """Les deux dates de `pipeline_snapshots` qui encadrent le mieux la fenêtre :
    la dernière au plus tard `jusqu_a`, et la dernière strictement antérieure à
    `depuis`. Sans deux points, il n'y a pas de différence à faire."""
    async with AsyncSessionLocal() as session:
        fin = (await session.execute(text(
            "SELECT MAX(snapshot_date) FROM pipeline_snapshots WHERE snapshot_date <= date(:j)"
        ), {"j": jusqu_a.isoformat()})).scalar()
        debut = (await session.execute(text(
            "SELECT MAX(snapshot_date) FROM pipeline_snapshots WHERE snapshot_date < date(:d)"
        ), {"d": depuis.isoformat()})).scalar()
    if not fin or not debut:
        return None
    conv = lambda v: v if isinstance(v, date) else date.fromisoformat(str(v)[:10])  # noqa: E731
    debut, fin = conv(debut), conv(fin)
    return None if debut >= fin else (debut, fin)


async def changements_etape(depuis: date, jusqu_a: date, limite: int = 5) -> dict:
    """Mouvements d'étape réels, par différence entre deux snapshots du pipeline.

    C'est la seule source de vérité disponible sur « qu'est-ce qui a bougé dans le
    pipe » : Odoo ne remonte aucun historique de stage. La contrepartie est que la
    mesure ne remonte pas avant le premier snapshot — `mesurable` le dit, et les
    puces appelantes ne doivent jamais présenter une absence de snapshot comme une
    absence de mouvement.
    """
    bornes = await _bornes_snapshot(depuis, jusqu_a)
    if bornes is None:
        return {"mesurable": False, "raison": "moins de deux snapshots de pipeline encadrent la période"}
    debut, fin = bornes

    async with AsyncSessionLocal() as session:
        lignes = (await session.execute(text("""
            SELECT apres.opp_id, apres.name, apres.client_name, apres.expected_revenue,
                   avant.stage, apres.stage
            FROM pipeline_snapshots apres
            JOIN pipeline_snapshots avant
              ON avant.opp_id = apres.opp_id AND avant.snapshot_date = date(:debut)
            WHERE apres.snapshot_date = date(:fin) AND avant.stage != apres.stage
            ORDER BY apres.expected_revenue DESC
        """), {"debut": debut.isoformat(), "fin": fin.isoformat()})).all()
        entrees = (await session.execute(text("""
            SELECT COUNT(*), COALESCE(SUM(expected_revenue), 0) FROM pipeline_snapshots apres
            WHERE apres.snapshot_date = date(:fin) AND NOT EXISTS (
                SELECT 1 FROM pipeline_snapshots avant
                WHERE avant.opp_id = apres.opp_id AND avant.snapshot_date = date(:debut))
        """), {"debut": debut.isoformat(), "fin": fin.isoformat()})).fetchone()

    return {
        "mesurable": True,
        "depuis_snapshot": debut.isoformat(),
        "jusqu_a_snapshot": fin.isoformat(),
        "nb": len(lignes),
        "montant_xof": sum(float(l[3] or 0) for l in lignes),
        "nb_entrees_pipe": entrees[0] or 0,
        "montant_entrees_xof": float(entrees[1] or 0),
        "top": [
            {"opportunite": l[1], "client": l[2], "revenu_attendu_xof": float(l[3] or 0),
             "de": l[4], "vers": l[5]}
            for l in lignes[:limite]
        ],
    }


async def hygiene_pipe(seuil_jours: int = DORMANCE_JOURS, limite: int = 5,
                       as_of: date | None = None) -> dict:
    """Répond au « qu'est-ce qui dort ? » de la trame — en deux tas, pas un seul.

    Un premier jet remontait 3 339 opportunités et 131 Md « dormantes », ce qui
    n'est pas un signal mais tout le pipe. La coupe utile n'est pas l'ancienneté
    de la retouche, c'est l'ÉCHÉANCE :

      - `a_relancer` : échéance encore à venir, mais plus aucune retouche depuis
        `seuil_jours`. Ce sont des affaires vivantes qu'on est en train de
        perdre par inaction — la seule liste sur laquelle on décroche son
        téléphone aujourd'hui.
      - `a_assainir` : échéance dépassée et stade toujours ouvert. 3 015 lignes,
        107 881 M FCFA, 82 % du pipe affiché (anomalie A4). Ce n'est pas un
        travail de relance mais de clôture, et tant qu'il n'est pas fait, tout
        montant de pipeline publié est faux d'un facteur douze.

    Les mêmes lignes dans un seul tas donneraient une liste que personne ne peut
    traiter, triée par montant, donc dominée par les plus périmées.

    Réserve commune : `activity_date_deadline` n'étant pas synchronisé, la mesure
    porte sur l'absence de MODIFICATION, jamais sur l'absence d'activité
    planifiée. Une affaire peut figurer ici et avoir un rendez-vous demain.
    """
    from modules.uc_briefing.indicateurs import _PIPE_OUVERT

    as_of = as_of or date.today()
    params = {
        "a": as_of.isoformat(),
        "limite": (as_of - timedelta(days=seuil_jours)).isoformat(),
    }
    silence = ("CAST(julianday(date(:a)) - julianday(date(write_date)) AS INTEGER)")

    async def _liste(condition: str) -> list[tuple]:
        async with AsyncSessionLocal() as session:
            return (await session.execute(text(f"""
                SELECT name, client_name, expected_revenue, stage, {silence}, date(deadline)
                FROM opportunities
                WHERE expected_revenue > 0 AND {_PIPE_OUVERT} AND {condition}
                ORDER BY expected_revenue DESC
            """), params)).all()

    def _bloc(lignes: list[tuple]) -> dict:
        return {
            "nb": len(lignes),
            "montant_xof": sum(float(l[2] or 0) for l in lignes),
            "top": [
                {"opportunite": l[0], "client": l[1], "revenu_attendu_xof": float(l[2] or 0),
                 "stade": l[3], "jours_silence": int(l[4] or 0), "deadline": l[5]}
                for l in lignes[:limite]
            ],
        }

    a_relancer = await _liste(
        "deadline IS NOT NULL AND date(deadline) >= date(:a) "
        "AND write_date IS NOT NULL AND date(write_date) < date(:limite)"
    )
    a_assainir = await _liste("deadline IS NOT NULL AND date(deadline) < date(:a)")
    sans_echeance = await _liste("deadline IS NULL")

    return {
        "seuil_jours": seuil_jours,
        "a_relancer": _bloc(a_relancer),
        "a_assainir": _bloc(a_assainir),
        "sans_echeance": _bloc(sans_echeance),
        "reserve": "mesure l'absence de modification, non l'absence d'activité planifiée "
                   "(`activity_date_deadline` n'est pas synchronisé)",
    }


async def mouvements(depuis: date, jusqu_a: date | None = None, limite: int = 3) -> dict:
    """Tout ce qui a bougé sur la fenêtre, prêt à être mis en puces.

    Bornes INCLUSIVES des deux côtés : un briefing du matin qui couvre « hier »
    passe `depuis = jusqu_a = J-1`, et une reprise après week-end passe le
    vendredi et le dimanche.
    """
    jusqu_a = jusqu_a or date.today()
    if depuis > jusqu_a:
        raise ValueError(f"Fenêtre vide : {depuis} > {jusqu_a}")

    resultat: dict = {"depuis": depuis.isoformat(), "jusqu_a": jusqu_a.isoformat()}
    for cle in _FLUX:
        resultat[cle] = await _mouvement(cle, depuis, jusqu_a, limite)
    resultat["opportunites_retouchees"] = await _opportunites_retouchees(depuis, jusqu_a, limite)
    resultat["changements_etape"] = await changements_etape(depuis, jusqu_a, limite)
    resultat["total_evenements"] = sum(
        resultat[cle]["nb"] for cle in (*_FLUX, "opportunites_retouchees")
    )
    return resultat
