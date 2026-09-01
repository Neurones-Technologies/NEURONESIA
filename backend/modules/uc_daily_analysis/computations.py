"""Les 7 narrations IA de cockpit : chiffres réels calculés en Python, texte
rédigé par Claude, jamais l'inverse.

Ce module a été extrait des routers (`api/v1/dashboard.py`,
`modules/uc_crosssell/router.py`, `modules/uc_partners/router.py`) pour que le
job quotidien et l'endpoint de secours calculent exactement la même chose : une
divergence entre les deux ferait afficher au cockpit un texte que la relance
manuelle ne saurait pas reproduire.

Chaque fonction renvoie `{"analysis", "context", "source"}` où `source` vaut :
- "llm"   : rédigé par le modèle, seul cas figé pour la journée ;
- "repli" : repli déterministe des `build_*_analysis` (modèle absent/en erreur) ;
- "vide"  : aucune donnée à commenter, message d'état sans appel modèle.
"""
from __future__ import annotations

from modules.uc_crosssell.narratif import build_crosssell_analysis
from modules.uc_crosssell.signals import get_signals
from modules.uc_dashboard.narratif import build_margins_analysis, build_trend_analysis
from modules.uc_forecast.aggregation import build_pipeline_forecast
from modules.uc_forecast.narratif import build_forecast_analysis
from modules.uc_partners.narratif import build_partners_analysis
from modules.uc_performance.narratif import build_performance_analysis
from modules.uc_tresorerie.narratif import build_tresorerie_analysis

# Clés de persistance (table daily_analyses). Les changer invalide les lignes
# déjà en base : le cockpit repasserait un jour par le calcul de secours.
KEY_TREND = "dashboard_trend"
KEY_PERFORMANCE = "performance"
KEY_FORECAST = "forecast"
KEY_MARGINS = "margins"
KEY_UNPAID = "unpaid"
KEY_CROSSSELL = "crosssell"
KEY_PARTNERS = "partners"

# Abréviations de mois du graphe CA — doivent rester identiques à MOIS_ABREV
# côté vue (frontend/src/components/views/vision/DgVision.tsx), sinon le job
# calcule la tendance sous une variante que la vue ne demandera jamais.
MOIS_ABREV = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août",
              "Sept", "Oct", "Nov", "Déc"]


def _m_fcfa(xof: float) -> int:
    return round((xof or 0) / 1_000_000)


class _LlmProbe:
    """Témoin de rédaction réelle par le modèle.

    Les `build_*_analysis` retombent silencieusement sur un repli déterministe
    quand Claude est absent ou échoue (cf. uc_dashboard/narratif.py) : le texte
    rendu est du même type dans les deux cas. Sans ce témoin, un repli produit
    pendant une indisponibilité de quelques minutes serait figé en base pour
    toute la journée.
    """

    def __init__(self, llm):
        self._llm = llm
        self.ok = False

    async def generate(self, *args, **kwargs):
        text = await self._llm.generate(*args, **kwargs)
        self.ok = bool((text or "").strip())
        return text


def _probe(llm) -> tuple[object | None, _LlmProbe | None]:
    """Renvoie (llm à passer au builder, témoin). `llm` absent → repli assumé."""
    if llm is None:
        return None, None
    probe = _LlmProbe(llm)
    return probe, probe


def _source(probe: _LlmProbe | None) -> str:
    return "llm" if probe is not None and probe.ok else "repli"


def _vide(message: str) -> dict:
    return {"analysis": message, "context": {}, "source": "vide"}


# ---------- Tendance du CA affichée (profil DG) ----------

def trend_variant(months: list[str]) -> str:
    """Variante de la courbe analysée : bornes et nombre de points.

    Volontairement indépendante des VALEURS : elles bougent à chaque sync Odoo
    (le mois en cours se remplit dans la journée), ce qui ferait tomber chaque
    affichage sur une variante inédite et donc un nouvel appel LLM — l'inverse
    de ce qu'on cherche. Deux périodes affichées différentes gardent en revanche
    deux narrations distinctes.
    """
    if not months:
        return "vide"
    return f"{months[0]}-{months[-1]}x{len(months)}"


async def trend_inputs(crm, year: int) -> tuple[list[str], list[float]]:
    """Reconstitue la courbe telle que la vue DG l'envoie (mêmes libellés, mêmes
    valeurs en M FCFA) — utilisé par le job, qui n'a pas de requête HTTP."""
    monthly = await crm.get_monthly_revenue(year)
    months = [MOIS_ABREV[m["mois"] - 1] if 1 <= m["mois"] <= 12 else str(m["mois"]) for m in monthly]
    values = [m["ca_xof"] / 1_000_000 for m in monthly]
    return months, values


async def trend_analysis(llm, months: list[str], values: list[float]) -> dict:
    if not months or not values or all(v == 0 for v in values):
        return _vide("Pas assez de données sur cette période pour une analyse de tendance.")

    debut, fin = values[0], values[-1]
    variation_pct = round((fin - debut) / debut * 100, 1) if debut else 0.0
    pic_idx = max(range(len(values)), key=lambda i: values[i])
    creux_idx = min(range(len(values)), key=lambda i: values[i])
    ctx = {
        "nb_mois": len(values),
        "periode_debut": months[0],
        "periode_fin": months[-1],
        "valeur_debut": round(debut),
        "valeur_fin": round(fin),
        "variation_pct": variation_pct,
        "mois_pic": months[pic_idx],
        "valeur_pic": round(values[pic_idx]),
        "mois_creux": months[creux_idx],
        "valeur_creux": round(values[creux_idx]),
        "moyenne_periode": round(sum(values) / len(values)),
    }
    proxy, probe = _probe(llm)
    analysis = await build_trend_analysis(proxy, ctx)
    return {"analysis": analysis, "context": ctx, "source": _source(probe)}


# ---------- Performance commerciale (profil DC) ----------

async def performance_analysis(crm, llm) -> dict:
    win_rate = await crm.get_win_rate()
    lost = await crm.get_lost_deals(limit=50)
    if lost["nb_total"] == 0:
        return _vide("Aucune opportunité perdue enregistrée — pas d'analyse de pertes possible.")

    top_client = lost["by_client"][0]
    ctx = {
        "taux_nb": win_rate["taux_nb_pct"],
        "taux_valeur": win_rate["taux_valeur_pct"],
        "nb_perdues": lost["nb_total"],
        "montant_perdu": _m_fcfa(lost["montant_total_xof"]),
        "top_client_name": top_client["client"],
        "top_client_montant": _m_fcfa(top_client["montant_xof"]),
        "top_client_nb": top_client["nb"],
    }
    proxy, probe = _probe(llm)
    analysis = await build_performance_analysis(proxy, ctx)
    return {"analysis": analysis, "context": ctx, "source": _source(probe)}


# ---------- Forecast pondéré (profil DC) ----------

async def forecast_analysis(crm, llm) -> dict:
    opportunities = await crm.list_opportunities(limit=500)
    agg = build_pipeline_forecast(opportunities)
    scen = agg["scenarios"]
    if scen["nb_opportunites"] == 0 or scen["realiste_xof"] == 0:
        return _vide(
            "Aucune opportunité pondérée dans le pipeline ouvert actuellement — "
            "pas de forecast à analyser."
        )

    top_opp = max(agg["opportunities"], key=lambda o: o["weighted_xof"])
    top_stage = agg["by_stage"][0]
    ctx = {
        "nb_opps": scen["nb_opportunites"],
        "realiste": _m_fcfa(scen["realiste_xof"]),
        "pessimiste": _m_fcfa(scen["pessimiste_xof"]),
        "optimiste": _m_fcfa(scen["optimiste_xof"]),
        "avg_prob": scen["avg_probability_pct"],
        "top_opp_name": top_opp["name"],
        "top_opp_client": top_opp["client"],
        "top_opp_share": round(top_opp["weighted_xof"] / scen["realiste_xof"] * 100),
        "top_stage_name": top_stage["stage"],
        "top_stage_share": round(top_stage["weighted_xof"] / scen["realiste_xof"] * 100),
        "top_stage_value": _m_fcfa(top_stage["weighted_xof"]),
        "ecart": _m_fcfa(scen["optimiste_xof"] - scen["pessimiste_xof"]),
    }
    proxy, probe = _probe(llm)
    analysis = await build_forecast_analysis(proxy, ctx)
    return {"analysis": analysis, "context": ctx, "source": _source(probe)}


# ---------- Marges provisoire / définitive (profils DF et DO) ----------

def margins_variant(year: int | None) -> str:
    """Exercice demandé — vide quand la vue ne filtre pas (cas des cockpits DF/DO)."""
    return str(year) if year else ""


async def margins_analysis(crm, llm, year: int | None = None) -> dict:
    stats = await crm.get_margin_stats(year=year)
    if stats["nb_dossiers"] == 0:
        return _vide("Aucun dossier avec marge calculée sur cette période.")

    top_dossiers = await crm.get_top_margin_dossiers(limit=20, year=year)
    pire = min(top_dossiers, key=lambda d: d.get("perc_marge_def", 0)) if top_dossiers else None
    taux_materialisation = (
        round(stats["ca_definitif_total"] / stats["ca_provisoire_total"] * 100, 1)
        if stats["ca_provisoire_total"] else 0
    )
    ctx = {
        "nb_dossiers": stats["nb_dossiers"],
        "backlog_m": _m_fcfa(stats["backlog_total"]),
        "taux_materialisation": taux_materialisation,
        # Ratios agrégés et non `perc_marge_*_moyen` : ces derniers moyennent des
        # pourcentages par dossier et valent -745 % sur ce miroir — le LLM
        # commentait une érosion de 780 points qui n'existe pas.
        "marge_provisoire_pct": stats["taux_marge_provisoire_pct"],
        "marge_definitive_pct": stats["taux_marge_definitive_pct"],
        # L'écart n'a de sens que si le définitif est mesurable : sous le seuil de
        # couverture il vaut None, et le gabarit doit le dire au lieu de le chiffrer.
        "marge_definitive_exploitable": stats["marge_definitive_exploitable"],
        "couverture_marge_pct": stats["couverture_marge_definitive_pct"],
        "ecart_marge_pts": (
            round(stats["taux_marge_definitive_pct"] - stats["taux_marge_provisoire_pct"], 1)
            if stats["marge_definitive_exploitable"]
            and stats["taux_marge_definitive_pct"] is not None
            and stats["taux_marge_provisoire_pct"] is not None
            else None
        ),
        "pire_dossier_ref": pire["ref"] if pire else "—",
        "pire_dossier_client": pire["client"] if pire else "—",
        "pire_dossier_marge": pire["perc_marge_def"] if pire else 0,
    }
    proxy, probe = _probe(llm)
    analysis = await build_margins_analysis(proxy, ctx)
    return {"analysis": analysis, "context": ctx, "source": _source(probe)}


# ---------- Exposition aux impayés (profil DF) ----------

async def unpaid_analysis(crm, llm) -> dict:
    exposure = await crm.get_unpaid_exposure()
    if exposure["nb_factures_impayees"] == 0:
        return _vide("Aucun impayé enregistré actuellement.")

    top3 = exposure["top_10_debiteurs"][:3]
    top1 = top3[0] if top3 else None
    ctx = {
        "exposition_totale": _m_fcfa(exposure["exposition_totale_xof"]),
        "nb_factures": exposure["nb_factures_impayees"],
        "retard_90j_montant": _m_fcfa(exposure["retard_90j_montant_xof"]),
        "retard_90j_nb": exposure["retard_90j_nb_factures"],
        "top_debiteur_client": top1["client"] if top1 else "—",
        "top_debiteur_montant": _m_fcfa(top1["montant_total_xof"]) if top1 else 0,
        "top_debiteur_jours": top1["retard_max_jours"] if top1 else 0,
        "top3_part_pct": (
            round(sum(d["montant_total_xof"] for d in top3) / exposure["exposition_totale_xof"] * 100)
            if exposure["exposition_totale_xof"] else 0
        ),
    }
    proxy, probe = _probe(llm)
    analysis = await build_tresorerie_analysis(proxy, ctx)
    return {"analysis": analysis, "context": ctx, "source": _source(probe)}


# ---------- Montée en valeur / cross-sell (profils DC et AM) ----------

async def crosssell_analysis(crm, llm) -> dict:
    signals = await get_signals(crm)

    all_signals = []
    for key, label in [
        ("renouvellement", "Renouvellement"),
        ("obsolete", "Obsolescence"),
        ("cross_sell", "Cross-sell"),
        ("up_sell", "Up-sell"),
    ]:
        for item in signals[key]:
            all_signals.append({**item, "type": label})

    if not all_signals:
        return _vide("Aucun signal de montée en valeur détecté sur les commandes actuelles.")

    top = max(all_signals, key=lambda x: x["montant_xof"])
    ctx = {
        "nb_renouvellement": len(signals["renouvellement"]),
        "nb_obsolete": len(signals["obsolete"]),
        "nb_cross_sell": len(signals["cross_sell"]),
        "nb_up_sell": len(signals["up_sell"]),
        "top_signal_type": top["type"],
        "top_signal_client": top["client"],
        "top_signal_montant": _m_fcfa(top["montant_xof"]),
        "top_signal_detail": top["detail"],
    }
    proxy, probe = _probe(llm)
    analysis = await build_crosssell_analysis(proxy, ctx)
    return {"analysis": analysis, "context": ctx, "source": _source(probe)}


# ---------- Concentration fournisseurs (profil DO) ----------

async def partners_analysis(crm, llm) -> dict:
    suppliers = await crm.get_top_suppliers(limit=50)
    if not suppliers:
        return _vide("Aucune commande fournisseur enregistrée actuellement.")

    total = sum(s["montant_total_xof"] for s in suppliers)
    top = suppliers[0]
    ctx = {
        "total_m": _m_fcfa(total),
        "nb_fournisseurs": len(suppliers),
        "top_nom": top["name"],
        "top_montant_m": _m_fcfa(top["montant_total_xof"]),
        "top_part_pct": round(top["montant_total_xof"] / total * 100) if total else 0,
        "top_nb_commandes": top["nb_commandes"],
        "top_derniere_commande": top["derniere_commande"] or "non renseignée",
    }
    proxy, probe = _probe(llm)
    analysis = await build_partners_analysis(proxy, ctx)
    return {"analysis": analysis, "context": ctx, "source": _source(probe)}
