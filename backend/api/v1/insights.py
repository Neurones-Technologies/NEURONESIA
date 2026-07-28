"""
Insights IA par vue : le LLM analyse les données réelles du cockpit et
produit le contenu des emplacements dédiés du front (« Notifications
intelligentes », constats, recommandations) — au lieu de textes figés.

- Les chiffres viennent EXCLUSIVEMENT des agrégats réels passés en contexte.
- Redaction par rôle côté serveur : un profil sans accès Trésorerie ne voit
  jamais les impayés dans le contexte transmis au LLM (contrairement au
  mockup qui faisait cette redaction dans le prompt côté navigateur).
- Cache TTL 30 min par (vue, périmètre financier) — un LLM par page load
  serait lent et coûteux.
- Repli déterministe (règles) si le LLM est indisponible : le slot reste
  rempli, la réponse indique source = "regles".
"""
import json
import logging
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.dependencies import get_current_user
from config.permissions import can_access
from core.domain.user import User
from db.database import get_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/insights", tags=["Insights IA"])

_CACHE: dict[tuple[str, bool], tuple[dict, float]] = {}
_CACHE_TTL = 1800.0  # 30 min

_SYSTEM = """Tu es l'analyste commercial intégré au cockpit de Neurones Technologies \
(ESN IT, Côte d'Ivoire/Burkina Faso). On te fournit des agrégats RÉELS issus d'Odoo. \
Tu produis des notifications d'analyse concises et actionnables en français.

Règles strictes :
- N'utilise AUCUN chiffre absent des données fournies. Ne devine rien.
- Chaque notification relie un constat chiffré à une implication métier.
- Balises <b> autorisées pour les éléments clés, aucun autre HTML.
- Réponds UNIQUEMENT avec un JSON valide, sans texte autour, au format :
{"notifications": [{"sev": "good"|"warn"|"bad", "text": "…", "meta": "analyse IA · <thème>"}]}
- 4 à 6 notifications, ordonnées de la plus critique à la plus positive."""


def _fmt_m(xof: float) -> str:
    return f"{round(xof / 1_000_000):,} M FCFA".replace(",", " ")


async def _dashboard_context(crm, include_finance: bool) -> tuple[str, list[dict]]:
    """Contexte réel pour la vue dashboard + notifications de repli (règles)."""
    now_year = datetime.now().year
    year = await crm.get_year_stats(now_year)
    prev = await crm.get_year_stats(now_year - 1)
    pipeline = await crm.get_open_pipeline_stats()
    win = await crm.get_win_rate()
    margins = await crm.get_margin_stats()
    top_clients = await crm.get_top_clients(limit=5)

    delta_pct = ((year["revenue_xof"] - prev["revenue_xof"]) / prev["revenue_xof"] * 100) if prev["revenue_xof"] else 0

    lines = [
        f"CA commandé {now_year} : {_fmt_m(year['revenue_xof'])} ({year['orders_count']} commandes), "
        f"vs {now_year - 1} : {_fmt_m(prev['revenue_xof'])} ({prev['orders_count']} commandes) — delta {delta_pct:+.1f} %.",
        f"Pipeline OUVERT : {pipeline['total_opportunites']} opportunités, {_fmt_m(pipeline['ca_brut_xof'])} brut, "
        f"{_fmt_m(pipeline['ca_pondere_xof'])} pondéré. {pipeline['plus_un_an_nb']} opportunités "
        f"({pipeline['plus_un_an_pct']} %) ont plus d'un an — probablement obsolètes.",
        "Répartition par stade : " + ", ".join(
            f"{s['stade']} {s['nb']} opp. ({_fmt_m(s['ca_brut_xof'])})" for s in pipeline["par_stade"]
        ),
        f"Taux de transformation (historique) : {win['taux_nb_pct']} % en nombre "
        f"({win['gagnees_nb']} gagnées / {win['perdues_nb']} perdues), mais {win['taux_valeur_pct']} % en valeur "
        f"({_fmt_m(win['gagnees_valeur_xof'])} gagnés vs {_fmt_m(win['perdues_valeur_xof'])} perdus).",
        f"Marge définitive moyenne : {margins['perc_marge_definitive_moyen']} % ({margins['nb_dossiers']} dossiers).",
        "Top clients (CA commandé) : " + ", ".join(
            f"{c['client']} ({_fmt_m(c['ca_total_xof'])})" for c in top_clients
        ),
    ]
    if include_finance:
        unpaid = await crm.get_unpaid_exposure()
        top_deb = unpaid["top_10_debiteurs"][0] if unpaid["top_10_debiteurs"] else None
        lines.append(
            f"Impayés échus : {_fmt_m(unpaid['exposition_totale_xof'])} sur {unpaid['nb_factures_impayees']} factures, "
            f"dont {_fmt_m(unpaid['retard_90j_montant_xof'])} en souffrance > 90 jours."
            + (f" 1er débiteur : {top_deb['client']} ({_fmt_m(top_deb['montant_total_xof'])}, "
               f"retard max {top_deb['retard_max_jours']} j)." if top_deb else "")
        )
        lines.append(
            f"Backlog non facturé : {_fmt_m(margins['backlog_total'])} ; "
            f"reste à encaisser : {_fmt_m(margins['reste_a_encaisser'])}."
        )

    # Repli déterministe si le LLM échoue — le slot du front reste rempli.
    fallback: list[dict] = [
        {
            "sev": "bad" if pipeline["plus_un_an_pct"] >= 30 else "warn",
            "text": f"<b>{pipeline['plus_un_an_nb']} opportunités ouvertes</b> ({pipeline['plus_un_an_pct']} % du pipeline) ont plus d'un an d'ancienneté — probablement obsolètes, jamais clôturées.",
            "meta": "règle · qualité CRM",
        },
        {
            "sev": "warn" if delta_pct < 0 else "good",
            "text": f"<b>CA commandé {now_year}</b> : {_fmt_m(year['revenue_xof'])}, {delta_pct:+.1f} % vs {now_year - 1}.",
            "meta": "règle · rythme annuel",
        },
        {
            "sev": "bad" if win["taux_valeur_pct"] < 40 else "good",
            "text": f"<b>Taux de transformation</b> : {win['taux_nb_pct']} % en nombre mais {win['taux_valeur_pct']} % en valeur — les dossiers perdus sont en moyenne plus gros que les gagnés.",
            "meta": "règle · performance",
        },
    ]
    if top_clients:
        fallback.append({
            "sev": "good",
            "text": f"<b>{top_clients[0]['client']}</b> est le 1er client par CA commandé ({_fmt_m(top_clients[0]['ca_total_xof'])}).",
            "meta": "règle · top client",
        })
    return "\n".join(lines), fallback


_COLLECTORS = {
    "dashboard": _dashboard_context,
}


def _parse_llm_json(raw: str) -> list[dict]:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    data = json.loads(cleaned)
    notifications = data["notifications"]
    out = []
    for n in notifications:
        sev = n.get("sev") if n.get("sev") in ("good", "warn", "bad") else "warn"
        text = str(n.get("text", "")).strip()
        if not text:
            continue
        out.append({"sev": sev, "text": text, "meta": str(n.get("meta", "analyse IA"))})
    if not out:
        raise ValueError("aucune notification exploitable")
    return out


@router.get("/{view}")
async def get_insights(
    view: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    collector = _COLLECTORS.get(view)
    if collector is None:
        raise HTTPException(status_code=404, detail=f"Pas d'insights définis pour la vue '{view}'")

    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if not await can_access(session, role, view):
        raise HTTPException(status_code=403, detail=f"Accès refusé — rôle '{role}' non autorisé sur ce module")

    include_finance = await can_access(session, role, "tresorerie")
    cache_key = (view, include_finance)
    cached = _CACHE.get(cache_key)
    if cached and time.monotonic() - cached[1] < _CACHE_TTL:
        return cached[0]

    container = request.app.state.container
    context, fallback = await collector(container.crm_repo, include_finance)

    result: dict
    try:
        raw = await container.llm_haiku.generate(
            system=_SYSTEM,
            user=f"DONNÉES RÉELLES DU COCKPIT (vue : {view}) :\n{context}\n\nProduis le JSON de notifications.",
            max_tokens=1500,
            temperature=0.2,
        )
        result = {
            "notifications": _parse_llm_json(raw),
            "source": "ia",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # LLM indisponible / réponse invalide → repli règles
        logger.warning("Insights IA indisponibles pour '%s' (%s) — repli règles", view, exc)
        result = {
            "notifications": fallback,
            "source": "regles",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    _CACHE[cache_key] = (result, time.monotonic())
    return result
