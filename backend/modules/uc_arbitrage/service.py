"""Assemblage de la file d'arbitrage, hors couche HTTP : le router l'expose,
le briefing quotidien le consomme. `_compute_candidates` vivait dans le
router (donc couplé à `Request`) et n'était pas réutilisable depuis un job
qui n'a pas de contexte FastAPI.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from core.services.ttl_cache import cached
from modules.uc_arbitrage import aggregation, store
from modules.uc_crosssell.signals import get_signals as crosssell_signals

logger = logging.getLogger(__name__)

# La file de candidats ne dépend que du miroir Odoo, rafraîchi par la sync
# planifiée (`jobs/scheduler.py`, au minimum toutes les 5 min) : la recalculer à
# chaque requête refait le même travail sur des données identiques. L'écran
# enchaîne systématiquement `/file` puis `/dossier/{ref}` — sans cache, le
# second appel refaisait intégralement le calcul du premier pour n'en garder
# qu'une ligne. Volontairement sous le pas de sync, pour qu'une sync soit
# toujours visible au tour suivant.
_CANDIDATS_TTL_SECONDES = 120.0
_CANDIDATS_CACHE_KEY = ("arbitrage_candidats",)

# Les entités du groupe (NEURONES*) ne s'arbitrent pas comme un client tiers :
# sans ce filtre, NEURONES TECHNOLOGIES BF représente à elle seule l'essentiel
# de l'enjeu observé, présenté au DG comme de l'enjeu client alors que c'est
# un artefact intra-groupe. Même règle que get_year_stats(exclude_internal=True).
_MOTIF_ENTITE_INTERNE = "NEURONES"


def _est_interne(nom: str) -> bool:
    return _MOTIF_ENTITE_INTERNE in (nom or "").upper()


async def _fetch_behaviour(crm, client: str) -> tuple[str, dict | None, dict | None]:
    try:
        collection, behaviour = await asyncio.gather(
            crm.get_invoice_collection_stats(client_name=client),
            crm.get_payment_behaviour(client_name=client),
        )
        return client, collection, behaviour
    except Exception as exc:
        logger.warning("Comportement de paiement indisponible pour « %s » : %s", client, exc)
        return client, None, None


async def _compute_all_candidates(crm) -> list[dict]:
    """File complète, sans filtrage — c'est elle qui est mise en cache."""
    unpaid = await crm.get_unpaid_exposure()

    # Seuls les débiteurs en retard (≤ 10 clients, cf. top_10_debiteurs) peuvent
    # produire un dossier : tout ce qui suit se restreint à eux plutôt que de
    # lire le miroir entier.
    debiteurs = [d for d in unpaid.get("top_10_debiteurs", []) if d.get("retard_max_jours", 0) > 0]
    clients = [d.get("client") or "" for d in debiteurs]
    clients = [c for c in clients if c and c != "—"]
    if not clients:
        return []

    # Les trois lectures sont indépendantes entre elles : elles partent ensemble
    # au lieu d'additionner leurs latences. Les signaux commerciaux passent par
    # `crosssell_signals`, partagé avec les autres modules qui les demandent
    # (cf. uc_crosssell/signals.py) — c'est le poste le plus lourd du calcul et
    # il produisait quatre fois le même résultat.
    #
    # Un appel de comportement qui échoue laisse son dossier sans profil mesuré
    # (classe `historique_insuffisant`) plutôt que de faire tomber la file entière.
    crosssell, portfolio, comportements = await asyncio.gather(
        crosssell_signals(crm),
        crm.get_client_portfolio(clients=clients),
        asyncio.gather(*(_fetch_behaviour(crm, client) for client in clients)),
    )

    portfolio_by_client = {c["client"]: c for c in portfolio}
    collection_stats = {c: coll for c, coll, beh in comportements if coll is not None}
    behaviour = {c: beh for c, coll, beh in comportements if beh is not None}

    return aggregation.detect_client_conflicts(
        debiteurs, crosssell, portfolio_by_client, collection_stats, behaviour,
    )


async def compute_candidates(
    crm, exclude_internal: bool = False, subject_ref: str | None = None
) -> list[dict]:
    """`subject_ref` restreint le résultat à un seul client (utilisé par
    `/arbitrage/dossier/{ref}`, qui n'a besoin que d'un dossier).

    Le filtrage se fait désormais APRÈS le calcul, sur la file mise en cache,
    et non plus en amont : recalculer la file pour n'en garder qu'une ligne
    coûtait presque aussi cher que la calculer entière, alors que l'écran vient
    précisément d'appeler `/file` juste avant.
    """
    candidats = await cached(
        _CANDIDATS_CACHE_KEY, _CANDIDATS_TTL_SECONDES, lambda: _compute_all_candidates(crm)
    )
    if subject_ref:
        candidats = [d for d in candidats if d["subject_ref"] == subject_ref]
    if exclude_internal:
        candidats = [d for d in candidats if not _est_interne(d["subject_ref"])]
    # Copie de surface : les dossiers viennent du cache et sont partagés entre
    # requêtes — un appelant qui poserait une clé dessus (cf. le `{**dossier}` du
    # router) corromprait la file servie aux suivants.
    return [dict(d) for d in candidats]


def _m(xof: float) -> int:
    return round(xof / 1_000_000)


async def compute_file(crm, exclude_internal: bool = False) -> dict:
    """Payload complet de /v1/arbitrage/file : kpi + candidats + décisions
    ouvertes. Corps repris tel quel du router (les deux consommateurs, écran
    et briefing, doivent voir exactement le même calcul)."""
    # Le registre de décisions ne passe PAS par le cache de la file : il change
    # au moment où un mandataire tranche, et l'écran doit voir sa décision
    # apparaître tout de suite. Les deux lectures sont indépendantes, donc
    # simultanées.
    #
    # `return_exceptions=True` puis relance : sans lui, le premier échec fait
    # sortir du gather en abandonnant l'autre lecture en plein vol — sa session
    # DB n'est jamais refermée et la coroutine orpheline explose au ramassage,
    # potentiellement dans un tout autre contexte (c'est ainsi qu'un test du
    # briefing faisait échouer la fixture d'un test voisin).
    resultats = await asyncio.gather(
        compute_candidates(crm, exclude_internal=exclude_internal),
        store.list_decisions(status="en_cours"),
        return_exceptions=True,
    )
    erreurs = [r for r in resultats if isinstance(r, BaseException)]
    if erreurs:
        raise erreurs[0]
    candidates, open_decisions = resultats

    now = datetime.utcnow()
    dossiers_ouverts = len(candidates) + len(open_decisions)
    enjeu_cumule = sum(d["enjeu_xof"] for d in candidates) + sum(d["enjeu_xof"] for d in open_decisions)
    cout_report = (
        sum(d["cout_report_xof_semaine"] for d in candidates)
        + sum(d["cout_report_xof_semaine"] for d in open_decisions)
    )
    # Échéance d'une décision ouverte = sa date butoir si elle en a une, sinon sa date
    # de relecture (posée d'office à la création depuis store.REVIEW_DELAY_DAYS). Les
    # dossiers non encore tranchés (`candidats`) n'ont, eux, aucune date : le miroir ne
    # contient aucune échéance contractuelle exploitable — cf. `echeance: "aucune"`.
    echeances = [d["due_date"] or d["review_date"] for d in open_decisions]
    echeances = [e for e in echeances if e]
    jours_echeance = None
    if echeances:
        prochaine = min(datetime.fromisoformat(e) for e in echeances)
        jours_echeance = max((prochaine - now).days, 0)
    revues_en_retard = sum(
        1 for d in open_decisions
        if d["review_date"] and datetime.fromisoformat(d["review_date"]) < now and not d["review_verdict"]
    )

    return {
        "kpi": {
            "dossiers_ouverts": dossiers_ouverts,
            "enjeu_cumule_m_fcfa": _m(enjeu_cumule),
            "echeance_plus_proche_jours": jours_echeance,
            "cout_report_m_fcfa_semaine": round(cout_report / 1_000_000, 1),
            "revues_en_retard": revues_en_retard,
            # Seuil au-delà duquel le mandat bascule à la DG (cf. aggregation._mandat) —
            # exposé pour que l'écran explique POURQUOI un dossier remonte à la DG plutôt
            # qu'à la direction dont vient le signal, au lieu de le laisser deviner.
            "seuil_mandat_dg_m_fcfa": _m(aggregation.ENJEU_MANDAT_DG_XOF),
        },
        "candidats": candidates,
        "decisions_ouvertes": open_decisions,
    }
