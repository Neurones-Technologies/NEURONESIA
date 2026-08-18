"""Faits réels du jour, par rôle — calcul déterministe pur Python (aucun LLM
ici). Réutilise les agrégations déjà exposées par CRMRepository (les mêmes
que les endpoints /v1/dashboard/*) : chaque rôle reçoit un sous-ensemble
pertinent, jamais l'intégralité brute.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

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


class Composition:
    """Ce que le rôle a décidé d'inclure dans son débrief (cf. uc_briefing.preferences).

    `None` — aucune préférence — signifie « tout est actif ». C'est ce qui permet
    aux appelants qui ne connaissent rien aux préférences (tests, scripts) de
    continuer à appeler `build_dg_facts(crm)` nu, et garantit qu'un déploiement
    sans ligne en base produit exactement le briefing d'avant.

    Le gating est appliqué à la SOURCE, pas sur la liste de puces en sortie :
    filtrer après coup laisserait tourner les requêtes CRM d'un élément décoché,
    et laisserait `facts` complet alors que le cockpit le lit (DgVision lit
    `facts.ca_ytd_xof`) — d'où un titre nourri d'un chiffre dont plus aucune
    puce ne parle.

    `pilote` — mode « consigne pilote » (rien de coché, consigne posée) : la
    consigne choisit le CONTENU du briefing et non plus seulement le ton. Le
    drapeau ne change RIEN au gating — l'appelant passe alors `ids=None` pour
    ouvrir tout le pool de faits — il ne sert qu'au choix du bloc de prompt en
    aval (cf. narratif._CONSIGNE_PILOTE_BLOC).
    """
    __slots__ = ("_ids", "consigne", "pilote")

    def __init__(self, ids: list[str] | None = None, consigne: str = "", pilote: bool = False):
        self._ids = None if ids is None else set(ids)
        self.consigne = consigne
        self.pilote = pilote

    def actif(self, element_id: str) -> bool:
        return self._ids is None or element_id in self._ids


# Repli de `get_account_rhythm_breaks` : sert de valeur par défaut à `_safe` ET
# de valeur d'une source non demandée. Extrait en constante depuis qu'il a deux
# usages — inline, il fallait le tenir synchronisé à la main.
_RUPTURE_VIDE: dict = {
    "comptes": [], "dormants": [], "nb_comptes_rompus": 0, "nb_comptes_dormants": 0,
    "ca_annuel_historique_xof": 0.0, "ca_ytd_xof": 0.0, "impaye_cumule_xof": 0.0,
    "ca_annuel_historique_dormants_xof": 0.0,
}

# Quels éléments ont besoin de quelle source. Une source n'est interrogée que si
# au moins un élément actif la réclame.
#
# Déclaré ici plutôt qu'inline dans le `gather` : « margins sert le bloc 5 ET le
# bloc 7 », « rupture sert 2, 3 et l'action du jour » sont des faits métier qui
# doivent se lire d'un coup d'œil, pas se reconstituer en parcourant 150 lignes
# de conditions. Une erreur ici est parfaitement silencieuse — une source
# manquante retombe sur son défaut et la puce disparaît sans un mot — d'où le
# test dédié qui compte les appels au CRM.
_DG_SOURCES: dict[str, tuple[str, ...]] = {
    "ytd": ("ca_ytd", "concentration"),
    "ytd_n1": ("ca_ytd",),
    "rupture": ("rupture_rythme", "croisement_impaye_rupture"),
    "margins": ("position_tresorerie", "taux_materialisation"),
    "top_clients": ("concentration",),
    "exposure": ("croisement_impaye_rupture",),
    "arbitrage": ("file_arbitrage",),
    "retention": ("retention_clients",),
    "fournisseurs": ("engagement_fournisseurs",),
    # Vue 360 — `margins` (toutes années) et `marge_exercice` (année en cours)
    # sont deux sources distinctes : la trésorerie se lit sur le stock complet,
    # la marge de l'exercice sur l'exercice seul.
    "pluriannuel": ("ca_pluriannuel",),
    "marge_exercice": ("marge_exercice",),
    "forecast": ("prevision_atterrissage",),
    "win_rate": ("taux_transformation",),
    "lost": ("taux_transformation",),
    "opportunites": ("echeances_affaires",),
    "collecte": ("delai_encaissement",),
    "par_commercial": ("performance_commerciaux",),
    "secteurs": ("mix_sectoriel",),
    "mensuel": ("rythme_mensuel",),
    "hot_leads": ("affaires_imminentes",),
}

_MOIS = ("", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre")


async def _ca_pluriannuel(crm, annee: int, nb: int = 5) -> list[dict]:
    """CA commandé des `nb` derniers exercices, du plus ancien au plus récent.

    Séquentiel et non `gather` : sur le miroir SQLite, le parallélisme est
    mesuré plus lent que l'enchaînement (cf. api/v1/dashboard.py), et un
    exercice en échec fait échouer toute la série — une série incomplète
    mentirait, une année absente se lisant comme une année sans ventes.
    """
    serie = []
    for a in range(annee - nb + 1, annee + 1):
        stats = await crm.get_year_stats(a)
        serie.append({"annee": a, "ca_xof": stats["revenue_xof"], "nb_commandes": stats["orders_count"]})
    return serie


async def _resoudre(sources: dict, besoins: dict[str, tuple[str, ...]], c: Composition) -> dict:
    """Interroge les sources réclamées par au moins un élément actif, en parallèle.

    Les sources écartées prennent la même valeur que si elles avaient échoué, si
    bien que le code aval (`if ytd and ytd_n1:`) n'a pas à distinguer « non
    demandé » de « indisponible » — dans les deux cas, la puce ne sort pas.

    `sources` : nom -> (fabrique de coroutine, valeur par défaut).
    """
    retenues = [nom for nom in sources if any(c.actif(e) for e in besoins[nom])]
    valeurs = await asyncio.gather(
        *(_safe(sources[nom][0](), sources[nom][1], nom) for nom in retenues)
    )
    resolues = {nom: defaut for nom, (_, defaut) in sources.items()}
    resolues.update(zip(retenues, valeurs))
    return resolues


def _action_du_jour(croisement_top, arb_top, rupture_top, position_nette_xof) -> str | None:
    """La décision du jour, choisie par une échelle de priorité déterministe —
    jamais par le LLM. C'est cette valeur qui occupe la 5e ligne du résumé.

    `None` quand aucun rang de l'échelle n'est chiffrable : le repli de dernier
    rang cite la position nette, qui n'existe pas si la trésorerie n'a pas été
    interrogée. Mieux vaut cinq constats qu'une action affirmant « 0 M FCFA de
    découvert » sur un chiffre jamais mesuré.
    """
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
    if position_nette_xof is None:
        return None
    return (
        f"Arbitrer aujourd'hui l'échéancier fournisseurs : {_m(abs(position_nette_xof))} M FCFA de "
        f"découvert net entre ce qui est dû et ce qui est encaissable."
    )


async def build_dg_facts(crm, composition: Composition | None = None) -> dict:
    """Sept faits nommés, datés et seuillés — le mandat du DG est l'arbitrage
    et l'atterrissage de l'exercice, pas la lecture d'agrégats de stock sans
    contrepartie."""
    c = composition or Composition()
    y = datetime.now().year
    arret = datetime.now().date()

    src = await _resoudre(
        {
            "ytd": (lambda: crm.get_ytd_stats(y), None),
            "ytd_n1": (lambda: crm.get_ytd_stats(y - 1), None),
            "rupture": (lambda: crm.get_account_rhythm_breaks(), _RUPTURE_VIDE),
            "margins": (lambda: crm.get_margin_stats(), None),
            "top_clients": (lambda: crm.get_top_clients(limit=10, year=y), []),
            "exposure": (lambda: crm.get_unpaid_exposure(), None),
            "arbitrage": (lambda: arbitrage_service.compute_file(crm, exclude_internal=True), None),
            "retention": (lambda: crm.get_client_retention(year=y), None),
            "fournisseurs": (lambda: crm.get_supplier_intelligence(limit=5), None),
            "pluriannuel": (lambda: _ca_pluriannuel(crm, y), []),
            "marge_exercice": (lambda: crm.get_margin_stats(year=y), None),
            "forecast": (lambda: crm.get_quarterly_forecast(), None),
            "win_rate": (lambda: crm.get_win_rate(), None),
            "lost": (lambda: crm.get_lost_deals(limit=5), None),
            "opportunites": (lambda: crm.list_opportunities(limit=500), []),
            "collecte": (lambda: crm.get_invoice_collection_stats(), None),
            "par_commercial": (lambda: crm.get_revenue_by_salesperson(year=y), []),
            "secteurs": (lambda: crm.get_revenue_by_sector(year=y, limit=10), []),
            "mensuel": (lambda: crm.get_monthly_revenue(y), []),
            "hot_leads": (lambda: crm.get_hot_leads(limit=5), []),
        },
        _DG_SOURCES,
        c,
    )
    ytd, ytd_n1, rupture = src["ytd"], src["ytd_n1"], src["rupture"]
    margins, top_clients, exposure, arb = src["margins"], src["top_clients"], src["exposure"], src["arbitrage"]
    retention, fournisseurs = src["retention"], src["fournisseurs"]

    # `date_arret` est posé hors de tout élément : le cockpit s'en sert pour dater
    # ses propres chiffres (DgVision), il ne peut pas dépendre d'une case cochée.
    facts: dict = {"date_arret": arret.isoformat()}
    bullets: list[str] = []
    rupture_comptes = rupture.get("comptes", [])

    # 1 — atterrissage à date comparable (remplace la comparaison YTD/année pleine)
    #     [élément : ca_ytd]
    if c.actif("ca_ytd") and ytd and ytd_n1:
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

    # 2 — rupture de rythme des comptes majeurs (M1)  [élément : rupture_rythme]
    if c.actif("rupture_rythme"):
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
                f"{cpt['client']} silencieux depuis {cpt['jours_silence']} j (dernière commande le "
                f"{_fr(cpt['derniere_commande'])}, {_m(cpt['ca_annuel_moyen_xof'])} M FCFA/an historiques)"
                for cpt in rupture_comptes[:3]
            )
            bullets.append(
                f"{rupture['nb_comptes_rompus']} comptes majeurs en rupture de rythme : {cites} — "
                f"{_m(rupture['ca_annuel_historique_xof'])} M FCFA/an historiques réduits à "
                f"{_m(rupture['ca_ytd_xof'])} M FCFA depuis janvier."
            )

    # 3 — croisement impayé × rupture de rythme (le fait décidable)
    #     [élément : croisement_impaye_rupture]
    croises = sorted(
        (cpt for cpt in rupture_comptes if cpt.get("croise_impaye")),
        key=lambda cpt: cpt["impaye_xof"], reverse=True,
    )
    croisement_top = croises[0] if croises else None
    croisement_impaye = rupture.get("impaye_cumule_xof", 0)
    exposition_totale = exposure["exposition_totale_xof"] if exposure else None
    part_pct = (
        round(croisement_impaye / exposition_totale * 100, 1)
        if exposition_totale else None
    )
    if c.actif("croisement_impaye_rupture"):
        facts.update({
            "croisement_nb_comptes": len(croises),
            "croisement_impaye_xof": croisement_impaye,
            "croisement_part_impaye_total_pct": part_pct,
            "croisement_top": croisement_top,
        })
    if c.actif("croisement_impaye_rupture") and croisement_top:
        bullets.append(
            f"{croisement_top['client']} croise les deux risques : {_m(croisement_top['impaye_xof'])} M FCFA "
            f"impayés à {croisement_top['retard_max_jours']} j de retard et {croisement_top['jours_silence']} j "
            f"sans commande. Au total {_m(croisement_impaye)} M FCFA d'impayés sur les comptes qui ont cessé "
            f"de commander" + (f", soit {part_pct:.0f}% de l'exposition." if part_pct is not None else ".")
        )

    # 4 — file d'arbitrage (le mandat du DG), hors entités du groupe
    #     [élément : file_arbitrage]
    arb_top = arb["candidats"][0] if arb and arb.get("candidats") else None
    if c.actif("file_arbitrage") and arb:
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
    #     [élément : position_tresorerie]
    # `position_nette` est calculée même si l'élément est décoché : c'est le repli
    # de dernier rang de l'action du jour, qui doit rester chiffrable.
    position_nette = None
    if margins:
        four = margins["fournisseurs_restant"]
        reste = margins["reste_a_encaisser"]
        position_nette = reste - four
        couverture = (reste / four * 100) if four else None
        if c.actif("position_tresorerie"):
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
    #     [élément : concentration]
    if c.actif("concentration") and top_clients and ytd:
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
    #     [élément : taux_materialisation]
    if c.actif("taux_materialisation") and margins and margins.get("ca_provisoire_total"):
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

    # 8 — rétention de la base cliente  [élément : retention_clients, décoché par défaut]
    if c.actif("retention_clients") and retention:
        facts.update({
            "retention_annee_cible": retention["annee_cible"],
            "retention_annee_reference": retention["annee_reference"],
            "retention_taux_pct": retention["taux_retention_pct"],
            "retention_nb_retenus": retention["clients_retenus"],
            "retention_nb_perdus": retention["clients_perdus_churn"],
            "retention_taux_churn_pct": retention["taux_churn_pct"],
            "retention_nb_nouveaux": retention["nouveaux_clients"],
            "retention_actifs_reference": retention["clients_actifs_annee_ref"],
        })
        bullets.append(
            f"Rétention {retention['annee_cible']} : {retention['taux_retention_pct']}% des "
            f"{retention['clients_actifs_annee_ref']} clients actifs en {retention['annee_reference']} ont "
            f"recommandé ({retention['clients_retenus']} retenus), {retention['clients_perdus_churn']} perdus "
            f"et {retention['nouveaux_clients']} nouveaux."
        )

    # 9 — engagement fournisseur  [élément : engagement_fournisseurs, décoché par défaut]
    # `get_supplier_intelligence` renvoie une LISTE triée par volume d'achat, pas
    # un agrégat : le total est recomposé ici sur les fournisseurs remontés, et la
    # puce le dit (« sur les N premiers ») plutôt que de laisser croire à un total
    # d'entreprise.
    if c.actif("engagement_fournisseurs") and fournisseurs:
        encours = [f for f in fournisseurs if f.get("encours_du_xof")]
        if encours:
            total_encours = sum(f["encours_du_xof"] for f in encours)
            top_f = max(encours, key=lambda f: f["encours_du_xof"])
            facts.update({
                "fournisseurs_encours_total_xof": total_encours,
                "fournisseurs_nb_suivis": len(fournisseurs),
                "fournisseurs_top_nom": top_f["name"],
                "fournisseurs_top_encours_xof": top_f["encours_du_xof"],
                "fournisseurs_top_dependance_pct": top_f.get("taux_dependance_pct"),
            })
            bullets.append(
                f"Engagement fournisseurs : {_m(total_encours)} M FCFA d'encours dû sur les "
                f"{len(fournisseurs)} premiers fournisseurs, {top_f['name']} en tête à "
                f"{_m(top_f['encours_du_xof'])} M FCFA"
                + (f" ({top_f['taux_dependance_pct']:.0f}% des achats)."
                   if top_f.get("taux_dependance_pct") is not None else ".")
            )

    # ── Blocs 10-19 : vue 360 du pilotage, tous décochés par défaut ──────────
    # Servent le débrief ET l'onglet cockpit « Pilotage de l'activité ».

    # 10 — trajectoire pluriannuelle  [élément : ca_pluriannuel]
    pluriannuel = src["pluriannuel"]
    if c.actif("ca_pluriannuel") and pluriannuel:
        meilleure = max(pluriannuel, key=lambda a: a["ca_xof"])
        part_meilleure = (
            pluriannuel[-1]["ca_xof"] / meilleure["ca_xof"] * 100 if meilleure["ca_xof"] else None
        )
        facts.update({
            "pluriannuel_series": pluriannuel,
            "pluriannuel_meilleure_annee": meilleure["annee"],
            "pluriannuel_meilleure_ca_xof": meilleure["ca_xof"],
            "pluriannuel_part_meilleure_pct": round(part_meilleure, 1) if part_meilleure is not None else None,
        })
        serie = ", ".join(f"{a['annee']} : {_m(a['ca_xof'])}" for a in pluriannuel)
        bullets.append(
            f"CA commandé des {len(pluriannuel)} derniers exercices (M FCFA) — {serie} ; "
            f"meilleure année {meilleure['annee']}"
            + (f", l'exercice en cours (encore incomplet) en est à {part_meilleure:.0f}%."
               if part_meilleure is not None and meilleure["annee"] != y else ".")
        )

    # 11 — marge de l'exercice  [élément : marge_exercice]
    # Source distincte de `margins` : ici l'exercice seul, là le stock complet.
    marge = src["marge_exercice"]
    if c.actif("marge_exercice") and marge and marge.get("nb_dossiers"):
        facts.update({
            "marge_annee": y,
            "marge_nb_dossiers": marge["nb_dossiers"],
            "marge_provisoire_xof": marge["marge_provisoire_total"],
            "marge_definitive_xof": marge["marge_definitive_total"],
            "marge_provisoire_moy_pct": marge["perc_marge_provisoire_moyen"],
            "marge_definitive_moy_pct": marge["perc_marge_definitive_moyen"],
        })
        bullets.append(
            f"Marge {y} : {_m(marge['marge_provisoire_total'])} M FCFA provisoires sur "
            f"{marge['nb_dossiers']} dossiers ({marge['perc_marge_provisoire_moyen']:.1f}% en moyenne), "
            f"{_m(marge['marge_definitive_total'])} M FCFA définitifs constatés "
            f"({marge['perc_marge_definitive_moyen']:.1f}%)."
        )

    # 12 — prévision d'atterrissage  [élément : prevision_atterrissage]
    forecast = src["forecast"]
    projection = (forecast or {}).get("projection_fin_trimestre", {})
    if c.actif("prevision_atterrissage") and projection.get("realiste_xof") is not None:
        facts.update({
            "atterrissage_trimestre": forecast.get("trimestre"),
            "atterrissage_realise_xof": forecast.get("realise_a_ce_jour_xof"),
            "atterrissage_realiste_xof": projection.get("realiste_xof"),
            "atterrissage_pessimiste_xof": projection.get("pessimiste_xof"),
            "atterrissage_optimiste_xof": projection.get("optimiste_xof"),
        })
        texte = f"Atterrissage {forecast.get('trimestre')} : "
        if forecast.get("realise_a_ce_jour_xof") is not None:
            texte += f"{_m(forecast['realise_a_ce_jour_xof'])} M FCFA déjà commandés, "
        texte += f"projection de fin de trimestre à {_m(projection['realiste_xof'])} M FCFA en scénario réaliste"
        if projection.get("pessimiste_xof") is not None and projection.get("optimiste_xof") is not None:
            texte += f" (fourchette {_m(projection['pessimiste_xof'])} à {_m(projection['optimiste_xof'])})"
        bullets.append(texte + ".")

    # 13 — taux de transformation  [élément : taux_transformation]
    win_rate, lost = src["win_rate"], src["lost"]
    if c.actif("taux_transformation") and win_rate:
        facts.update({
            "transformation_taux_nb_pct": win_rate["taux_nb_pct"],
            "transformation_taux_valeur_pct": win_rate["taux_valeur_pct"],
        })
        texte = (
            f"Transformation commerciale : {win_rate['taux_nb_pct']}% d'affaires gagnées en nombre, "
            f"{win_rate['taux_valeur_pct']}% en valeur"
        )
        perdant = lost["by_client"][0] if lost and lost.get("by_client") else None
        if perdant:
            facts.update({
                "transformation_nb_perdus": lost["nb_total"],
                "transformation_top_perdant": perdant,
            })
            texte += (
                f" ; {lost['nb_total']} affaires perdues, {perdant['client']} en concentre le plus "
                f"({_m(perdant['montant_xof'])} M FCFA sur {perdant['nb']})"
            )
        bullets.append(texte + ".")

    # 14 — affaires à échéance sous 60 jours  [élément : echeances_affaires]
    # Même helper que le DC : la table `contracts` étant vide, ce sont les
    # opportunités ouvertes qui portent la notion d'échéance.
    if c.actif("echeances_affaires"):
        _echeances(facts, bullets, src["opportunites"], jours=60)

    # 15 — délai d'encaissement  [élément : delai_encaissement]
    collecte = src["collecte"]
    if c.actif("delai_encaissement") and collecte and "error" not in collecte:
        delai_reel = collecte.get("delai_moyen_recouvrement_reel_jours")
        facts.update({
            "encaissement_delai_reel_jours": delai_reel,
            "encaissement_retard_impayes_jours": collecte.get("retard_moyen_impayes_jours"),
            "encaissement_taux_recouvrement_pct": collecte.get("taux_recouvrement_pct"),
            "encaissement_en_attente_xof": collecte.get("montant_en_attente_xof"),
            "encaissement_nb_souffrance": collecte.get("nb_impayes_en_souffrance"),
        })
        tete = (
            f"Encaissement : délai réel moyen de {delai_reel} j entre facture et paiement"
            if delai_reel is not None
            # L'absence de délai réel est une info de qualité de données, pas un zéro.
            else "Encaissement : délai réel non mesurable (dates de paiement non synchronisées)"
        )
        bullets.append(
            tete + f" ; {collecte.get('taux_recouvrement_pct', 0)}% des factures recouvrées, "
            f"{_m(collecte.get('montant_en_attente_xof'))} M FCFA en attente sur "
            f"{collecte.get('nb_impayes_en_souffrance', 0)} factures en souffrance "
            f"(retard moyen {collecte.get('retard_moyen_impayes_jours', 0)} j)."
        )

    # 16 — réalisé par commercial  [élément : performance_commerciaux]
    # Même helper que le DC : la table d'objectifs étant vide, la puce répartit
    # le réalisé et le dit.
    if c.actif("performance_commerciaux"):
        _couverture_objectifs(facts, bullets, src["par_commercial"], y)

    # 17 — mix sectoriel  [élément : mix_sectoriel]
    secteurs = src["secteurs"]
    if c.actif("mix_sectoriel") and secteurs:
        total_secteurs = sum(s["ca_total_xof"] for s in secteurs)
        tete_secteur = secteurs[0]
        part_secteur = (
            tete_secteur["ca_total_xof"] / total_secteurs * 100 if total_secteurs else None
        )
        facts.update({
            "secteurs_annee": y,
            "secteurs_nb": len(secteurs),
            "secteurs_ca_total_xof": total_secteurs,
            "secteurs_top": tete_secteur["secteur"],
            "secteurs_top_ca_xof": tete_secteur["ca_total_xof"],
            "secteurs_top_part_pct": round(part_secteur, 1) if part_secteur is not None else None,
        })
        # « Non renseigné » en tête n'est pas un secteur dominant, c'est un
        # défaut de qualification : la puce le dit plutôt que de l'affirmer.
        if tete_secteur["secteur"] == "Non renseigné":
            bullets.append(
                f"Mix sectoriel {y} : le premier poste est « Non renseigné »"
                + (f" ({part_secteur:.0f}% des {_m(total_secteurs)} M FCFA commandés)"
                   if part_secteur is not None else "")
                + " — la qualification sectorielle des clients reste à faire avant toute lecture."
            )
        else:
            bullets.append(
                f"Mix sectoriel {y} : {tete_secteur['secteur']} en tête à "
                f"{_m(tete_secteur['ca_total_xof'])} M FCFA"
                + (f" ({part_secteur:.0f}% des {_m(total_secteurs)} M FCFA commandés)"
                   if part_secteur is not None else "")
                + f", sur {len(secteurs)} secteurs suivis."
            )

    # 18 — rythme mensuel  [élément : rythme_mensuel]
    mensuel = src["mensuel"]
    if c.actif("rythme_mensuel") and mensuel:
        # Le mois en cours est incomplet : il n'entre dans la comparaison que
        # s'il est le seul disponible (janvier), et la moyenne reste alors la
        # sienne — jamais un « effondrement » calculé contre lui-même.
        complets = [m for m in mensuel if m["mois"] < arret.month] or mensuel
        moyenne = sum(m["ca_xof"] for m in complets) / len(complets)
        dernier = complets[-1]
        part_mois = (dernier["ca_xof"] / moyenne * 100) if moyenne else None
        facts.update({
            "mensuel_annee": y,
            "mensuel_series": mensuel,
            "mensuel_moyenne_xof": round(moyenne),
            "mensuel_dernier_mois": dernier["mois"],
            "mensuel_dernier_ca_xof": dernier["ca_xof"],
            "mensuel_dernier_vs_moyenne_pct": round(part_mois, 1) if part_mois is not None else None,
        })
        bullets.append(
            f"Rythme mensuel {y} : {_MOIS[dernier['mois']]} à {_m(dernier['ca_xof'])} M FCFA contre "
            f"une moyenne de {_m(moyenne)} M FCFA sur les mois écoulés"
            + (f" ({part_mois:.0f}% de la moyenne)." if part_mois is not None else ".")
        )

    # 19 — affaires imminentes  [élément : affaires_imminentes]
    hot = src["hot_leads"]
    if c.actif("affaires_imminentes") and hot:
        total_pondere = sum(l.get("score_pondere_xof") or 0 for l in hot)
        tete_lead = hot[0]
        facts.update({
            "imminentes_nb": len(hot),
            "imminentes_pondere_xof": total_pondere,
            "imminentes_top": tete_lead,
        })
        bullets.append(
            f"{len(hot)} affaires chaudes au pipeline pour {_m(total_pondere)} M FCFA pondérés — "
            f"la première : {tete_lead['opportunite']} ({tete_lead['client']}, "
            f"{_m(tete_lead['score_pondere_xof'])} M FCFA pondérés)."
        )

    # L'action du jour n'est PAS un élément décochable : elle est la 5e ligne
    # contractuelle du résumé (cf. narratif._SYSTEM_RESUME et _fallback_resume).
    # En revanche, ses entrées suivent les éléments actifs — une action qui cite
    # un dossier dont plus aucune puce ne parle serait indéfendable : le lecteur
    # ne saurait pas d'où elle sort. Le repli de dernier rang (échéancier
    # fournisseurs) reste toujours chiffrable.
    rupture_top = rupture_comptes[0] if rupture_comptes else None
    action = _action_du_jour(
        croisement_top if c.actif("croisement_impaye_rupture") else None,
        arb_top if c.actif("file_arbitrage") else None,
        rupture_top if c.actif("rupture_rythme") else None,
        # `None` et non `0` : une trésorerie non interrogée n'est pas une
        # trésorerie à l'équilibre (cf. _action_du_jour).
        position_nette,
    )

    return {"facts": facts, "bullets": bullets, "action": action}


# Étapes qui ferment une opportunité. `stade` est du texte libre venu d'Odoo et
# mélange deux nomenclatures (« 6-Gagné » / « Won », « 7-Perdu » / « Lost ») : on
# reconnaît donc par mot-clé, sans casse ni accent, plutôt que par égalité.
_STADES_FERMES = ("gagn", "won", "perdu", "lost", "annul", "cancel", "suspendu")


def _est_ouverte(opp: dict) -> bool:
    stade = (opp.get("stade") or "").lower()
    return not any(mot in stade for mot in _STADES_FERMES)


def _echeances(facts: dict, bullets: list[str], opportunities: list[dict], jours: int) -> None:
    """Opportunités encore ouvertes dont la date de clôture tombe dans la fenêtre.

    Comble la promesse de ROLE_FOCUS (« les renouvellements et échéances à
    venir ») que la table `contracts`, vide, ne peut pas tenir. Le filtre sur les
    étapes ouvertes est indispensable : `deadline` est renseignée sur 6401 des
    6675 opportunités, gagnées, perdues et annulées comprises.
    """
    aujourd_hui = datetime.now().date()
    limite = aujourd_hui + timedelta(days=jours)
    proches = []
    for opp in opportunities:
        brut = opp.get("deadline")
        if not brut or not _est_ouverte(opp):
            continue
        try:
            echeance = datetime.fromisoformat(str(brut)).date()
        except ValueError:
            continue
        if aujourd_hui <= echeance <= limite:
            proches.append((echeance, opp))

    facts["echeances_fenetre_jours"] = jours
    facts["echeances_nb"] = len(proches)
    if not proches:
        # Dit explicitement qu'il n'y a rien, plutôt que de laisser un trou : sur
        # un débrief, l'absence de puce se lit comme une donnée manquante.
        bullets.append(f"Aucune opportunité ouverte n'arrive à échéance dans les {jours} prochains jours.")
        return

    proches.sort(key=lambda p: p[0])
    montant = sum(o.get("revenu_attendu_xof") or 0 for _, o in proches)
    premiere, opp = proches[0]
    facts.update({
        "echeances_montant_xof": montant,
        "echeances_prochaine": {
            "opportunite": opp.get("opportunite"),
            "client": opp.get("client"),
            "deadline": premiere.isoformat(),
            "revenu_attendu_xof": opp.get("revenu_attendu_xof"),
        },
    })
    bullets.append(
        f"{len(proches)} opportunité(s) ouverte(s) à échéance sous {jours} j pour {_m(montant)} M FCFA — "
        f"la plus proche : {opp.get('opportunite')} ({opp.get('client')}) le {_fr(premiere.isoformat())}."
    )


def _couverture_objectifs(facts: dict, bullets: list[str], par_commercial: list[dict], annee: int) -> None:
    """Couverture de l'équipe commerciale, promise par ROLE_FOCUS et jamais tenue.

    ATTENTION — la table `commercial_objectives` est VIDE : il n'existe aucun
    objectif saisi. La puce ne compare donc pas à un objectif mais RÉPARTIT le
    réalisé, et le dit. Annoncer une « couverture » calculée sur un objectif
    dérivé sans le signaler reproduirait exactement le reproche que
    uc_commercial/objectifs.py documente à propos de ce briefing.
    """
    actifs = [c for c in (par_commercial or []) if c.get("ca_total_xof")]
    if not actifs:
        return
    total = sum(c["ca_total_xof"] for c in actifs)
    tete = max(actifs, key=lambda c: c["ca_total_xof"])
    part = (tete["ca_total_xof"] / total * 100) if total else None
    facts.update({
        "couverture_annee": annee,
        "couverture_nb_commerciaux": len(actifs),
        "couverture_ca_total_xof": total,
        "couverture_top_commercial": tete["commercial"],
        "couverture_top_ca_xof": tete["ca_total_xof"],
        "couverture_top_part_pct": round(part, 1) if part is not None else None,
        "couverture_objectif_saisi": False,
    })
    bullets.append(
        f"Réalisé {annee} par commercial : {_m(total)} M FCFA sur {len(actifs)} commerciaux, "
        f"{tete['commercial']} en tête à {_m(tete['ca_total_xof'])} M FCFA"
        + (f" ({part:.0f}% du total)" if part is not None else "")
        + " — aucun objectif n'étant saisi en base, c'est une répartition du réalisé, pas un taux d'atteinte."
    )


def _mix_offre(facts: dict, bullets: list[str], par_produit: list[dict], annee: int, cle: str) -> None:
    """Répartition du CA par famille d'offre. `cle` préfixe les faits, le DC et le
    DO lisant la même source pour deux lectures différentes (mix commercial /
    charge de production)."""
    lignes = [p for p in (par_produit or []) if p.get("ca_total_xof")]
    if not lignes:
        return
    total = sum(p["ca_total_xof"] for p in lignes)
    tete = lignes[0]
    part = (tete["ca_total_xof"] / total * 100) if total else None
    # Le libellé produit vient d'Odoo et contient référence + description
    # tabulées : on ne garde que la partie utile à l'oral.
    nom = str(tete["produit"]).split("\t")[0].strip()
    facts.update({
        f"{cle}_annee": annee,
        f"{cle}_nb_familles": len(lignes),
        f"{cle}_ca_total_xof": total,
        f"{cle}_top_produit": nom,
        f"{cle}_top_ca_xof": tete["ca_total_xof"],
        f"{cle}_top_part_pct": round(part, 1) if part is not None else None,
    })
    bullets.append(
        f"Mix d'offre {annee} : {_m(total)} M FCFA sur {len(lignes)} familles suivies, "
        f"{nom} en tête à {_m(tete['ca_total_xof'])} M FCFA"
        + (f" ({part:.0f}% du total)." if part is not None else ".")
    )


_DC_SOURCES: dict[str, tuple[str, ...]] = {
    "pipeline": ("pipeline_ouvert",),
    "opportunites": ("pipeline_ouvert", "forecast_scenarios", "echeances_opportunites"),
    "win_rate": ("taux_victoire",),
    "lost": ("pertes_par_client",),
    "hot_leads": ("top_lead",),
    "par_commercial": ("couverture_objectifs",),
    "par_produit": ("mix_offre",),
}


async def build_dir_commercial_facts(crm, composition: Composition | None = None) -> dict:
    c = composition or Composition()
    y = datetime.now().year

    src = await _resoudre(
        {
            "pipeline": (lambda: crm.get_pipeline_stats(), None),
            "opportunites": (lambda: crm.list_opportunities(limit=500), []),
            "win_rate": (lambda: crm.get_win_rate(), None),
            "lost": (lambda: crm.get_lost_deals(limit=5), None),
            "hot_leads": (lambda: crm.get_hot_leads(limit=5), []),
            "par_commercial": (lambda: crm.get_revenue_by_salesperson(year=y), []),
            "par_produit": (lambda: crm.get_revenue_by_product(year=y, limit=10), []),
        },
        _DC_SOURCES,
        c,
    )
    pipeline, opportunities = src["pipeline"], src["opportunites"]
    win_rate, lost, hot_leads = src["win_rate"], src["lost"], src["hot_leads"]
    scen = build_pipeline_forecast(opportunities)["scenarios"]

    facts: dict = {}
    bullets: list[str] = []

    if c.actif("pipeline_ouvert") and pipeline:
        facts.update({
            "pipeline_total_xof": pipeline["ca_potentiel_brut_xof"],
            "pipeline_pondere_xof": pipeline["ca_potentiel_pondéré_xof"],
            "nb_opportunites_ouvertes": scen["nb_opportunites"],
        })
        bullets.append(
            f"Pipeline ouvert : {_m(pipeline['ca_potentiel_brut_xof'])} M FCFA brut, "
            f"{_m(pipeline['ca_potentiel_pondéré_xof'])} M FCFA pondéré ({scen['nb_opportunites']} opportunités)."
        )

    if c.actif("forecast_scenarios") and opportunities:
        facts.update({
            "forecast_realiste_xof": scen["realiste_xof"],
            "forecast_pessimiste_xof": scen["pessimiste_xof"],
            "forecast_optimiste_xof": scen["optimiste_xof"],
        })
        bullets.append(
            f"Forecast 6 mois : {_m(scen['pessimiste_xof'])} à {_m(scen['optimiste_xof'])} M FCFA "
            f"(réaliste {_m(scen['realiste_xof'])} M FCFA)."
        )

    if c.actif("taux_victoire") and win_rate:
        facts.update({
            "taux_victoire_nb_pct": win_rate["taux_nb_pct"],
            "taux_victoire_valeur_pct": win_rate["taux_valeur_pct"],
        })
        bullets.append(
            f"Taux de victoire : {win_rate['taux_nb_pct']}% en nombre, {win_rate['taux_valeur_pct']}% en valeur."
        )

    if c.actif("pertes_par_client") and lost:
        top_client_perdant = lost["by_client"][0] if lost["by_client"] else None
        facts.update({"nb_deals_perdus": lost["nb_total"], "top_client_perdant": top_client_perdant})
        if top_client_perdant:
            bullets.append(
                f"Client concentrant le plus de pertes : {top_client_perdant['client']} "
                f"({_m(top_client_perdant['montant_xof'])} M FCFA sur {top_client_perdant['nb']} opportunités)."
            )

    if c.actif("top_lead") and hot_leads:
        facts["top_lead"] = hot_leads[0]
        bullets.append(
            f"Lead le plus chaud : {hot_leads[0]['opportunite']} ({hot_leads[0]['client']}), "
            f"{_m(hot_leads[0]['score_pondere_xof'])} M FCFA pondérés."
        )

    if c.actif("echeances_opportunites"):
        _echeances(facts, bullets, opportunities, jours=60)

    if c.actif("couverture_objectifs"):
        _couverture_objectifs(facts, bullets, src["par_commercial"], y)

    if c.actif("mix_offre"):
        _mix_offre(facts, bullets, src["par_produit"], y, cle="mix")

    return {"facts": facts, "bullets": bullets}


_DF_SOURCES: dict[str, tuple[str, ...]] = {
    "exposure": ("exposition_impayes", "retard_90j", "top_debiteur"),
    "margins": ("marge_definitive", "encaissable_vs_du", "ecart_marge_promise"),
    "forecast": ("forecast_trimestre",),
    "fournisseurs": ("echeancier_fournisseurs",),
}


async def build_dir_financier_facts(crm, composition: Composition | None = None) -> dict:
    c = composition or Composition()

    src = await _resoudre(
        {
            "exposure": (lambda: crm.get_unpaid_exposure(), None),
            "margins": (lambda: crm.get_margin_stats(), None),
            "forecast": (lambda: crm.get_quarterly_forecast(), None),
            "fournisseurs": (lambda: crm.get_supplier_intelligence(limit=10), None),
        },
        _DF_SOURCES,
        c,
    )
    exposure, margins, forecast = src["exposure"], src["margins"], src["forecast"]

    facts: dict = {}
    bullets: list[str] = []

    if c.actif("exposition_impayes") and exposure:
        facts.update({
            "exposition_totale_xof": exposure["exposition_totale_xof"],
            "nb_factures_impayees": exposure["nb_factures_impayees"],
        })
        bullets.append(
            f"Exposition totale aux impayés : {_m(exposure['exposition_totale_xof'])} M FCFA "
            f"sur {exposure['nb_factures_impayees']} factures."
        )

    if c.actif("retard_90j") and exposure:
        facts["retard_90j_montant_xof"] = exposure["retard_90j_montant_xof"]
        bullets.append(f"Retard de plus de 90 jours : {_m(exposure['retard_90j_montant_xof'])} M FCFA.")

    if c.actif("marge_definitive") and margins:
        facts["marge_definitive_moyenne_pct"] = margins["perc_marge_definitive_moyen"]
        bullets.append(f"Marge définitive moyenne : {margins['perc_marge_definitive_moyen']}%.")

    if c.actif("encaissable_vs_du") and margins:
        facts.update({
            "reste_a_encaisser_xof": margins["reste_a_encaisser"],
            "fournisseurs_restant_xof": margins["fournisseurs_restant"],
        })
        bullets.append(
            f"Reste à encaisser : {_m(margins['reste_a_encaisser'])} M FCFA. "
            f"Fournisseurs restant à payer : {_m(margins['fournisseurs_restant'])} M FCFA."
        )

    if c.actif("top_debiteur") and exposure:
        top_debiteur = exposure["top_10_debiteurs"][0] if exposure["top_10_debiteurs"] else None
        facts["top_debiteur"] = top_debiteur
        if top_debiteur:
            bullets.append(
                f"Plus gros débiteur : {top_debiteur['client']} "
                f"({_m(top_debiteur['montant_total_xof'])} M FCFA, {top_debiteur['retard_max_jours']} jours de retard)."
            )

    if c.actif("forecast_trimestre") and forecast:
        proj = forecast.get("projection_fin_trimestre", {})
        facts.update({
            "forecast_trimestre": forecast.get("trimestre"),
            "forecast_realiste_xof": proj.get("realiste_xof"),
        })
        bullets.append(
            f"Prévision {forecast.get('trimestre')} : {_m(proj.get('realiste_xof'))} M FCFA (scénario réaliste)."
        )

    # Répare ROLE_FOCUS["dir_financier"] : « la marge réelle par rapport à la
    # marge annoncée en début de dossier ».
    #
    # Les taux sont recalculés sur les TOTAUX, jamais repris de
    # `perc_marge_*_moyen` : ces deux champs sont des AVG() non pondérés sur des
    # pourcentages par dossier, et 91 dossiers à dénominateur minuscule (jusqu'à
    # -85 034 %) tirent la moyenne provisoire à -756 %. Un briefing annonçant
    # « 791 points de mieux que promis » serait faux et indéfendable.
    if c.actif("ecart_marge_promise") and margins:
        ca_prov = margins.get("ca_provisoire_total") or 0
        ca_def = margins.get("ca_definitif_total") or 0
        if ca_prov and ca_def:
            prevue = margins["marge_provisoire_total"] / ca_prov * 100
            reelle = margins["marge_definitive_total"] / ca_def * 100
            ecart = reelle - prevue
            facts.update({
                "marge_promise_pct": round(prevue, 1),
                "marge_constatee_pct": round(reelle, 1),
                "marge_ecart_points": round(ecart, 1),
            })
            bullets.append(
                f"Marge annoncée à l'ouverture {prevue:.1f}% du CA contre {reelle:.1f}% constatés à l'arrêté, "
                f"soit {abs(ecart):.1f} point(s) {'de mieux' if ecart >= 0 else 'de moins'} que promis."
            )

    if c.actif("echeancier_fournisseurs"):
        _echeancier_fournisseurs(facts, bullets, src["fournisseurs"])

    return {"facts": facts, "bullets": bullets}


def _echeancier_fournisseurs(facts: dict, bullets: list[str], fournisseurs: list[dict] | None) -> None:
    """Décaissements fournisseurs à 30/60/90 jours — la contrepartie de
    l'encaissement, que le briefing DAF ne portait pas."""
    lignes = fournisseurs or []
    if not lignes:
        return
    c30 = sum(f.get("cash_30j_xof") or 0 for f in lignes)
    c60 = sum(f.get("cash_60j_xof") or 0 for f in lignes)
    c90 = sum(f.get("cash_90j_xof") or 0 for f in lignes)
    if not (c30 or c60 or c90):
        return
    facts.update({
        "echeancier_30j_xof": c30, "echeancier_60j_xof": c60, "echeancier_90j_xof": c90,
        "echeancier_nb_fournisseurs": len(lignes),
    })
    bullets.append(
        f"Échéancier fournisseurs sur les {len(lignes)} premiers : {_m(c30)} M FCFA à 30 j, "
        f"{_m(c60)} M FCFA à 60 j, {_m(c90)} M FCFA à 90 j."
    )


_DO_SOURCES: dict[str, tuple[str, ...]] = {
    "margins": ("volume_marges", "backlog"),
    "top_dossiers": ("top_dossier_marge", "dossiers_marge_faible"),
    "par_produit": ("charge_par_practice",),
    "fournisseurs": ("fiabilite_fournisseurs", "risque_rupture_fournisseur"),
    "commandes": ("commandes_recentes",),
}


async def build_dir_operations_facts(crm, composition: Composition | None = None) -> dict:
    c = composition or Composition()
    y = datetime.now().year

    src = await _resoudre(
        {
            "margins": (lambda: crm.get_margin_stats(), None),
            "top_dossiers": (lambda: crm.get_top_margin_dossiers(limit=10, metric="marge_provisoire"), []),
            "par_produit": (lambda: crm.get_revenue_by_product(year=y, limit=10), []),
            "fournisseurs": (lambda: crm.get_supplier_intelligence(limit=10), None),
            "commandes": (lambda: crm.get_recent_orders(limit=5), []),
        },
        _DO_SOURCES,
        c,
    )
    margins, top_dossiers = src["margins"], src["top_dossiers"]

    facts: dict = {}
    bullets: list[str] = []

    if c.actif("volume_marges") and margins:
        facts.update({
            "nb_dossiers": margins["nb_dossiers"],
            "marge_provisoire_moyenne_pct": margins["perc_marge_provisoire_moyen"],
            "marge_definitive_moyenne_pct": margins["perc_marge_definitive_moyen"],
        })
        bullets.append(
            f"{margins['nb_dossiers']} dossiers en base — marge provisoire moyenne "
            f"{margins['perc_marge_provisoire_moyen']}%, marge définitive moyenne {margins['perc_marge_definitive_moyen']}%."
        )

    if c.actif("backlog") and margins:
        facts.update({
            "backlog_total_xof": margins["backlog_total"],
            "fournisseurs_restant_xof": margins["fournisseurs_restant"],
        })
        bullets.append(
            f"Backlog non facturé : {_m(margins['backlog_total'])} M FCFA. "
            f"Fournisseurs restant à payer : {_m(margins['fournisseurs_restant'])} M FCFA."
        )

    if c.actif("top_dossier_marge") and top_dossiers:
        top_dossier = top_dossiers[0]
        facts["top_dossier"] = top_dossier
        bullets.append(
            f"Dossier le plus margé : {top_dossier['ref']} ({top_dossier['client']}), "
            f"{_m(top_dossier['marge_provisoire'])} M FCFA de marge provisoire ({top_dossier['perc_marge_prov']}%)."
        )

    if c.actif("dossiers_marge_faible") and top_dossiers:
        # L'inverse du palmarès : la source est triée par marge décroissante, le
        # dernier rang est donc le plus dégradé des dossiers suivis.
        pire = min(top_dossiers, key=lambda d: d.get("perc_marge_prov") or 0)
        facts["dossier_marge_faible"] = pire
        bullets.append(
            f"Dossier à la marge la plus basse : {pire['ref']} ({pire['client']}), "
            f"{pire['perc_marge_prov']}% de marge provisoire pour {_m(pire['marge_provisoire'])} M FCFA."
        )

    # Répare ROLE_FOCUS["dir_operations"] : « la visibilité de charge par practice ».
    if c.actif("charge_par_practice"):
        _mix_offre(facts, bullets, src["par_produit"], y, cle="charge")

    if c.actif("fiabilite_fournisseurs"):
        _fiabilite_fournisseurs(facts, bullets, src["fournisseurs"])

    if c.actif("risque_rupture_fournisseur"):
        _concentration_fournisseur(facts, bullets, src["fournisseurs"])

    if c.actif("commandes_recentes") and src["commandes"]:
        recentes = src["commandes"]
        montant = sum(o.get("montant_xof") or 0 for o in recentes)
        tete = recentes[0]
        facts.update({"commandes_recentes_nb": len(recentes), "commandes_recentes_montant_xof": montant})
        bullets.append(
            f"{len(recentes)} dernières commandes entrées pour {_m(montant)} M FCFA — la plus récente : "
            f"{tete.get('client')} ({_m(tete.get('montant_xof'))} M FCFA)."
        )

    return {"facts": facts, "bullets": bullets}


def _fiabilite_fournisseurs(facts: dict, bullets: list[str], fournisseurs: list[dict] | None) -> None:
    """Retard moyen de livraison/paiement par fournisseur. Un retard négatif est
    une avance : le libellé le dit, sinon « -17 jours de retard » se lit mal."""
    lignes = [f for f in (fournisseurs or []) if f.get("retard_moyen_jours") is not None]
    if not lignes:
        return
    pire = max(lignes, key=lambda f: f["retard_moyen_jours"])
    facts.update({
        "fiabilite_nb_fournisseurs": len(lignes),
        "fiabilite_pire_fournisseur": pire["name"],
        "fiabilite_pire_retard_jours": pire["retard_moyen_jours"],
    })
    retard = pire["retard_moyen_jours"]
    bullets.append(
        f"Fiabilité fournisseurs sur {len(lignes)} suivis : {pire['name']} est le moins ponctuel avec "
        + (f"{retard:.0f} j de retard moyen." if retard > 0 else f"{abs(retard):.0f} j d'avance moyenne.")
    )


def _concentration_fournisseur(facts: dict, bullets: list[str], fournisseurs: list[dict] | None) -> None:
    """Fournisseurs sur lesquels l'engagement se concentre, et dossiers qui n'ont
    qu'une seule source d'approvisionnement."""
    lignes = [f for f in (fournisseurs or []) if f.get("taux_dependance_pct")]
    if not lignes:
        return
    tete = max(lignes, key=lambda f: f["taux_dependance_pct"])
    a_risque = sum(f.get("dossiers_a_risque_fournisseur_unique") or 0 for f in lignes)
    facts.update({
        "concentration_fournisseur_top": tete["name"],
        "concentration_fournisseur_top_pct": tete["taux_dependance_pct"],
        "concentration_dossiers_source_unique": a_risque,
    })
    bullets.append(
        f"Concentration fournisseur : {tete['name']} porte {tete['taux_dependance_pct']:.0f}% des achats"
        + (f", et {a_risque} dossier(s) dépendent d'une source unique." if a_risque else ".")
    )


_AM_SOURCES: dict[str, tuple[str, ...]] = {
    "opportunites": ("pipeline_perso", "echeances_opportunites"),
    "win_rate": ("taux_victoire_nb",),
    "hot_leads": ("top_lead",),
    "rupture": ("comptes_silencieux",),
    "exposure": ("impayes_portefeuille",),
    "lost": ("deals_perdus",),
}


async def build_commercial_facts(crm, composition: Composition | None = None) -> dict:
    """ATTENTION — périmètre : aucune de ces sources n'est filtrée par commercial.
    `get_account_rhythm_breaks` et `get_unpaid_exposure` renvoient l'entreprise
    entière. Les puces nomment donc leur périmètre et ne disent jamais « vos
    comptes » (cf. la note de uc_briefing.preferences)."""
    c = composition or Composition()

    src = await _resoudre(
        {
            "opportunites": (lambda: crm.list_opportunities(limit=500), []),
            "win_rate": (lambda: crm.get_win_rate(), None),
            "hot_leads": (lambda: crm.get_hot_leads(limit=5), []),
            "rupture": (lambda: crm.get_account_rhythm_breaks(), _RUPTURE_VIDE),
            "exposure": (lambda: crm.get_unpaid_exposure(), None),
            "lost": (lambda: crm.get_lost_deals(limit=5), None),
        },
        _AM_SOURCES,
        c,
    )
    opportunities, win_rate, hot_leads = src["opportunites"], src["win_rate"], src["hot_leads"]
    scen = build_pipeline_forecast(opportunities)["scenarios"]

    facts: dict = {}
    bullets: list[str] = []

    if c.actif("pipeline_perso") and opportunities:
        facts.update({
            "nb_opportunites_ouvertes": scen["nb_opportunites"],
            "forecast_realiste_xof": scen["realiste_xof"],
        })
        bullets.append(
            f"Pipeline ouvert : {scen['nb_opportunites']} opportunités, "
            f"{_m(scen['realiste_xof'])} M FCFA pondérés (scénario réaliste)."
        )

    if c.actif("taux_victoire_nb") and win_rate:
        facts["taux_victoire_nb_pct"] = win_rate["taux_nb_pct"]
        bullets.append(f"Taux de victoire en nombre : {win_rate['taux_nb_pct']}%.")

    if c.actif("top_lead"):
        facts["nb_hot_leads"] = len(hot_leads)
        if hot_leads:
            top_lead = hot_leads[0]
            facts["top_lead"] = top_lead
            bullets.append(
                f"Lead le plus chaud du pipeline : {top_lead['opportunite']} ({top_lead['client']}), "
                f"{_m(top_lead['score_pondere_xof'])} M FCFA pondérés, étape {top_lead['stade']}."
            )
        else:
            bullets.append("Aucun lead chaud identifié actuellement.")

    if c.actif("echeances_opportunites"):
        _echeances(facts, bullets, opportunities, jours=30)

    if c.actif("comptes_silencieux"):
        comptes = src["rupture"].get("comptes", [])
        facts["silencieux_nb_comptes"] = src["rupture"].get("nb_comptes_rompus", 0)
        if comptes:
            tete = comptes[0]
            facts["silencieux_top"] = tete
            bullets.append(
                f"{src['rupture']['nb_comptes_rompus']} comptes ont décroché sur l'ensemble du portefeuille "
                f"S2I — {tete['client']} en tête, silencieux depuis {tete['jours_silence']} j "
                f"({_m(tete['ca_annuel_moyen_xof'])} M FCFA/an historiques)."
            )

    if c.actif("impayes_portefeuille") and src["exposure"]:
        exposure = src["exposure"]
        top_debiteur = exposure["top_10_debiteurs"][0] if exposure["top_10_debiteurs"] else None
        facts["impayes_exposition_xof"] = exposure["exposition_totale_xof"]
        if top_debiteur:
            facts["impayes_top_debiteur"] = top_debiteur
            bullets.append(
                f"Impayés en cours sur le portefeuille S2I : {_m(exposure['exposition_totale_xof'])} M FCFA, "
                f"{top_debiteur['client']} en tête à {_m(top_debiteur['montant_total_xof'])} M FCFA "
                f"({top_debiteur['retard_max_jours']} j de retard)."
            )

    if c.actif("deals_perdus") and src["lost"]:
        lost = src["lost"]
        top_perdant = lost["by_client"][0] if lost["by_client"] else None
        facts["nb_deals_perdus"] = lost["nb_total"]
        if top_perdant:
            facts["top_client_perdant"] = top_perdant
            bullets.append(
                f"{lost['nb_total']} affaires perdues récemment — {top_perdant['client']} en concentre "
                f"{top_perdant['nb']} pour {_m(top_perdant['montant_xof'])} M FCFA."
            )

    return {"facts": facts, "bullets": bullets}
