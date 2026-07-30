"""Profil de payeur — comportement de paiement RÉEL du client débiteur.

Sans ce module, un dossier d'arbitrage ne connaît du client que son impayé
(montant, nombre de factures, retard maximum) et en tire mécaniquement la même
conclusion pour tout le monde : conditionner l'engagement commercial au
recouvrement. Or deux impayés de montant identique n'ont pas la même nature.

Ce que le module mesure, et pourquoi ce n'est pas le retard :

  Le retard maximum est un mauvais discriminant. Sur le miroir réel il vaut
  1456 j chez PORT AUTONOME D'ABIDJAN et 483 j chez BICICI — tiré dans les deux
  cas par de vieilles factures non lettrées. Comparé au délai habituel, il
  classait TOUS les dossiers en rupture de comportement, donc aucun.

  Le discriminant utile est la TENDANCE : le délai des factures récemment
  réglées contre celui des plus anciennes (cf.
  LocalCRMAdapter.get_payment_behaviour). Là, les dossiers se séparent enfin :

    BICICI              14 j → 36 j   dégradation réelle, l'impayé est un symptôme
    MTN CI             124 j → 75 j   le client paie MIEUX qu'avant
    PORT AUTONOME      244 j → aucun paiement depuis 18 mois
    ABI                 70 j → 61 j   stable, l'impayé n'indique pas de risque nouveau

  Et surtout, l'arrêt complet des paiements chez un client qui réglait
  auparavant — le signal de risque client le plus fort du miroir — n'était
  exploité par aucun module.

Tout est MESURÉ ici : délais lus sur les dates de paiement Odoo réellement
synchronisées (`invoices.payment_date`), aucune inférence, aucun LLM. Quand
l'historique est trop mince pour conclure, la classe le dit
(`historique_insuffisant`) plutôt que de produire un profil par défaut qui se
lirait comme un constat.
"""
from __future__ import annotations

# Seuils de classement du délai habituel réellement observé, en jours. Un
# payeur « rapide » l'est par rapport à une pratique de place, pas par rapport à
# son propre contrat : en Côte d'Ivoire, les délais accordés au privé (30-60 j)
# et la réalité du secteur public/parapublic (150-250 j) sont deux mondes.
DELAI_RAPIDE_MAX_JOURS = 60
DELAI_LENT_MIN_JOURS = 120

# En dessous de ce nombre de factures payées avec date de paiement connue, on
# refuse de conclure sur un comportement : trois factures ne font pas une
# habitude, et un profil affiché à tort porte plus à conséquence qu'un profil absent.
HISTORIQUE_MIN_FACTURES = 4

# Nombre minimum de paiements dans CHACUNE des deux fenêtres pour qu'une
# comparaison récent/ancien ait un sens. Sous ce seuil, la tendance n'est pas
# calculée du tout — deux factures récentes ne font pas une inflexion.
TENDANCE_MIN_PAIEMENTS = 2

# Variation du délai moyen (récent / ancien) au-delà de laquelle la tendance
# n'est plus du bruit. Asymétrique à dessein : un ralentissement mérite l'alerte
# plus vite qu'une accélération ne mérite la confiance.
#
# Le palier de vigilance existe parce qu'un seuil unique produisait un discours
# incohérent : SOCIETE GENERALE CI passe de 36 j à 52 j (ratio 1.44) et se
# retrouvait classée « rythme inchangé » juste sous la ligne, à l'écran, sous les
# chiffres qui montraient l'inverse. Entre « rien à signaler » et « rupture », il
# manquait le cran intermédiaire.
TENDANCE_DEGRADATION_RATIO = 1.5
TENDANCE_VIGILANCE_RATIO = 1.2
TENDANCE_AMELIORATION_RATIO = 0.8

# Au-delà de ce silence de paiement, un client qui réglait auparavant n'a pas
# ralenti : il s'est arrêté. Calé sur la fenêtre d'analyse (18 mois) pour rester
# cohérent avec `nb_paiements_recents`.
SILENCE_ALERTE_JOURS = 540

# Ratio du coût d'un report d'une semaine, en proportion de l'enjeu, par classe
# de payeur. Remplace le 2 % uniforme d'`aggregation.COUT_REPORT_RATIO_SEMAINE` :
# attendre une semaine sur un client stable depuis toujours ne coûte pas ce que
# coûte une semaine sur un client qui a cessé de payer. Reste une CONVENTION de
# tri (jamais un montant à provisionner), mais une convention qui distingue au
# lieu d'aplatir.
COUT_REPORT_RATIO_PAR_CLASSE = {
    "intragroupe": 0.0,
    "amelioration": 0.005,
    "stable_rapide": 0.008,
    "stable_lent": 0.01,
    "stable": 0.015,
    "vigilance": 0.025,
    "degradation": 0.035,
    "paiements_stoppes": 0.05,
    "defaillance_probable": 0.05,
    "historique_insuffisant": 0.02,
}

# Groupe Neurones — un « impayé » d'une filiale n'est pas un impayé client mais
# un compte courant intragroupe. Le présenter comme un dossier d'arbitrage
# commercial (« conditionner l'engagement au recouvrement » vis-à-vis de sa
# propre filiale burkinabè) discréditerait l'écran entier. Détection par nom :
# le miroir ne porte aucun champ de rattachement groupe.
_INTRAGROUPE_MOTIFS = ("NEURONES",)

CLASSE_LABELS = {
    "intragroupe": "entité du groupe",
    "amelioration": "paie mieux qu'avant",
    "stable_rapide": "payeur rapide et stable",
    "stable_lent": "payeur lent mais stable",
    "stable": "comportement stable",
    "vigilance": "ralentissement modéré",
    "degradation": "ralentissement marqué",
    "paiements_stoppes": "paiements arrêtés",
    "defaillance_probable": "défaillance probable",
    "historique_insuffisant": "historique insuffisant",
}

# Conséquence de la classe sur l'option recommandée. C'est une règle métier
# déterministe, jamais une sortie de LLM : le modèle rédige, il ne choisit pas
# (même garde-fou que uc_forecast/decision_client.py).
#   "echeancier"  : l'apurement se négocie, l'engagement commercial se poursuit
#   "conditionner": pas de nouvel engagement avant régularisation
#   "poursuivre"  : rien ne justifie de bloquer
RECOMMANDATION_PAR_CLASSE = {
    "intragroupe": "poursuivre",
    "amelioration": "poursuivre",
    "stable_rapide": "echeancier",
    "stable_lent": "echeancier",
    "stable": "echeancier",
    "vigilance": "echeancier",
    "degradation": "conditionner",
    "paiements_stoppes": "conditionner",
    "defaillance_probable": "conditionner",
    "historique_insuffisant": "conditionner",
}


def _is_intragroupe(client: str) -> bool:
    upper = (client or "").upper()
    return any(motif in upper for motif in _INTRAGROUPE_MOTIFS)


def build_payeur_profile(
    client: str,
    collection_stats: dict | None,
    retard_max_jours: int,
    behaviour: dict | None = None,
) -> dict:
    """Profil de payeur d'un client débiteur.

    `collection_stats` : sortie de `get_invoice_collection_stats(client)` — délai
    habituel sur tout l'historique, taux de recouvrement.
    `behaviour` : sortie de `get_payment_behaviour(client)` — la tendance
    récent/ancien, sans laquelle aucune classe autre que « historique
    insuffisant » n'est atteignable.
    `retard_max_jours` : retard COURANT le plus ancien, repris du dossier. Sert à
    qualifier l'ancienneté de la créance, PAS à classer le comportement (cf.
    docstring du module).
    """
    stats = collection_stats if isinstance(collection_stats, dict) and "error" not in collection_stats else {}
    beh = behaviour or {}
    nb_payees = int(stats.get("nb_factures_avec_date_paiement") or 0)
    delai_habituel = stats.get("delai_moyen_recouvrement_reel_jours")
    delai_accorde = stats.get("delai_moyen_accorde_jours")
    taux = stats.get("taux_recouvrement_pct")

    delai_recent = beh.get("delai_recent_jours")
    delai_ancien = beh.get("delai_ancien_jours")
    nb_recents = int(beh.get("nb_paiements_recents") or 0)
    nb_anciens = int(beh.get("nb_paiements_anciens") or 0)
    silence_jours = beh.get("jours_depuis_dernier_paiement")

    # Tendance : uniquement quand les deux fenêtres portent assez de paiements.
    # Absente, elle vaut None et ne prétend pas à 1.0 (« stable ») — l'inconnu et
    # le stable ne conduisent pas à la même décision.
    tendance_ratio = None
    if (
        delai_recent is not None and delai_ancien
        and nb_recents >= TENDANCE_MIN_PAIEMENTS
        and nb_anciens >= TENDANCE_MIN_PAIEMENTS
    ):
        tendance_ratio = round(delai_recent / delai_ancien, 2)

    classe = _classify(
        client, nb_payees, delai_habituel, taux, tendance_ratio, nb_recents, nb_anciens, silence_jours,
    )

    return {
        "classe": classe,
        "classe_label": CLASSE_LABELS[classe],
        "nature": "observé" if classe in ("historique_insuffisant", "intragroupe") else "mesuré",
        "delai_habituel_jours": delai_habituel,
        "delai_accorde_jours": delai_accorde,
        "nb_factures_payees": nb_payees,
        "taux_recouvrement_pct": taux,
        "retard_max_jours": retard_max_jours,
        # Tendance — le cœur de la lecture
        "delai_recent_jours": delai_recent,
        "delai_ancien_jours": delai_ancien,
        "nb_paiements_recents": nb_recents,
        "nb_paiements_anciens": nb_anciens,
        "tendance_ratio": tendance_ratio,
        "dernier_paiement": beh.get("dernier_paiement"),
        "jours_depuis_dernier_paiement": silence_jours,
        "fenetre_mois": beh.get("fenetre_mois"),
        "recommandation": RECOMMANDATION_PAR_CLASSE[classe],
        "cout_report_ratio_semaine": COUT_REPORT_RATIO_PAR_CLASSE[classe],
        "lecture": _lecture(client, classe, delai_habituel, delai_recent, delai_ancien,
                            nb_payees, nb_recents, taux, tendance_ratio, silence_jours, beh.get("fenetre_mois")),
    }


def _classify(
    client: str,
    nb_payees: int,
    delai_habituel: int | None,
    taux: float | None,
    tendance_ratio: float | None,
    nb_recents: int,
    nb_anciens: int,
    silence_jours: int | None,
) -> str:
    if _is_intragroupe(client):
        return "intragroupe"

    # Jamais aucun paiement alors qu'un impayé est constaté : ce n'est pas un
    # manque d'historique, c'est un historique qui ne montre aucun paiement.
    if nb_payees == 0:
        return "defaillance_probable"

    # Le client réglait, et ne règle plus du tout. Testé AVANT la tendance : sans
    # paiement récent, il n'y a pas de délai récent à comparer — la tendance est
    # muette là où le fait est le plus parlant.
    if nb_recents == 0 and nb_anciens >= TENDANCE_MIN_PAIEMENTS:
        return "paiements_stoppes"
    if silence_jours is not None and silence_jours > SILENCE_ALERTE_JOURS and nb_payees >= TENDANCE_MIN_PAIEMENTS:
        return "paiements_stoppes"

    if nb_payees < HISTORIQUE_MIN_FACTURES or not delai_habituel:
        return "historique_insuffisant"

    if tendance_ratio is not None:
        if tendance_ratio >= TENDANCE_DEGRADATION_RATIO:
            return "degradation"
        if tendance_ratio >= TENDANCE_VIGILANCE_RATIO:
            return "vigilance"
        if tendance_ratio <= TENDANCE_AMELIORATION_RATIO:
            return "amelioration"

    if delai_habituel <= DELAI_RAPIDE_MAX_JOURS:
        return "stable_rapide"
    if delai_habituel >= DELAI_LENT_MIN_JOURS:
        return "stable_lent"
    return "stable"


def _lecture(
    client: str,
    classe: str,
    delai_habituel: int | None,
    delai_recent: int | None,
    delai_ancien: int | None,
    nb_payees: int,
    nb_recents: int,
    taux: float | None,
    tendance_ratio: float | None,
    silence_jours: int | None,
    fenetre_mois: int | None,
) -> str:
    """Phrase de lecture affichée à l'écran. Rédigée ici, en Python, à partir des
    seuls chiffres mesurés — pas par le LLM : c'est un constat, pas un commentaire."""
    if classe == "intragroupe":
        return (
            f"{client} est une entité du groupe Neurones : le solde constaté relève du compte "
            "courant intragroupe, pas d'un impayé client. Aucun arbitrage commercial ne s'applique."
        )
    if classe == "defaillance_probable":
        return (
            "Aucune facture de ce client n'a jamais été encaissée dans le miroir. Ce n'est pas un "
            "manque d'historique : c'est un historique sans aucun paiement."
        )
    if classe == "paiements_stoppes":
        silence = (
            f"aucun encaissement depuis {silence_jours} jours"
            if silence_jours is not None else f"aucun encaissement sur les {fenetre_mois or 18} derniers mois"
        )
        return (
            f"Ce client a réglé {nb_payees} facture(s) par le passé"
            + (f" (à {delai_habituel} j en moyenne)" if delai_habituel else "")
            + f", puis {silence}. Il n'a pas ralenti : il s'est arrêté. C'est le signal le plus fort "
            "du dossier, et il porte davantage que le montant échu."
        )
    if classe == "historique_insuffisant":
        return (
            f"Seulement {nb_payees} facture(s) payée(s) avec date de paiement connue — trop peu pour "
            f"établir un comportement (seuil : {HISTORIQUE_MIN_FACTURES}). Le dossier se traite donc sur "
            "le seul impayé, sans lecture de rythme de paiement."
        )

    base = f"{nb_payees} facture(s) déjà encaissée(s), délai moyen {delai_habituel} j"
    if taux is not None:
        base += f" ({taux} % des factures de ce client sont payées)"
    base += "."
    tendance = ""
    if delai_recent is not None and delai_ancien:
        tendance = f" Sur les {nb_recents} règlement(s) récent(s) : {delai_ancien} j → {delai_recent} j."
    elif delai_recent is not None:
        tendance = f" Règlements récents à {delai_recent} j ({nb_recents}), sans base de comparaison antérieure."

    if classe == "degradation":
        return (
            f"{base}{tendance} Le rythme s'est dégradé de {tendance_ratio}× : l'impayé courant est le "
            "symptôme d'un ralentissement réel, pas un incident isolé. C'est le cas où conditionner "
            "l'engagement commercial se justifie sur le comportement de paiement lui-même."
        )
    if classe == "vigilance":
        return (
            f"{base}{tendance} Le rythme s'est allongé de {tendance_ratio}× — assez pour être signalé, pas "
            "assez pour constituer une rupture. Un échéancier daté vaut mieux qu'un blocage à ce stade : il "
            "traite le ralentissement sans casser la relation."
        )
    if classe == "amelioration":
        return (
            f"{base}{tendance} Ce client paie MIEUX qu'avant. L'impayé existe, mais la dynamique lui est "
            "favorable : bloquer maintenant sanctionnerait un redressement en cours."
        )
    if classe == "stable_lent":
        return (
            f"{base}{tendance} Ce client paie tard mais paie, à un rythme inchangé : son retard est "
            "structurel, non une défaillance. Conditionner l'engagement commercial reviendrait à "
            "sanctionner un comportement connu et accepté depuis le début de la relation."
        )
    if classe == "stable_rapide":
        return (
            f"{base}{tendance} Payeur rapide et régulier, rythme inchangé : l'impayé courant a toutes "
            "les chances d'être un incident de facturation ou de circuit de validation."
        )
    return (
        f"{base}{tendance} Comportement de paiement stable : rien dans la dynamique de règlement "
        "n'indique un risque nouveau, l'arbitrage se joue donc sur le montant et non sur le client."
    )


def echeancier(impaye_xof: float, profil: dict) -> dict | None:
    """Échéancier d'apurement calculé — jamais rédigé par le LLM.

    Le nombre d'échéances et l'horizon sont dérivés du rythme réellement observé
    du client : proposer 30 jours à un payeur qui n'a jamais tenu moins de 244 j
    serait un échéancier décoratif, refusé au premier appel. C'est précisément
    parce que le délai est mesuré que l'échéancier est défendable en négociation.

    Renvoie None quand aucun rythme n'est mesurable, et aussi quand un échéancier
    n'aurait pas de sens : chez un client qui a cessé de payer ou n'a jamais payé,
    un plan d'apurement n'est pas une option, c'est un vœu. Mieux vaut deux
    options honnêtes qu'une troisième fabriquée.
    """
    if profil["classe"] in (
        "intragroupe", "historique_insuffisant", "paiements_stoppes", "defaillance_probable",
    ):
        return None
    # Le rythme récent prime sur la moyenne de tout l'historique : c'est celui que
    # le client tient aujourd'hui, donc celui qu'il peut s'engager à tenir.
    delai = profil.get("delai_recent_jours") or profil.get("delai_habituel_jours")
    if not delai:
        return None

    # Horizon = le rythme observé du client, borné pour rester un plan d'apurement
    # (au-delà de ~9 mois ce n'est plus un échéancier, c'est un abandon de créance)
    # et jamais plus court que 60 j (un plan qu'aucun circuit de validation public
    # ne peut tenir n'engage personne).
    horizon = max(60, min(int(delai), 270))
    nb = 2 if horizon <= 90 else 3
    pas = round(horizon / nb)
    tranche = round(impaye_xof / nb)

    return {
        "nb_echeances": nb,
        "horizon_jours": horizon,
        "pas_jours": pas,
        "tranche_xof": tranche,
        "montant_total_xof": round(impaye_xof),
        "premiere_echeance_jours": pas,
        "delai_reference_jours": int(delai),
        # Ce qui est libéré côté commerce, et à quelle condition exacte : sans ce
        # déclencheur, l'échéancier est une concession sans contrepartie.
        "declencheur": f"engagement commercial débloqué à l'encaissement de la 1ʳᵉ échéance (J+{pas})",
        "methode": (
            f"{nb} échéances de {round(tranche / 1_000_000)} M FCFA sur {horizon} j, calibrées sur le "
            f"délai de paiement réellement observé chez ce client ({int(delai)} j) — pas sur un standard interne."
        ),
    }
