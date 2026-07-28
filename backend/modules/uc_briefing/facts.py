"""Faits réels du jour, par rôle — calcul déterministe pur Python (aucun LLM
ici). Réutilise les agrégations déjà exposées par CRMRepository (les mêmes
que les endpoints /v1/dashboard/*) : chaque rôle reçoit un sous-ensemble
pertinent, jamais l'intégralité brute.
"""
from __future__ import annotations

from datetime import datetime

from modules.uc_forecast.aggregation import build_pipeline_forecast


def _m(xof: float | int | None) -> int:
    return round((xof or 0) / 1_000_000)


async def build_dg_facts(crm) -> dict:
    y = datetime.now().year
    year_stats = await crm.get_year_stats(y)
    prev_stats = await crm.get_year_stats(y - 1)
    win_rate = await crm.get_win_rate()
    open_pipeline = await crm.get_open_pipeline_stats()
    margins = await crm.get_margin_stats()
    forecast = await crm.get_quarterly_forecast()
    exposure = await crm.get_unpaid_exposure()
    lost = await crm.get_lost_deals(limit=5)

    proj = forecast.get("projection_fin_trimestre", {}) if forecast else {}
    facts = {
        "ca_annee_xof": year_stats["revenue_xof"],
        "ca_annee_precedente_xof": prev_stats["revenue_xof"],
        "taux_victoire_valeur_pct": win_rate["taux_valeur_pct"],
        "pipeline_pondere_xof": open_pipeline["ca_pondere_xof"],
        "marge_definitive_moyenne_pct": margins["perc_marge_definitive_moyen"],
        "forecast_trimestre": forecast.get("trimestre") if forecast else None,
        "forecast_realiste_xof": proj.get("realiste_xof"),
        "exposition_impayes_xof": exposure["exposition_totale_xof"],
        "nb_deals_perdus": lost["nb_total"],
        "montant_perdu_xof": lost["montant_total_xof"],
    }
    ecart = year_stats["revenue_xof"] - prev_stats["revenue_xof"]
    bullets = [
        f"CA {y} commandé : {_m(year_stats['revenue_xof'])} M FCFA "
        f"({'▲' if ecart >= 0 else '▼'} {_m(abs(ecart))} M FCFA vs {y - 1}).",
        f"Pipeline ouvert pondéré : {_m(open_pipeline['ca_pondere_xof'])} M FCFA. "
        f"Taux de victoire en valeur : {win_rate['taux_valeur_pct']}%.",
        f"Marge définitive moyenne : {margins['perc_marge_definitive_moyen']}%.",
        f"Exposition totale aux impayés : {_m(exposure['exposition_totale_xof'])} M FCFA.",
        (
            f"{lost['nb_total']} opportunités perdues au total, pour "
            f"{_m(lost['montant_total_xof'])} M FCFA."
        ),
    ]
    if forecast:
        bullets.append(
            f"Prévision {forecast.get('trimestre')} : {_m(proj.get('realiste_xof'))} M FCFA (scénario réaliste)."
        )
    return {"facts": facts, "bullets": bullets}


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
