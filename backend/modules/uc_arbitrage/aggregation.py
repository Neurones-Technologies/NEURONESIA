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

from modules.uc_arbitrage import payeur

# Au-delà de ce seuil d'enjeu, aucune direction ne tranche seule (cf. mockup —
# "au-delà de 150 M, aucune direction ne tranche seule").
ENJEU_MANDAT_DG_XOF = 150_000_000

# Ancien ratio uniforme de coût du report — conservé comme repli lorsqu'aucun
# profil de payeur n'est calculable. Le ratio réellement appliqué dépend
# désormais de la classe de payeur (cf. payeur.COUT_REPORT_RATIO_PAR_CLASSE) :
# appliquer 2 % à tout le monde revenait à dire qu'attendre coûte le même prix
# chez un payeur public lent depuis toujours et chez un client qui vient de
# rompre son rythme — et c'est ce ratio qui ordonne la file de travail.
COUT_REPORT_RATIO_SEMAINE = 0.02

_TYPE_TO_ROLE = {
    "Renouvellement": "commercial",
    "Obsolescence": "commercial",
    "Cross-sell": "dir_commercial",
    "Up-sell": "dir_commercial",
}

# Nature épistémique de chaque signal — affichée à l'écran pour qu'on ne lise pas
# une inférence comme un fait comptable :
#   mesuré  : lu directement dans le miroir (montants, retards de facture)
#   observé : absence constatée dans le miroir (aucun achat dans une catégorie)
#   inféré  : déduit d'un cycle supposé (renouvellement annuel, fin de vie)
_SIGNAL_NATURE = {
    "Renouvellement": "inféré",
    "Obsolescence": "inféré",
    "Cross-sell": "observé",
    "Up-sell": "observé",
}

# Cycle supposé, en mois, pour les signaux de type renouvellement — sert à situer
# la fenêtre estimée (age_mois vs cycle), jamais présenté comme une date ferme.
_CYCLE_MOIS = {"Renouvellement": 12}


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
    collection_stats_by_client: dict[str, dict] | None = None,
    behaviour_by_client: dict[str, dict] | None = None,
) -> list[dict]:
    """Recoupe les débiteurs en retard (signal Direction Financière) avec les
    signaux commerciaux actifs sur le même client (signal DC/AM) — c'est ce
    recoupement, et lui seul, qui constitue une tension réelle à arbitrer.

    `collection_stats_by_client` / `behaviour_by_client` (optionnels) : sorties de
    `get_invoice_collection_stats` et `get_payment_behaviour` par client, qui
    donnent le comportement de paiement RÉELLEMENT observé et sa tendance. Sans
    eux, chaque dossier est instruit sur son seul impayé et reçoit donc la même
    recommandation — cf. `payeur.py` pour pourquoi c'est la principale cause de
    recommandation à côté de la plaque.
    """
    debtors = {d["client"]: d for d in unpaid_top_debiteurs if d.get("retard_max_jours", 0) > 0}
    if not debtors:
        return []
    stats_by_client = collection_stats_by_client or {}
    behaviour = behaviour_by_client or {}

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
        # Signal retenu = le plus gros montant commercial du client. C'est un choix de
        # tri, pas un jugement d'urgence ni de probabilité — d'où `signaux_*` exposés
        # ci-dessous pour que l'écran puisse le dire explicitement.
        best = max(signals, key=lambda s: s["montant_xof"])
        enjeu = float(best["montant_xof"])
        impaye = float(debt["montant_total_xof"])
        role_commercial = _TYPE_TO_ROLE.get(best["type"], "dir_commercial")
        profils = ["dir_financier", role_commercial]
        portfolio = portfolio_by_client.get(client, {})

        # Comportement de paiement mesuré du client — calcule le coût du report et
        # oriente la recommandation (cf. payeur.py). Toujours présent : quand
        # l'historique manque, le profil le dit au lieu d'être absent.
        profil_payeur = payeur.build_payeur_profile(
            client,
            stats_by_client.get(client),
            int(debt.get("retard_max_jours", 0) or 0),
            behaviour.get(client),
        )
        plan = payeur.echeancier(impaye, profil_payeur)

        dossiers.append({
            "subject_ref": client,
            "subject_label": f"{client} — {debt['nb_factures']} facture(s) échue(s) contre {best['type'].lower()} en cours",
            "profils_impliques": profils,
            "enjeu_xof": enjeu,
            "echeance": "aucune",
            # Ratio calibré sur la classe de payeur plutôt que les 2 % uniformes
            # d'origine : une semaine d'attente sur un payeur public lent depuis
            # toujours ne coûte pas ce qu'elle coûte sur une rupture de rythme.
            "cout_report_xof_semaine": round(enjeu * profil_payeur["cout_report_ratio_semaine"]),
            "mandat_role": _mandat(enjeu, profils),
            "profil_payeur": profil_payeur,
            "echeancier": plan,
            # Exposition financière RÉELLE, distincte de l'enjeu commercial ci-dessus :
            # les deux échelles étaient auparavant noyées dans le texte des positions,
            # au risque de lire l'enjeu comme le montant dû.
            "impaye_xof": impaye,
            "impaye_nb_factures": debt["nb_factures"],
            "retard_max_jours": debt["retard_max_jours"],
            # Traçabilité du signal commercial retenu
            "signal_type": best["type"],
            "signal_nature": _SIGNAL_NATURE.get(best["type"], "inféré"),
            "signaux_commerciaux_nb": len(signals),
            "signal_age_mois": best.get("age_mois"),
            "signal_cycle_mois": _CYCLE_MOIS.get(best["type"]),
            "commercial_compte": portfolio.get("salesperson"),
            "positions": [
                {
                    "role": "dir_financier",
                    "nature": "mesuré",
                    "text": f"{debt['nb_factures']} facture(s) impayée(s) pour {_m(impaye)} M FCFA, retard maximum {debt['retard_max_jours']} j.",
                },
                {
                    "role": role_commercial,
                    "nature": _SIGNAL_NATURE.get(best["type"], "inféré"),
                    "text": f"{best['type']} détecté sur {best['titre']} : {best['detail']}",
                },
            ],
            "backlog_xof": portfolio.get("backlog_xof"),
            "reste_a_encaisser_xof": portfolio.get("reste_a_encaisser_xof"),
            "signaux_portefeuille": portfolio.get("signaux", []),
        })

    for d in dossiers:
        d["priorite"] = _priorite(d)

    # Tri par priorité, plus par enjeu seul. Le tri par enjeu classait en tête les
    # plus gros montants — dont un payeur public qui règle à 243 j depuis toujours,
    # devant une rupture de rythme sur un montant moindre où la fenêtre d'action est
    # réelle. La file dit maintenant « ce qui bouge », pas « ce qui est gros » ;
    # l'enjeu reste le second critère, à priorité égale.
    return sorted(dossiers, key=lambda d: (d["priorite"]["score"], d["enjeu_xof"]), reverse=True)


# Pondération de la priorité par classe de payeur. Un dossier reste dans la file
# quelle que soit sa classe (rien n'est masqué) : c'est son RANG qui change.
_PRIORITE_POIDS = {
    "paiements_stoppes": 1.0,
    "defaillance_probable": 1.0,
    "degradation": 0.85,
    "vigilance": 0.65,
    "historique_insuffisant": 0.5,
    "stable": 0.4,
    "stable_rapide": 0.3,
    "stable_lent": 0.25,
    "amelioration": 0.15,
    "intragroupe": 0.0,
}

_PRIORITE_LABELS = {3: "à trancher maintenant", 2: "à instruire", 1: "à surveiller", 0: "hors arbitrage"}


def _priorite(dossier: dict) -> dict:
    """Priorité de traitement d'un dossier — croise le montant en jeu ET la
    fenêtre d'action réelle (le comportement du payeur), au lieu du seul montant.

    Motif : sur le miroir réel, 6 dossiers sur 7 dépassent le seuil de mandat DG.
    Une file où tout est prioritaire et tout remonte au DG ne hiérarchise plus
    rien. La priorité ne touche PAS au mandat (règle de gouvernance fondée sur le
    montant, cf. `_mandat`) : elle ordonne le travail à l'intérieur du mandat.
    """
    profil = dossier["profil_payeur"]
    poids = _PRIORITE_POIDS.get(profil["classe"], 0.5)
    # Enjeu normalisé sur le seuil de mandat DG : au-delà, le montant ne fait plus
    # varier la priorité (tout ce qui dépasse le seuil est déjà « gros »), sinon un
    # enjeu de 2 245 M écraserait à lui seul toute lecture du comportement.
    enjeu_norm = min(dossier["enjeu_xof"] / ENJEU_MANDAT_DG_XOF, 1.0)
    score = round(poids * (0.6 + 0.4 * enjeu_norm), 3)

    if profil["classe"] == "intragroupe":
        niveau = 0
    elif score >= 0.7:
        niveau = 3
    elif score >= 0.4:
        niveau = 2
    else:
        niveau = 1

    return {
        "niveau": niveau,
        "label": _PRIORITE_LABELS[niveau],
        "score": score,
        "raison": (
            f"{profil['classe_label']} · enjeu {_m(dossier['enjeu_xof'])} M FCFA"
            if niveau > 0 else "compte courant intragroupe, pas un impayé client"
        ),
    }


_ROLE_LABELS = {
    "dg": "Direction générale",
    "dir_commercial": "Direction commerciale",
    "dir_operations": "Direction des opérations",
    "dir_financier": "Direction financière",
    "commercial": "Compte (account manager)",
}


# Correspondance option recommandée → code d'option (cf.
# payeur.RECOMMANDATION_PAR_CLASSE). Le choix vient d'une règle métier
# déterministe adossée à un comportement de paiement mesuré, jamais du LLM.
_RECO_TO_CODE = {"conditionner": "A", "poursuivre": "B", "echeancier": "C"}


def build_options(dossier: dict) -> list[dict]:
    """Options d'arbitrage déterministes — le LLM n'en choisit ni ne calcule
    aucune (il ne rédige que l'option C et l'avocat du contraire, cf. narratif.py).

    Trois structures de compromis au lieu de deux : A bloque, B accepte, et C
    négocie un apurement échelonné tout en libérant le commerce sous condition.
    C n'apparaît que quand elle est calculable, c'est-à-dire quand le rythme de
    paiement du client est mesuré (`payeur.echeancier`) — un échéancier calibré
    sur un standard interne au lieu du comportement réel du client se fait
    refuser au premier appel, et n'aurait donc rien à faire dans un dossier.

    L'option recommandée n'est plus systématiquement A : elle découle de la
    classe de payeur. Recommander « conditionner » à un payeur public qui règle
    à 243 j depuis le début de la relation, c'est sanctionner un comportement
    connu et accepté — et c'est ce que faisait l'écran pour tous les dossiers.
    """
    enjeu_m = _m(dossier["enjeu_xof"])
    impaye_m = _m(dossier["impaye_xof"])
    role_financier, role_commercial = dossier["profils_impliques"][0], dossier["profils_impliques"][1]
    profil = dossier.get("profil_payeur") or {}
    plan = dossier.get("echeancier")
    reco_code = _RECO_TO_CODE.get(profil.get("recommandation", "conditionner"), "A")

    options = [
        {
            "code": "A",
            "titre": "Conditionner l'engagement commercial au recouvrement",
            "description": (
                f"Aucune nouvelle proposition ({enjeu_m} M FCFA) tant que les factures échues ne sont pas régularisées."
            ),
            "recommandee": False,
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

    if plan:
        tranche_m = _m(plan["tranche_xof"])
        options.append({
            "code": "C",
            "titre": f"Échelonner l'apurement sur {plan['horizon_jours']} j et débloquer sous condition",
            "description": (
                f"{plan['nb_echeances']} échéances de {tranche_m} M FCFA (total {impaye_m} M FCFA échus), "
                f"une tous les {plan['pas_jours']} j ; {plan['declencheur']}."
            ),
            "recommandee": False,
            "consequences": [
                {
                    "role": role_financier,
                    "text": f"Apurement daté et opposable au lieu d'un retard qui court, calibré sur le rythme réel du client ({plan['horizon_jours']} j).",
                    "variant": "s",
                },
                {
                    "role": role_commercial,
                    "text": f"Les {enjeu_m} M FCFA restent en vie, au prix d'un déblocage différé de {plan['pas_jours']} j.",
                    "variant": "w",
                },
            ],
            # Traçabilité : d'où sortent ces chiffres, pour qu'on ne les prenne pas
            # pour une proposition du modèle.
            "methode": plan["methode"],
        })

    for opt in options:
        if opt["code"] == reco_code:
            opt["recommandee"] = True
            break
    else:
        # Classe orientant vers C sans échéancier calculable : on retombe sur A
        # plutôt que de laisser un dossier sans recommandation.
        options[0]["recommandee"] = True

    return options


def missing_info(dossier: dict, contexte_terrain: str = "") -> list[dict]:
    """Ce qu'il faut vérifier avant de trancher — ce sont exactement les données
    que le miroir Odoo ne contient pas, pas une liste inventée par dossier.

    `contexte_terrain` : ce que le commercial du compte a déjà renseigné sur ce
    dossier (cf. `store.get_contexte_terrain`). Une fois le motif du retard donné,
    la ligne disparaît au lieu de rester affichée indéfiniment : demander deux
    fois la même information à celui qui l'a déjà fournie décourage la seule
    contribution humaine que l'écran attende.

    La liste s'adapte aussi au profil de payeur : chez un payeur lent mais fiable,
    ce qui manque n'est pas le motif d'un retard déjà expliqué par son rythme,
    c'est l'accord du client sur un échéancier.
    """
    owner = _ROLE_LABELS.get(dossier["profils_impliques"][1], "Compte")
    profil = dossier.get("profil_payeur") or {}
    classe = profil.get("classe", "")
    items: list[dict] = []

    if not contexte_terrain.strip():
        if classe in ("stable_lent", "stable_rapide", "stable", "amelioration"):
            items.append({
                "text": (
                    f"Confirmation que le retard relève bien du circuit de validation habituel du client "
                    f"(rythme mesuré : {profil.get('delai_habituel_jours')} j, inchangé) et non d'un litige "
                    "ouvert — le miroir ne distingue pas les deux."
                ),
                "owner": owner,
                "delay": "2 jours",
            })
        elif classe in ("degradation", "vigilance"):
            items.append({
                "text": (
                    f"Cause du ralentissement ({profil.get('delai_ancien_jours')} j → "
                    f"{profil.get('delai_recent_jours')} j) : changement d'interlocuteur, litige, difficulté "
                    "de trésorerie ? Le miroir ne peut pas le dire."
                ),
                "owner": owner,
                "delay": "48 heures",
            })
        elif classe == "paiements_stoppes":
            items.append({
                "text": (
                    f"Pourquoi ce client a-t-il cessé tout règlement "
                    f"({profil.get('jours_depuis_dernier_paiement')} j sans encaissement) ? Facture contestée, "
                    "pièce manquante, circuit bloqué de notre côté ? À vérifier avant toute décision."
                ),
                "owner": owner,
                "delay": "24 heures",
            })
        else:
            items.append({
                "text": "Motif du retard de paiement — aucune donnée du miroir ne l'explique, seul un appel client le donnerait.",
                "owner": owner,
                "delay": "2 jours",
            })

    items.append({
        "text": "Confirmation que le dossier commercial est toujours d'actualité côté client.",
        "owner": owner,
        "delay": "2 jours",
    })

    if dossier.get("echeancier"):
        items.append({
            "text": "Accord du client sur le principe d'un échéancier daté (option C) — sans son accord, l'option reste théorique.",
            "owner": owner,
            "delay": "5 jours",
        })

    return items
