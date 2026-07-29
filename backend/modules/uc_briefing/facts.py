"""Faits réels du jour, par rôle — calcul déterministe pur Python (aucun LLM
ici). Réutilise les agrégations déjà exposées par CRMRepository (les mêmes
que les endpoints /v1/dashboard/*) : chaque rôle reçoit un sous-ensemble
pertinent, jamais l'intégralité brute.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from modules.uc_arbitrage import service as arbitrage_service
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


def _action_du_jour(croisement_top, arb_top, rupture_top, position_nette_xof) -> str:
    """La décision du jour, choisie par une échelle de priorité déterministe —
    jamais par le LLM. C'est cette valeur qui occupe la 5e ligne du résumé."""
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
    return (
        f"Arbitrer aujourd'hui l'échéancier fournisseurs : {_m(abs(position_nette_xof))} M FCFA de "
        f"découvert net entre ce qui est dû et ce qui est encaissable."
    )


async def build_dg_facts(crm) -> dict:
    """Sept faits nommés, datés et seuillés — le mandat du DG est l'arbitrage
    et l'atterrissage de l'exercice, pas la lecture d'agrégats de stock sans
    contrepartie."""
    y = datetime.now().year
    arret = datetime.now().date()

    ytd, ytd_n1, rupture, margins, top_clients, exposure, arb = await asyncio.gather(
        _safe(crm.get_ytd_stats(y), None, "ytd"),
        _safe(crm.get_ytd_stats(y - 1), None, "ytd_n1"),
        _safe(
            crm.get_account_rhythm_breaks(),
            {"comptes": [], "dormants": [], "nb_comptes_rompus": 0, "nb_comptes_dormants": 0,
             "ca_annuel_historique_xof": 0.0, "ca_ytd_xof": 0.0, "impaye_cumule_xof": 0.0,
             "ca_annuel_historique_dormants_xof": 0.0},
            "rupture",
        ),
        _safe(crm.get_margin_stats(), None, "margins"),
        _safe(crm.get_top_clients(limit=10, year=y), [], "top_clients"),
        _safe(crm.get_unpaid_exposure(), None, "exposure"),
        _safe(arbitrage_service.compute_file(crm, exclude_internal=True), None, "arbitrage"),
    )

    facts: dict = {"date_arret": arret.isoformat()}
    bullets: list[str] = []
    rupture_comptes = rupture.get("comptes", [])

    # 1 — atterrissage à date comparable (remplace la comparaison YTD/année pleine)
    if ytd and ytd_n1:
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
        bullets.append(
            f"CA commandé au {_fr(arret.isoformat())} : {_m(ytd['revenue_xof'])} M FCFA contre "
            f"{_m(ytd_n1['revenue_xof'])} M FCFA à la même date en {y - 1} "
            f"({'▲' if ecart >= 0 else '▼'} {_m(abs(ecart))} M FCFA"
            + (f", {ecart_pct:+.0f}%" if ecart_pct is not None else "")
            + f"), sur {ytd['orders_count']} commandes contre {ytd_n1['orders_count']}."
        )

    # 2 — rupture de rythme des comptes majeurs (M1)
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
            f"{c['client']} silencieux depuis {c['jours_silence']} j (dernière commande le "
            f"{_fr(c['derniere_commande'])}, {_m(c['ca_annuel_moyen_xof'])} M FCFA/an historiques)"
            for c in rupture_comptes[:3]
        )
        bullets.append(
            f"{rupture['nb_comptes_rompus']} comptes majeurs en rupture de rythme : {cites} — "
            f"{_m(rupture['ca_annuel_historique_xof'])} M FCFA/an historiques réduits à "
            f"{_m(rupture['ca_ytd_xof'])} M FCFA depuis janvier."
        )

    # 3 — croisement impayé × rupture de rythme (le fait décidable)
    croises = sorted(
        (c for c in rupture_comptes if c.get("croise_impaye")),
        key=lambda c: c["impaye_xof"], reverse=True,
    )
    croisement_top = croises[0] if croises else None
    croisement_impaye = rupture.get("impaye_cumule_xof", 0)
    exposition_totale = exposure["exposition_totale_xof"] if exposure else None
    part_pct = (
        round(croisement_impaye / exposition_totale * 100, 1)
        if exposition_totale else None
    )
    facts.update({
        "croisement_nb_comptes": len(croises),
        "croisement_impaye_xof": croisement_impaye,
        "croisement_part_impaye_total_pct": part_pct,
        "croisement_top": croisement_top,
    })
    if croisement_top:
        bullets.append(
            f"{croisement_top['client']} croise les deux risques : {_m(croisement_top['impaye_xof'])} M FCFA "
            f"impayés à {croisement_top['retard_max_jours']} j de retard et {croisement_top['jours_silence']} j "
            f"sans commande. Au total {_m(croisement_impaye)} M FCFA d'impayés sur les comptes qui ont cessé "
            f"de commander" + (f", soit {part_pct:.0f}% de l'exposition." if part_pct is not None else ".")
        )

    # 4 — file d'arbitrage (le mandat du DG), hors entités du groupe
    arb_top = arb["candidats"][0] if arb and arb.get("candidats") else None
    if arb:
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
            bullets.append(
                f"File d'arbitrage : {arb['kpi']['dossiers_ouverts']} dossiers ouverts, "
                f"{arb['kpi']['enjeu_cumule_m_fcfa']} M FCFA d'enjeu, "
                f"{arb['kpi']['cout_report_m_fcfa_semaine']:.0f} M FCFA de coût par semaine de report"
                + (
                    f" — le premier est {arb_top['subject_ref']} ({_m(arb_top['enjeu_xof'])} M FCFA)."
                    if arb_top else "."
                )
            )

    # 5 — position nette de trésorerie (les deux côtés, jamais un seul)
    position_nette = None
    if margins:
        four = margins["fournisseurs_restant"]
        reste = margins["reste_a_encaisser"]
        position_nette = reste - four
        couverture = (reste / four * 100) if four else None
        facts.update({
            "fournisseurs_restant_xof": four,
            "reste_a_encaisser_xof": reste,
            "position_nette_xof": position_nette,
            "couverture_fournisseurs_pct": round(couverture, 1) if couverture is not None else None,
        })
        bullets.append(
            f"Position nette de trésorerie : {_m(four)} M FCFA dus aux fournisseurs contre "
            f"{_m(reste)} M FCFA à encaisser des clients, soit {_m(abs(position_nette))} M FCFA de "
            f"{'découvert' if position_nette < 0 else 'excédent'} structurel"
            + (f" ({couverture:.0f}% de couverture)." if couverture is not None else ".")
        )

    # 6 — concentration réelle de l'exercice (base = MÊME année que le numérateur)
    if top_clients and ytd:
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
            "concentration_seuil_pct": 50,
            "concentration_top1_client": top1["client"],
            "concentration_top1_pct": round(top1_pct, 1) if top1_pct is not None else None,
        })
        if top5_pct is not None:
            bullets.append(
                f"Concentration {y} : le top 5 pèse {top5_pct:.0f}% des {_m(base)} M FCFA commandés "
                f"(seuil de vigilance 50%), {top1['client']} premier à {top1_pct:.0f}%."
            )

    # 7 — taux de matérialisation (le seul pourcentage du miroir avec un seuil documenté)
    if margins and margins.get("ca_provisoire_total"):
        taux = margins["ca_definitif_total"] / margins["ca_provisoire_total"] * 100
        seuil = 80
        facts.update({
            "taux_materialisation_pct": round(taux, 1),
            "seuil_materialisation_pct": seuil,
            "backlog_xof": margins["backlog_total"],
        })
        bullets.append(
            f"Matérialisation du CA (définitif/provisoire) : {taux:.1f}%, "
            f"{'sous' if taux < seuil else 'au-dessus de'} le seuil d'alerte de {seuil}% — "
            f"{_m(margins['backlog_total'])} M FCFA de backlog non encore facturés."
        )

    rupture_top = rupture_comptes[0] if rupture_comptes else None
    action = _action_du_jour(croisement_top, arb_top, rupture_top, position_nette or 0)

    return {"facts": facts, "bullets": bullets, "action": action}


async def build_dir_commercial_facts(crm) -> dict:
    pipeline = await crm.get_pipeline_stats()
    opportunities = await crm.list_opportunities(limit=500)
    agg = build_pipeline_forecast(opportunities)
    scen = agg["scenarios"]
    win_rate = await crm.get_win_rate()
    lost = await crm.get_lost_deals(limit=5)
    hot_leads = await crm.get_hot_leads(limit=5)

    top_client_perdant = lost["by_client"][0] if lost["by_client"] else None
    top_lead = hot_leads[0] if hot_leads else None
    facts = {
        "pipeline_total_xof": pipeline["ca_potentiel_brut_xof"],
        "pipeline_pondere_xof": pipeline["ca_potentiel_pondéré_xof"],
        "nb_opportunites_ouvertes": scen["nb_opportunites"],
        "forecast_realiste_xof": scen["realiste_xof"],
        "forecast_pessimiste_xof": scen["pessimiste_xof"],
        "forecast_optimiste_xof": scen["optimiste_xof"],
        "taux_victoire_nb_pct": win_rate["taux_nb_pct"],
        "taux_victoire_valeur_pct": win_rate["taux_valeur_pct"],
        "nb_deals_perdus": lost["nb_total"],
        "top_client_perdant": top_client_perdant,
        "top_lead": top_lead,
    }
    bullets = [
        f"Pipeline ouvert : {_m(pipeline['ca_potentiel_brut_xof'])} M FCFA brut, "
        f"{_m(pipeline['ca_potentiel_pondéré_xof'])} M FCFA pondéré ({scen['nb_opportunites']} opportunités).",
        f"Forecast 6 mois : {_m(scen['pessimiste_xof'])} à {_m(scen['optimiste_xof'])} M FCFA "
        f"(réaliste {_m(scen['realiste_xof'])} M FCFA).",
        f"Taux de victoire : {win_rate['taux_nb_pct']}% en nombre, {win_rate['taux_valeur_pct']}% en valeur.",
    ]
    if top_client_perdant:
        bullets.append(
            f"Client concentrant le plus de pertes : {top_client_perdant['client']} "
            f"({_m(top_client_perdant['montant_xof'])} M FCFA sur {top_client_perdant['nb']} opportunités)."
        )
    if top_lead:
        bullets.append(
            f"Lead le plus chaud : {top_lead['opportunite']} ({top_lead['client']}), "
            f"{_m(top_lead['score_pondere_xof'])} M FCFA pondérés."
        )
    return {"facts": facts, "bullets": bullets}


async def build_dir_financier_facts(crm) -> dict:
    exposure = await crm.get_unpaid_exposure()
    margins = await crm.get_margin_stats()
    forecast = await crm.get_quarterly_forecast()

    top_debiteur = exposure["top_10_debiteurs"][0] if exposure["top_10_debiteurs"] else None
    proj = forecast.get("projection_fin_trimestre", {}) if forecast else {}
    facts = {
        "exposition_totale_xof": exposure["exposition_totale_xof"],
        "nb_factures_impayees": exposure["nb_factures_impayees"],
        "retard_90j_montant_xof": exposure["retard_90j_montant_xof"],
        "top_debiteur": top_debiteur,
        "marge_definitive_moyenne_pct": margins["perc_marge_definitive_moyen"],
        "reste_a_encaisser_xof": margins["reste_a_encaisser"],
        "fournisseurs_restant_xof": margins["fournisseurs_restant"],
        "forecast_trimestre": forecast.get("trimestre") if forecast else None,
        "forecast_realiste_xof": proj.get("realiste_xof"),
    }
    bullets = [
        f"Exposition totale aux impayés : {_m(exposure['exposition_totale_xof'])} M FCFA "
        f"sur {exposure['nb_factures_impayees']} factures.",
        f"Retard de plus de 90 jours : {_m(exposure['retard_90j_montant_xof'])} M FCFA.",
        f"Marge définitive moyenne : {margins['perc_marge_definitive_moyen']}%.",
        f"Reste à encaisser : {_m(margins['reste_a_encaisser'])} M FCFA. "
        f"Fournisseurs restant à payer : {_m(margins['fournisseurs_restant'])} M FCFA.",
    ]
    if top_debiteur:
        bullets.append(
            f"Plus gros débiteur : {top_debiteur['client']} "
            f"({_m(top_debiteur['montant_total_xof'])} M FCFA, {top_debiteur['retard_max_jours']} jours de retard)."
        )
    if forecast:
        bullets.append(
            f"Prévision {forecast.get('trimestre')} : {_m(proj.get('realiste_xof'))} M FCFA (scénario réaliste)."
        )
    return {"facts": facts, "bullets": bullets}


async def build_dir_operations_facts(crm) -> dict:
    margins = await crm.get_margin_stats()
    top_dossiers = await crm.get_top_margin_dossiers(limit=5, metric="marge_provisoire")

    top_dossier = top_dossiers[0] if top_dossiers else None
    facts = {
        "nb_dossiers": margins["nb_dossiers"],
        "marge_provisoire_moyenne_pct": margins["perc_marge_provisoire_moyen"],
        "marge_definitive_moyenne_pct": margins["perc_marge_definitive_moyen"],
        "backlog_total_xof": margins["backlog_total"],
        "fournisseurs_restant_xof": margins["fournisseurs_restant"],
        "top_dossier": top_dossier,
    }
    bullets = [
        f"{margins['nb_dossiers']} dossiers en base — marge provisoire moyenne "
        f"{margins['perc_marge_provisoire_moyen']}%, marge définitive moyenne {margins['perc_marge_definitive_moyen']}%.",
        f"Backlog non facturé : {_m(margins['backlog_total'])} M FCFA. "
        f"Fournisseurs restant à payer : {_m(margins['fournisseurs_restant'])} M FCFA.",
    ]
    if top_dossier:
        bullets.append(
            f"Dossier le plus margé : {top_dossier['ref']} ({top_dossier['client']}), "
            f"{_m(top_dossier['marge_provisoire'])} M FCFA de marge provisoire ({top_dossier['perc_marge_prov']}%)."
        )
    return {"facts": facts, "bullets": bullets}


async def build_commercial_facts(crm) -> dict:
    hot_leads = await crm.get_hot_leads(limit=5)
    opportunities = await crm.list_opportunities(limit=500)
    agg = build_pipeline_forecast(opportunities)
    scen = agg["scenarios"]
    win_rate = await crm.get_win_rate()

    top_lead = hot_leads[0] if hot_leads else None
    facts = {
        "nb_hot_leads": len(hot_leads),
        "top_lead": top_lead,
        "forecast_realiste_xof": scen["realiste_xof"],
        "nb_opportunites_ouvertes": scen["nb_opportunites"],
        "taux_victoire_nb_pct": win_rate["taux_nb_pct"],
    }
    bullets = [
        f"Pipeline ouvert : {scen['nb_opportunites']} opportunités, "
        f"{_m(scen['realiste_xof'])} M FCFA pondérés (scénario réaliste).",
        f"Taux de victoire en nombre : {win_rate['taux_nb_pct']}%.",
    ]
    if top_lead:
        bullets.append(
            f"Lead le plus chaud du pipeline : {top_lead['opportunite']} ({top_lead['client']}), "
            f"{_m(top_lead['score_pondere_xof'])} M FCFA pondérés, étape {top_lead['stade']}."
        )
    else:
        bullets.append("Aucun lead chaud identifié actuellement.")
    return {"facts": facts, "bullets": bullets}
