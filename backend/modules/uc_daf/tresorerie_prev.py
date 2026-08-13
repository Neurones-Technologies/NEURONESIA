"""Tableau de bord n°3 — Trésorerie prévisionnelle : vigilance échéances et atterrissage calendaire.

Demande du DAF : « Vigilance sur les créances proches de leur échéance (alerte AVANT
échéance). Prédiction des atterrissages mensuels, sur une vue calendaire, avec
prévision des encaissements et des décaissements mois par mois. »

Le mot « avant » commande tout le premier bloc : une alerte qui se déclenche au
retard constaté arrive trop tard pour changer quoi que ce soit. La vigilance porte
donc sur les créances à échoir dans les trente jours, et le comportement de
paiement mesuré du client sert à distinguer celles qui vont probablement glisser.

Deux limites structurelles sont portées jusqu'à l'écran, parce qu'elles changent la
façon de lire le calendrier :

1. AUCUNE POSITION DE TRÉSORERIE. Le miroir ne contient aucun solde bancaire : ni
   compte, ni relevé, ni découvert autorisé. Le cumul affiché est donc une
   VARIATION de trésorerie, pas une position. Un cumul négatif ne veut pas dire
   « à découvert », il veut dire « ce mois-là consomme plus qu'il n'apporte ».

2. AUCUN ÉCHÉANCIER DE DÉCAISSEMENT. `supplier_invoices` est vide : les
   décaissements ne sont pas échéançables. Les mois révolus affichent les achats
   réellement ENGAGÉS (mesuré, mais un engagement n'est pas un paiement), les mois
   à venir une moyenne des six derniers mois. C'est un ordre de grandeur assumé,
   nommé comme tel, et le seul disponible tant que les factures fournisseurs ne
   sont pas synchronisées.

Côté encaissement, en revanche, la prévision n'est pas un gabarit : l'échéancier
des créances est réel et le décalage appliqué est le retard MOYEN CONSTATÉ du
client lui-même. C'est ce qui rend le bloc `mixte` et non `statique`.
"""
from __future__ import annotations

from datetime import date, timedelta

from modules.uc_daf import statique
from modules.uc_daf.commun import cle_mois, fin_de_mois, jour, libelle_mois, mois_suivant, pct
from modules.uc_daf.relation_commerciale import (
    SEUIL_CONTENTIEUX_JOURS,
    _ouverte,
    comportement_par_client,
)


def _retard_attendu(f: dict, comportements: dict[str, dict], retard_global: float) -> float:
    """Décalage à appliquer à une créance : retard habituel du client, sinon global.

    Le retard global n'est pas zéro : sur ce miroir, la moyenne constatée est de
    près de 45 jours. Poser zéro par défaut aurait produit un plan de trésorerie
    systématiquement en avance d'un mois et demi.
    """
    c = comportements.get(f["client_id"] or f["client"])
    if c and c["significatif"]:
        return max(0.0, c["retard_moyen_jours"])
    return max(0.0, retard_global)


# ── Vigilance sur les créances proches de l'échéance ────────────────────────

def build_vigilance(factures: list[dict], aujourdhui: date,
                    horizon_jours: int = statique.HORIZON_VIGILANCE_JOURS,
                    limit: int = 20) -> dict:
    """Créances à échoir dans l'horizon, et créances déjà échues, séparément.

    Les deux listes ne servent pas la même action : la première est une relance
    PRÉVENTIVE (appeler avant l'échéance), la seconde un recouvrement. Les fondre
    dans une seule liste triée par montant aurait noyé les trois relances utiles
    sous huit cents impayés anciens.
    """
    comportements = comportement_par_client(factures)
    retards_globaux = [
        c["retard_moyen_jours"] * c["nb_factures_reglees"] for c in comportements.values()
    ]
    nb_reglees = sum(c["nb_factures_reglees"] for c in comportements.values())
    retard_global = round(sum(retards_globaux) / nb_reglees, 1) if nb_reglees else 0.0

    limite = aujourdhui + timedelta(days=horizon_jours)
    a_echoir, echues = [], []
    for f in factures:
        if not _ouverte(f):
            continue
        echeance = jour(f["echeance"])
        if not echeance:
            continue
        c = comportements.get(f["client_id"] or f["client"])
        retard_attendu = _retard_attendu(f, comportements, retard_global)
        ligne = {
            "invoice_id": f["invoice_id"],
            "reference": f["reference"],
            "client": f["client"],
            "client_id": f["client_id"],
            "montant_xof": f["montant_xof"],
            "reste_du_xof": f["reste_du_xof"],
            "echeance": f["echeance"],
            "jours_avant_echeance": (echeance - aujourdhui).days,
            "jours_de_retard": max(0, (aujourdhui - echeance).days),
            "retard_habituel_client_jours": c["retard_moyen_jours"] if c else None,
            "comportement_significatif": bool(c and c["significatif"]),
            "nb_factures_reglees_client": c["nb_factures_reglees"] if c else 0,
            "encaissement_attendu_le": (echeance + timedelta(days=round(retard_attendu))).isoformat(),
            # Un client dont le retard habituel dépasse une semaine ne paiera pas à
            # l'échéance : c'est là que la relance préventive a de la valeur.
            "risque_glissement": bool(c and c["significatif"] and c["retard_moyen_jours"] > 7),
            "devise": f["devise"],
        }
        if echeance >= aujourdhui:
            if echeance <= limite:
                a_echoir.append(ligne)
        else:
            echues.append(ligne)

    # Les créances À ÉCHOIR se trient par date : la relance préventive se prépare
    # dans l'ordre du calendrier. Les créances ÉCHUES se trient par MONTANT : trié
    # par ancienneté, le haut de liste était occupé par des factures de 2019 à
    # quelques centaines de milliers de francs, alors que l'argent à récupérer est
    # ailleurs. L'ancienneté extrême est déjà traitée par le bloc « arriéré ».
    a_echoir.sort(key=lambda l: (l["jours_avant_echeance"], -l["reste_du_xof"]))
    echues.sort(key=lambda l: (-l["reste_du_xof"], -l["jours_de_retard"]))
    contentieux = [l for l in echues if l["jours_de_retard"] > SEUIL_CONTENTIEUX_JOURS]

    return {
        # Échéancier réel, comportement de paiement mesuré : la seule part non
        # mesurée est l'hypothèse que le passé se répète.
        "source": statique.SOURCE_MIXTE,
        "as_of": aujourdhui.isoformat(),
        "horizon_jours": horizon_jours,
        "a_echoir": a_echoir[:limit],
        "echues": echues[:limit],
        "totaux": {
            "nb_a_echoir": len(a_echoir),
            "montant_a_echoir_xof": sum(l["reste_du_xof"] for l in a_echoir),
            "nb_a_echoir_a_risque": sum(1 for l in a_echoir if l["risque_glissement"]),
            "montant_a_echoir_a_risque_xof": sum(l["reste_du_xof"] for l in a_echoir if l["risque_glissement"]),
            "nb_echues": len(echues),
            "montant_echu_xof": sum(l["reste_du_xof"] for l in echues),
            "nb_contentieux": len(contentieux),
            "montant_contentieux_xof": sum(l["reste_du_xof"] for l in contentieux),
            "retard_global_constate_jours": retard_global,
        },
        "methode": statique.METHODE_ENCAISSEMENT,
        "note": (
            "Deux listes, deux actions, deux tris. Les créances À ÉCHOIR sont classées par date : la "
            "relance préventive se prépare dans l'ordre du calendrier — c'est la demande explicite du "
            "DAF, et c'est le seul moment où l'appel change la date de règlement. Les créances ÉCHUES "
            "sont classées par MONTANT : c'est là qu'est l'argent à récupérer, l'ancienneté extrême "
            "étant traitée à part dans l'arriéré. Au-delà de "
            f"{SEUIL_CONTENTIEUX_JOURS} jours de retard, la créance relève du contentieux et non plus "
            "de la relance. Le retard habituel du client est mesuré sur ses propres factures réglées, "
            "pas estimé."
        ),
    }


# ── Atterrissage mensuel (vue calendaire) ───────────────────────────────────

def build_atterrissage(factures: list[dict], achats: list[dict], aujourdhui: date, annee: int,
                       horizon_mois: int = statique.HORIZON_ATTERRISSAGE_MOIS) -> dict:
    """Calendrier mensuel encaissement / décaissement : constaté sur le passé, projeté ensuite.

    Un mois porte quatre montants et jamais un seul : encaissement constaté,
    encaissement prévu, décaissement constaté, décaissement prévu. Les fondre en
    deux colonnes aurait mélangé du mesuré et du projeté dans la même valeur — ce
    que ce module s'interdit partout ailleurs.

    Le calendrier couvre l'exercice civil complet, plus les mois de l'horizon qui
    dépassent sur l'exercice suivant : l'atterrissage d'un exercice se joue souvent
    en janvier suivant, sur des créances de décembre.
    """
    comportements = comportement_par_client(factures)
    nb_reglees = sum(c["nb_factures_reglees"] for c in comportements.values())
    retard_global = (
        round(sum(c["retard_moyen_jours"] * c["nb_factures_reglees"] for c in comportements.values()) / nb_reglees, 1)
        if nb_reglees else 0.0
    )

    # ── Encaissements CONSTATÉS : règlements réels, par mois de règlement ──
    encaisse_constate: dict[str, dict] = {}
    for f in factures:
        reglement = jour(f["date_reglement"])
        if not reglement or f["annulee"]:
            continue
        ligne = encaisse_constate.setdefault(cle_mois(reglement), {"montant_xof": 0, "nb": 0})
        ligne["montant_xof"] += f["montant_xof"]
        ligne["nb"] += 1

    # ── Encaissements PRÉVUS : créances ouvertes, échéance décalée du retard mesuré ──
    #
    # Le point le plus délicat de ce calcul : 832 créances sur 874 ont une date de
    # règlement attendue DÉJÀ DÉPASSÉE — le client aurait dû payer, même en tenant
    # compte de son retard habituel. Les basculer sur le mois courant produisait un
    # pic de 10,8 milliards en août, soit 92 % de l'encours encaissé en un mois :
    # une prévision fausse, et fausse dans le sens qui rassure.
    #
    # Elles sont donc sorties du calendrier et regroupées en ARRIÉRÉ. Ce n'est pas
    # les oublier : leur montant est publié à côté du plan, avec son ancienneté.
    # Aucune donnée du miroir ne permet de dater le recouvrement d'un impayé de
    # trois ans, et inventer ce mois-là ne le rendrait pas plus probable.
    debut_mois_courant = date(aujourdhui.year, aujourdhui.month, 1)
    encaisse_prevu: dict[str, dict] = {}
    arriere_xof, nb_arriere, arriere_ancien_xof = 0, 0, 0
    for f in factures:
        if not _ouverte(f):
            continue
        echeance = jour(f["echeance"])
        if not echeance:
            continue
        attendu = echeance + timedelta(days=round(_retard_attendu(f, comportements, retard_global)))
        if attendu < debut_mois_courant:
            arriere_xof += f["reste_du_xof"]
            nb_arriere += 1
            if (aujourdhui - echeance).days > 2 * 365:
                arriere_ancien_xof += f["reste_du_xof"]
            continue
        # Attendu dans le mois en cours, même si la date est passée de quelques
        # jours : cet encaissement-là reste crédible sur le mois.
        ligne = encaisse_prevu.setdefault(cle_mois(max(attendu, debut_mois_courant)), {"montant_xof": 0, "nb": 0})
        ligne["montant_xof"] += f["reste_du_xof"]
        ligne["nb"] += 1

    # ── Décaissements CONSTATÉS : achats engagés, par mois d'engagement ──
    decaisse_constate: dict[str, dict] = {}
    for a in achats:
        d = jour(a["date"])
        if not d:
            continue
        ligne = decaisse_constate.setdefault(cle_mois(d), {"montant_xof": 0, "nb": 0})
        ligne["montant_xof"] += a["montant_xof"]
        ligne["nb"] += 1

    # ── Run-rate de décaissement : moyenne des N derniers mois RÉVOLUS ──
    fenetre = []
    an, mo = aujourdhui.year, aujourdhui.month
    for _ in range(statique.FENETRE_RUN_RATE_MOIS):
        mo -= 1
        if mo == 0:
            an, mo = an - 1, 12
        fenetre.append(f"{an:04d}-{mo:02d}")
    montants_fenetre = [decaisse_constate.get(cle, {}).get("montant_xof", 0) for cle in fenetre]
    run_rate = round(sum(montants_fenetre) / len(montants_fenetre)) if montants_fenetre else 0

    # ── Construction du calendrier ──
    cles = [f"{annee:04d}-{m:02d}" for m in range(1, 13)]
    an_h, mo_h = aujourdhui.year, aujourdhui.month
    for _ in range(horizon_mois):
        cle = f"{an_h:04d}-{mo_h:02d}"
        if cle not in cles:
            cles.append(cle)
        an_h, mo_h = mois_suivant(an_h, mo_h)
    cles.sort()

    # Volume de règlements par mois, pour détecter les mois dont la synchronisation
    # des encaissements est incomplète. Sans ce garde-fou, la courbe de trésorerie
    # cumulée plonge sur les deux derniers mois — non parce que rien n'est rentré,
    # mais parce que les règlements n'ont pas encore été rapatriés de l'ERP. Une
    # courbe qui chute sans le dire fait prendre une décision sur un trou de données.
    volumes = sorted(v["nb"] for v in encaisse_constate.values() if v["nb"])
    mediane_volume = volumes[len(volumes) // 2] if volumes else 0

    mois_calendrier, cumul = [], 0
    for cle in cles:
        an, mo = int(cle[:4]), int(cle[5:7])
        fin = fin_de_mois(an, mo)
        if fin < aujourdhui:
            statut = "revolu"
        elif (an, mo) == (aujourdhui.year, aujourdhui.month):
            statut = "en_cours"
        else:
            statut = "a_venir"

        enc_constate = encaisse_constate.get(cle, {}).get("montant_xof", 0)
        enc_prevu = encaisse_prevu.get(cle, {}).get("montant_xof", 0)
        dec_constate = decaisse_constate.get(cle, {}).get("montant_xof", 0)
        dec_prevu = run_rate if statut == "a_venir" else 0

        # Ce qui entre dans le solde du mois : le mesuré tant qu'il existe, le
        # projeté seulement là où rien n'a encore été constaté. Sur le mois en
        # cours les deux se cumulent — une partie est déjà encaissée, le reste est
        # attendu — et c'est la seule case où ce cumul a un sens.
        if statut == "revolu":
            encaissement, decaissement = enc_constate, dec_constate
        elif statut == "en_cours":
            encaissement, decaissement = enc_constate + enc_prevu, dec_constate
        else:
            encaissement, decaissement = enc_prevu, dec_prevu

        solde = encaissement - decaissement
        cumul += solde
        mois_calendrier.append({
            "mois": cle,
            "annee": an,
            "index_mois": mo,
            "libelle": libelle_mois(an, mo, court=True),
            "libelle_long": libelle_mois(an, mo),
            "statut": statut,
            "encaissement_constate_xof": enc_constate,
            "nb_encaissements_constates": encaisse_constate.get(cle, {}).get("nb", 0),
            "encaissement_prevu_xof": enc_prevu,
            "nb_creances_attendues": encaisse_prevu.get(cle, {}).get("nb", 0),
            "decaissement_constate_xof": dec_constate,
            "nb_achats_engages": decaisse_constate.get(cle, {}).get("nb", 0),
            "decaissement_prevu_xof": dec_prevu,
            "encaissement_retenu_xof": encaissement,
            "decaissement_retenu_xof": decaissement,
            "solde_xof": solde,
            "solde_cumule_xof": cumul,
            "alerte": solde <= statique.SEUIL_ALERTE_SOLDE_XOF,
            "source_encaissement": statique.SOURCE_REELLE if statut == "revolu" else statique.SOURCE_MIXTE,
            "source_decaissement": statique.SOURCE_REELLE if statut != "a_venir" else statique.SOURCE_STATIQUE,
            # Vrai quand le mois est révolu mais porte trop peu de règlements face à
            # l'historique : le creux est un défaut de synchronisation, pas un fait.
            "synchronisation_incomplete": bool(
                statut == "revolu"
                and mediane_volume
                and encaisse_constate.get(cle, {}).get("nb", 0) < mediane_volume * 0.30
            ),
        })

    a_venir = [m for m in mois_calendrier if m["statut"] != "revolu"]
    encours_ouvert = sum(f["reste_du_xof"] for f in factures if _ouverte(f))
    return {
        "source": statique.SOURCE_MIXTE,
        "annee": annee,
        "as_of": aujourdhui.isoformat(),
        "mois": mois_calendrier,
        "totaux": {
            "encaissement_constate_xof": sum(m["encaissement_constate_xof"] for m in mois_calendrier),
            "decaissement_constate_xof": sum(m["decaissement_constate_xof"] for m in mois_calendrier),
            "encaissement_prevu_restant_xof": sum(m["encaissement_prevu_xof"] for m in a_venir),
            "decaissement_prevu_restant_xof": sum(m["decaissement_prevu_xof"] for m in a_venir),
            "solde_prevu_restant_xof": sum(m["solde_xof"] for m in a_venir),
            "variation_cumulee_xof": mois_calendrier[-1]["solde_cumule_xof"] if mois_calendrier else 0,
            "nb_mois_en_alerte": sum(1 for m in mois_calendrier if m["alerte"]),
            "run_rate_decaissement_xof": run_rate,
            "fenetre_run_rate_mois": statique.FENETRE_RUN_RATE_MOIS,
        },
        # Arriéré : hors calendrier, publié à côté. C'est le montant que le plan de
        # trésorerie ne promet PAS d'encaisser, et le premier gisement de cash de
        # l'entreprise s'il est recouvré.
        "arriere": {
            "source": statique.SOURCE_REELLE,
            "montant_xof": arriere_xof,
            "nb_creances": nb_arriere,
            "part_encours_pct": pct(arriere_xof, encours_ouvert),
            "montant_plus_de_2_ans_xof": arriere_ancien_xof,
            "part_plus_de_2_ans_pct": pct(arriere_ancien_xof, arriere_xof),
            "lecture": (
                "Créances dont la date de règlement attendue est dépassée même en tenant compte du "
                "retard habituel du client. Elles sont exclues du calendrier : aucune donnée du "
                "système ne permet de dater leur recouvrement, et les inscrire sur un mois aurait "
                "fabriqué un encaissement qui n'arrivera pas. Ce qui dépasse deux ans relève de "
                "l'assainissement comptable — provision ou passage en perte — plus que du "
                "recouvrement."
            ),
        },
        "hypotheses": [
            statique.METHODE_ENCAISSEMENT,
            statique.RAISON_DECAISSEMENT_PROJETE,
            (
                f"Les {nb_arriere} créances attendues avant le mois en cours sont sorties du "
                "calendrier et regroupées en arriéré : les reporter sur le mois courant aurait "
                "produit un pic d'encaissement invraisemblable et rendu le plan inutilisable."
            ),
            "Aucune position de trésorerie initiale n'existe dans le système : le cumul affiché est "
            "une VARIATION de trésorerie, pas un solde bancaire. Un cumul négatif ne signifie pas "
            "un découvert.",
        ],
        "note": (
            "Chaque mois porte quatre montants distincts — encaissement constaté, encaissement prévu, "
            "décaissement constaté, décaissement prévu — pour que le mesuré et le projeté ne se "
            "confondent jamais. Les mois révolus se lisent sur le constaté, les mois à venir sur le "
            "projeté, et le mois en cours cumule les deux parce que c'est la seule case où le mois "
            "est à la fois entamé et inachevé."
        ),
    }
