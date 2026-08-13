"""Tableau de bord n°2 — Relation commerciale : créances (DSO), dettes (DPO), mauvais payeurs.

Demande du DAF : « Point sur les créances : DSO. Point sur les dettes : DPO. Suivi
des mauvais clients (retard de paiement). »

Les trois demandes n'ont pas du tout le même degré de faisabilité, et c'est ce que
cet écran doit rendre évident :

1. DSO : MESURÉ, et de deux façons qui ne disent pas la même chose. Le miroir porte
   2 045 factures réglées avec leur date de règlement réelle : le délai
   d'encaissement constaté est un calcul. Mais l'encours rapporté au chiffre
   d'affaires — la lecture bilancielle — donne un tout autre nombre, parce qu'il
   inclut un stock d'impayés anciens que les factures réglées, par construction,
   ne montrent pas. Les deux sont servis, nommés séparément : présenter un seul
   « DSO » ferait passer un problème de recouvrement pour un délai de paiement.

2. MAUVAIS PAYEURS : MESURÉ. Deux signaux distincts sont croisés — le comportement
   passé (retard moyen sur les factures déjà réglées) et l'exposition présente
   (retard courant sur l'encours). Un client peut être lent et à jour, ou ponctuel
   et bloqué sur une facture : les confondre enverrait la mauvaise relance.

3. DPO : NON MESURABLE. `supplier_invoices` est vide — aucune facture fournisseur
   n'est synchronisée. Sans facture, il n'y a ni échéance ni règlement : le DPO
   n'est pas approximable. Ce qui est mesuré à la place, et nommé comme tel, ce
   sont les achats ENGAGÉS. Une commande passée n'est pas une dette échue.

Le module est écrit pour basculer sans changer de forme : `build_dpo` calcule un
DPO réel dès que des factures fournisseurs existent, et ne sert le gabarit que
tant qu'il n'y en a aucune.
"""
from __future__ import annotations

from datetime import date

from modules.uc_daf import statique
from modules.uc_daf.commun import cle_mois, jour, libelle_mois, pct

# Nombre minimal de factures réglées en dessous duquel le retard moyen d'un client
# n'est pas jugé significatif. Même principe que `MIN_CLOSES_POUR_TAUX` du DC : un
# retard de 200 jours sur une facture unique est un incident, pas un comportement.
MIN_FACTURES_COMPORTEMENT = 3

# Plafond de normalisation des retards dans l'indice de risque. Au-delà de six
# mois, le retard ne discrimine plus : un impayé de 200 jours et un de 600 jours
# relèvent tous deux du contentieux, pas du recouvrement.
PLAFOND_RETARD_JOURS = 180

# Seuil au-delà duquel une créance échue sort du recouvrement amiable. Repris de
# la lecture déjà tenue dans le cockpit financier (bloc « au-delà de 90 jours »).
SEUIL_CONTENTIEUX_JOURS = 90

TRANCHES_AGE = [
    ("non_echu", "Non échu", None, 0),
    ("0_30", "Échu de 1 à 30 jours", 1, 30),
    ("31_60", "Échu de 31 à 60 jours", 31, 60),
    ("61_90", "Échu de 61 à 90 jours", 61, 90),
    ("90_plus", "Échu depuis plus de 90 jours", 91, None),
]


def _mediane(valeurs: list[float]) -> float | None:
    if not valeurs:
        return None
    tri = sorted(valeurs)
    milieu = len(tri) // 2
    if len(tri) % 2:
        return round(tri[milieu], 1)
    return round((tri[milieu - 1] + tri[milieu]) / 2, 1)


def _ouverte(f: dict) -> bool:
    """Créance réellement due : reste dû strictement positif et facture non annulée.

    Le statut ne suffit pas : une facture « pending » soldée par un règlement
    partiel garde son statut mais n'a plus de reste dû.
    """
    return not f["annulee"] and f["reste_du_xof"] > 0


def comportement_par_client(factures: list[dict]) -> dict[str, dict]:
    """Retard moyen constaté par client, sur ses factures déjà réglées.

    Sert deux écrans : le suivi des mauvais payeurs (qui l'affiche) et la prévision
    d'encaissement (qui décale chaque créance de ce retard). Le calcul est ici, une
    seule fois, parce que deux définitions divergentes du « retard habituel » d'un
    client produiraient un mauvais payeur classé rouge sur un écran et une
    prévision d'encaissement optimiste sur l'autre.

    `significatif` reste faux sous `MIN_FACTURES_COMPORTEMENT` factures réglées : le
    retard est alors renseigné mais l'appelant est censé retomber sur le retard
    global observé, pas extrapoler un incident isolé.
    """
    par_client: dict[str, dict] = {}
    for f in factures:
        if f["annulee"] or not f["date_reglement"]:
            continue
        reglement, echeance = jour(f["date_reglement"]), jour(f["echeance"])
        if not reglement or not echeance:
            continue
        cle = f["client_id"] or f["client"]
        c = par_client.setdefault(cle, {"client": f["client"], "retards": []})
        c["retards"].append((reglement - echeance).days)

    return {
        cle: {
            "client": c["client"],
            "nb_factures_reglees": len(c["retards"]),
            "retard_moyen_jours": round(sum(c["retards"]) / len(c["retards"]), 1),
            "retard_median_jours": _mediane(c["retards"]),
            "significatif": len(c["retards"]) >= MIN_FACTURES_COMPORTEMENT,
        }
        for cle, c in par_client.items()
    }


# ── Socle mesuré, partagé par les trois tableaux de bord ─────────────────────

def mesurer_creances(factures: list[dict], aujourdhui: date, ca_exercice_xof: int,
                     jours_exercice_ecoules: int) -> dict:
    """Agrégats de créances mesurés — socle commun au budget, au DSO et à la trésorerie.

    Calculé une fois et partagé : le taux de recouvrement qui pèse dans l'indice de
    performance et celui qu'affiche l'écran des créances doivent être le MÊME
    nombre, sans quoi deux écrans du même cockpit se contredisent.
    """
    ouvertes = [f for f in factures if _ouverte(f)]
    reglees = [f for f in factures if f["date_reglement"] and not f["annulee"]]

    encours_xof = sum(f["reste_du_xof"] for f in ouvertes)
    echues, a_echoir = [], []
    for f in ouvertes:
        echeance = jour(f["echeance"])
        (echues if echeance and echeance < aujourdhui else a_echoir).append(f)

    encours_echu_xof = sum(f["reste_du_xof"] for f in echues)
    contentieux = [
        f for f in echues
        if (jour(f["echeance"]) and (aujourdhui - jour(f["echeance"])).days > SEUIL_CONTENTIEUX_JOURS)
    ]

    # Délais mesurés sur les factures réglées. Deux mesures distinctes, jamais
    # fondues : le délai d'encaissement se compte depuis la FACTURE, le retard se
    # compte depuis l'ÉCHÉANCE. Confondre les deux fait disparaître le délai
    # contractuel accordé au client.
    delais, retards = [], []
    for f in reglees:
        reglement, facture, echeance = jour(f["date_reglement"]), jour(f["date_facture"]), jour(f["echeance"])
        if reglement and facture:
            delais.append((reglement - facture).days)
        if reglement and echeance:
            retards.append((reglement - echeance).days)

    montant_regle_xof = sum(f["montant_xof"] for f in reglees)
    # Recouvrement = ce qui est rentré rapporté à ce qui aurait dû être rentré
    # (réglé + encours ÉCHU). L'encours non encore échu est volontairement exclu :
    # il n'est pas en retard, l'y inclure ferait baisser le taux sans faute.
    taux_recouvrement_pct = pct(montant_regle_xof, montant_regle_xof + encours_echu_xof)

    return {
        "encours_xof": encours_xof,
        "nb_factures_ouvertes": len(ouvertes),
        "encours_echu_xof": encours_echu_xof,
        "nb_factures_echues": len(echues),
        "encours_a_echoir_xof": sum(f["reste_du_xof"] for f in a_echoir),
        "nb_factures_a_echoir": len(a_echoir),
        "encours_contentieux_xof": sum(f["reste_du_xof"] for f in contentieux),
        "nb_factures_contentieux": len(contentieux),
        "part_contentieux_pct": pct(sum(f["reste_du_xof"] for f in contentieux), encours_xof),
        "montant_regle_xof": montant_regle_xof,
        "nb_factures_reglees": len(reglees),
        "taux_recouvrement_pct": taux_recouvrement_pct,
        # Délai d'encaissement constaté : facture → règlement, sur les factures
        # effectivement réglées. C'est le DSO au sens comportemental.
        "delai_encaissement_moyen_jours": round(sum(delais) / len(delais), 1) if delais else None,
        "delai_encaissement_median_jours": _mediane(delais),
        "retard_moyen_jours": round(sum(retards) / len(retards), 1) if retards else None,
        "retard_median_jours": _mediane(retards),
        "nb_delais_mesures": len(delais),
        # Lecture bilancielle : encours rapporté au CA de l'exercice, ramené en
        # jours de chiffre. Inclut le stock d'impayés anciens, donc bien plus élevé
        # que le délai constaté — c'est le signal de recouvrement, pas de délai.
        "dso_encours_jours": (
            round(encours_xof / ca_exercice_xof * jours_exercice_ecoules)
            if ca_exercice_xof and jours_exercice_ecoules else None
        ),
        "ca_exercice_xof": ca_exercice_xof,
        "jours_exercice_ecoules": jours_exercice_ecoules,
    }


# ── DSO ──────────────────────────────────────────────────────────────────────

def build_dso(factures: list[dict], socle: dict, aujourdhui: date, annee: int) -> dict:
    """Deux lectures du DSO, nommées séparément, plus la série mensuelle du délai constaté.

    La série est calculée sur le MOIS DE RÈGLEMENT et non sur le mois de facture :
    une facture de janvier réglée en juin dégrade le délai de juin, pas celui de
    janvier. C'est la lecture qui correspond à ce que la trésorerie a vécu.
    """
    par_mois: dict[str, dict] = {}
    for f in factures:
        reglement, facture = jour(f["date_reglement"]), jour(f["date_facture"])
        if not reglement or not facture or f["annulee"]:
            continue
        cle = cle_mois(reglement)
        ligne = par_mois.setdefault(cle, {"mois": cle, "delais": [], "retards": [], "montant_xof": 0, "nb": 0})
        ligne["delais"].append((reglement - facture).days)
        echeance = jour(f["echeance"])
        if echeance:
            ligne["retards"].append((reglement - echeance).days)
        ligne["montant_xof"] += f["montant_xof"]
        ligne["nb"] += 1

    serie = []
    for cle in sorted(par_mois)[-18:]:
        ligne = par_mois[cle]
        an, mo = int(cle[:4]), int(cle[5:7])
        serie.append({
            "mois": cle,
            "libelle": libelle_mois(an, mo, court=True),
            "nb_factures": ligne["nb"],
            "montant_encaisse_xof": ligne["montant_xof"],
            "delai_moyen_jours": round(sum(ligne["delais"]) / len(ligne["delais"]), 1) if ligne["delais"] else None,
            "retard_moyen_jours": round(sum(ligne["retards"]) / len(ligne["retards"]), 1) if ligne["retards"] else None,
        })

    nb_reglees = socle["nb_factures_reglees"]
    nb_total_non_annulees = sum(1 for f in factures if not f["annulee"])
    return {
        "source": statique.SOURCE_REELLE,
        "annee": annee,
        "as_of": aujourdhui.isoformat(),
        "delai_encaissement_moyen_jours": socle["delai_encaissement_moyen_jours"],
        "delai_encaissement_median_jours": socle["delai_encaissement_median_jours"],
        "retard_moyen_jours": socle["retard_moyen_jours"],
        "retard_median_jours": socle["retard_median_jours"],
        "dso_encours_jours": socle["dso_encours_jours"],
        "cible_dso_jours": statique.CIBLES_PERFORMANCE["dso_jours"],
        "encours_xof": socle["encours_xof"],
        "encours_echu_xof": socle["encours_echu_xof"],
        "encours_a_echoir_xof": socle["encours_a_echoir_xof"],
        "nb_factures_ouvertes": socle["nb_factures_ouvertes"],
        "taux_recouvrement_pct": socle["taux_recouvrement_pct"],
        "ca_exercice_xof": socle["ca_exercice_xof"],
        "serie_mensuelle": serie,
        "couverture": {
            "nb_factures": nb_total_non_annulees,
            "nb_reglees_datees": nb_reglees,
            "part_datee_pct": pct(nb_reglees, nb_total_non_annulees),
            "nb_delais_mesures": socle["nb_delais_mesures"],
        },
        "ecart_lectures_jours": (
            socle["dso_encours_jours"] - socle["delai_encaissement_moyen_jours"]
            if socle["dso_encours_jours"] is not None and socle["delai_encaissement_moyen_jours"] is not None
            else None
        ),
        "note": (
            "Deux lectures du même sujet, à ne pas confondre. Le DÉLAI CONSTATÉ est mesuré sur les "
            "factures effectivement réglées : il dit combien de temps met un client qui paie. Le DSO "
            "SUR ENCOURS rapporte l'encours total au chiffre d'affaires de l'exercice : il inclut les "
            "factures anciennes jamais réglées, que la première lecture ne peut pas voir. L'écart "
            "entre les deux est la mesure du stock d'impayés, pas une incohérence."
        ),
    }


def build_balance_agee(factures: list[dict], aujourdhui: date) -> dict:
    """Balance âgée des créances — mesurée sur les échéances réelles."""
    ouvertes = [f for f in factures if _ouverte(f)]
    total = sum(f["reste_du_xof"] for f in ouvertes)

    tranches = []
    for code, libelle, borne_min, borne_max in TRANCHES_AGE:
        lignes = []
        for f in ouvertes:
            echeance = jour(f["echeance"])
            if not echeance:
                continue
            retard = (aujourdhui - echeance).days
            if code == "non_echu":
                if retard <= 0:
                    lignes.append(f)
            elif borne_max is None:
                if retard >= borne_min:
                    lignes.append(f)
            elif borne_min <= retard <= borne_max:
                lignes.append(f)
        montant = sum(f["reste_du_xof"] for f in lignes)
        tranches.append({
            "code": code,
            "libelle": libelle,
            "nb_factures": len(lignes),
            "montant_xof": montant,
            "part_pct": pct(montant, total),
        })

    sans_echeance = [f for f in ouvertes if not jour(f["echeance"])]
    return {
        "source": statique.SOURCE_REELLE,
        "as_of": aujourdhui.isoformat(),
        "tranches": tranches,
        "total_xof": total,
        "nb_factures": len(ouvertes),
        "nb_sans_echeance": len(sans_echeance),
        "montant_sans_echeance_xof": sum(f["reste_du_xof"] for f in sans_echeance),
        "note": (
            "Âge calculé entre l'échéance de la facture et la date du jour, sur le reste dû et non "
            "sur le montant facturé : une facture réglée à moitié ne pèse que pour sa moitié."
        ),
    }


# ── Mauvais payeurs ──────────────────────────────────────────────────────────

def build_mauvais_payeurs(factures: list[dict], aujourdhui: date, limit: int = 15) -> dict:
    """Classement des clients par risque de paiement — comportement passé ET exposition présente.

    L'indice croise trois signaux plutôt que de classer par montant : le retard
    moyen déjà constaté (le client est lent par nature), le retard courant maximal
    (il est bloqué aujourd'hui) et le poids de son encours échu (il pèse sur la
    trésorerie). Un classement par montant seul remonterait les gros clients
    ponctuels ; un classement par retard seul remonterait des impayés à 40 000 F.
    """
    par_client: dict[str, dict] = {}
    for f in factures:
        if f["annulee"]:
            continue
        cle = f["client_id"] or f["client"]
        c = par_client.setdefault(cle, {
            "client": f["client"], "client_id": f["client_id"], "client_connu": f["client_connu"],
            "nb_factures": 0, "montant_facture_xof": 0,
            "nb_reglees": 0, "retards_regles": [],
            "nb_ouvertes": 0, "encours_xof": 0, "encours_echu_xof": 0,
            "retard_courant_max_jours": 0, "echeance_la_plus_ancienne": None,
        })
        c["nb_factures"] += 1
        c["montant_facture_xof"] += f["montant_xof"]

        reglement, echeance = jour(f["date_reglement"]), jour(f["echeance"])
        if reglement:
            c["nb_reglees"] += 1
            if echeance:
                c["retards_regles"].append((reglement - echeance).days)
        if _ouverte(f):
            c["nb_ouvertes"] += 1
            c["encours_xof"] += f["reste_du_xof"]
            if echeance and echeance < aujourdhui:
                retard = (aujourdhui - echeance).days
                c["encours_echu_xof"] += f["reste_du_xof"]
                if retard > c["retard_courant_max_jours"]:
                    c["retard_courant_max_jours"] = retard
                    c["echeance_la_plus_ancienne"] = f["echeance"]

    total_echu = sum(c["encours_echu_xof"] for c in par_client.values()) or 1
    # Le poids financier se normalise sur le PIRE débiteur, pas sur le total.
    # Rapporté au total (11,2 Md sur ce miroir), le plus gros débiteur ne pesait que
    # 2,9 % : la composante montant devenait négligeable et les quinze premiers
    # clients ressortaient tous au même indice de 80. Le classement n'apprenait
    # alors rien de plus que la liste des retards, alors que le montant en jeu est
    # précisément ce qui décide de l'ordre des relances.
    max_echu = max((c["encours_echu_xof"] for c in par_client.values()), default=0) or 1

    clients = []
    for c in par_client.values():
        retards = c["retards_regles"]
        retard_moyen = round(sum(retards) / len(retards), 1) if retards else None
        significatif = len(retards) >= MIN_FACTURES_COMPORTEMENT

        # Trois composantes normalisées, pondérées 30/35/35. Le comportement n'entre
        # dans l'indice que s'il est significatif : sinon son poids est reporté sur
        # les deux autres, qui sont des faits et non des moyennes.
        comportement = min(1.0, max(0.0, (retard_moyen or 0) / PLAFOND_RETARD_JOURS)) if significatif else None
        exposition = min(1.0, c["retard_courant_max_jours"] / PLAFOND_RETARD_JOURS)
        poids_encours = min(1.0, c["encours_echu_xof"] / max_echu)
        if comportement is None:
            indice = (exposition * 0.55 + poids_encours * 0.45) * 100
        else:
            indice = (comportement * 0.30 + exposition * 0.35 + poids_encours * 0.35) * 100

        if c["retard_courant_max_jours"] > SEUIL_CONTENTIEUX_JOURS and c["encours_echu_xof"] > 0:
            statut = "contentieux"
        elif c["encours_echu_xof"] > 0:
            statut = "en_retard"
        elif significatif and (retard_moyen or 0) > 30:
            statut = "payeur_lent"
        else:
            statut = "a_jour"

        clients.append({
            "client": c["client"],
            "client_id": c["client_id"],
            "client_connu": c["client_connu"],
            "nb_factures": c["nb_factures"],
            "montant_facture_xof": c["montant_facture_xof"],
            "nb_factures_reglees": c["nb_reglees"],
            "retard_moyen_regle_jours": retard_moyen,
            # Faux sous le seuil : le retard reste affiché, mais il ne pèse pas
            # dans l'indice et l'écran doit le dire.
            "comportement_significatif": significatif,
            "nb_factures_ouvertes": c["nb_ouvertes"],
            "encours_xof": c["encours_xof"],
            "encours_echu_xof": c["encours_echu_xof"],
            "retard_courant_max_jours": c["retard_courant_max_jours"],
            "echeance_la_plus_ancienne": c["echeance_la_plus_ancienne"],
            "part_encours_echu_pct": pct(c["encours_echu_xof"], total_echu),
            "indice_risque": round(indice, 1),
            "statut": statut,
        })

    # Ne sont classés que les clients qui portent un signal : un client à jour sans
    # encours n'a pas à figurer dans un suivi de mauvais payeurs.
    a_risque = [c for c in clients if c["statut"] != "a_jour"]
    a_risque.sort(key=lambda c: (-c["indice_risque"], -c["encours_echu_xof"]))

    return {
        "source": statique.SOURCE_REELLE,
        "as_of": aujourdhui.isoformat(),
        "clients": a_risque[:limit],
        "totaux": {
            "nb_clients_factures": len(clients),
            "nb_clients_a_risque": len(a_risque),
            "nb_contentieux": sum(1 for c in a_risque if c["statut"] == "contentieux"),
            "nb_payeurs_lents": sum(1 for c in a_risque if c["statut"] == "payeur_lent"),
            # Au-delà de deux ans, la créance ne relève plus du recouvrement. Le
            # compteur est là parce que ce miroir en porte beaucoup (des retards de
            # 1 685 et 2 653 jours figurent dans le classement) et qu'un « mauvais
            # payeur » de sept ans est en réalité un problème de provision.
            "nb_clients_arriere_ancien": sum(1 for c in clients if c["retard_courant_max_jours"] > 2 * 365),
            "encours_arriere_ancien_xof": sum(
                c["encours_echu_xof"] for c in clients if c["retard_courant_max_jours"] > 2 * 365
            ),
            "encours_echu_total_xof": sum(c["encours_echu_xof"] for c in clients),
            "part_top5_encours_echu_pct": pct(
                sum(c["encours_echu_xof"] for c in a_risque[:5]),
                sum(c["encours_echu_xof"] for c in clients) or 1,
            ),
        },
        "regle": {
            "composantes": "retard moyen constaté (30 %), retard courant maximal (35 %), "
                           "encours échu rapporté à celui du plus gros débiteur (35 %)",
            "min_factures_comportement": MIN_FACTURES_COMPORTEMENT,
            "plafond_retard_jours": PLAFOND_RETARD_JOURS,
            "seuil_contentieux_jours": SEUIL_CONTENTIEUX_JOURS,
        },
        "note": (
            "Deux natures de mauvais payeur sont distinguées : le client LENT (il paie, mais tard — "
            "mesuré sur ses factures déjà réglées) et le client BLOQUÉ (une créance échue court "
            "aujourd'hui). Le premier se traite en renégociant les délais, le second en relançant. "
            "Un retard moyen calculé sur moins de "
            f"{MIN_FACTURES_COMPORTEMENT} factures réglées est affiché mais n'entre pas dans l'indice : son "
            "poids est alors reporté sur l'exposition et le montant, qui sont des faits. Un client sans "
            "historique n'est donc pas crédité d'un bon comportement qu'on ne lui connaît pas. "
            "Les retards de plus de deux ans sont comptés à part : à cette ancienneté, la question "
            "n'est plus de relancer mais de provisionner."
        ),
    }


# ── DPO ──────────────────────────────────────────────────────────────────────

def build_dpo(factures_fournisseurs: list[dict], achats: list[dict], delais_negocies: list[dict],
              aujourdhui: date, annee: int) -> dict:
    """DPO réel si des factures fournisseurs existent, gabarit sinon — même forme dans les deux cas.

    Aujourd'hui la table est vide : le retour porte `source: "statique"` et dit
    pourquoi. Le jour où la synchronisation des `in_invoice` sera en place, le même
    code renvoie un DPO mesuré sans qu'aucun écran ne change.

    Ce qui est mesuré dans les deux régimes : les achats ENGAGÉS de l'exercice.
    C'est la seule charge fournisseur réellement observable, et elle est présentée
    comme un engagement, jamais comme une dette échue.
    """
    achats_exercice = [a for a in achats if (jour(a["date"]) or date(1900, 1, 1)).year == annee]
    engage_xof = sum(a["montant_xof"] for a in achats_exercice)
    delais = [d["delai_jours"] for d in delais_negocies if d["delai_jours"] is not None]

    base_mesuree = {
        "achats_engages_exercice_xof": engage_xof,
        "nb_commandes_exercice": len(achats_exercice),
        "nb_fournisseurs_exercice": len({a["fournisseur"] for a in achats_exercice}),
        "achats_engages_total_xof": sum(a["montant_xof"] for a in achats),
        "nb_commandes_total": len(achats),
        "nb_fiches_fournisseur": len(delais_negocies),
        "nb_delais_negocies_renseignes": len(delais),
        "delai_negocie_moyen_jours": round(sum(delais) / len(delais), 1) if delais else None,
    }

    if not factures_fournisseurs:
        total_part = sum(t["part_pct"] for t in statique.DPO_TRANCHES_STATIQUES) or 1
        # La dette posée est calibrée sur les achats RÉELS d'un trimestre : un
        # montant sorti de nulle part serait invérifiable, celui-ci se recalcule.
        dette_posee_xof = round(engage_xof / 4)
        return {
            "source": statique.SOURCE_STATIQUE,
            "raison": statique.RAISON_DPO_STATIQUE,
            "avertissement": statique.AVERTISSEMENT_STATIQUE,
            "as_of": aujourdhui.isoformat(),
            "annee": annee,
            "dpo_jours": statique.DPO_STATIQUE_JOURS,
            "delai_negocie_moyen_jours": base_mesuree["delai_negocie_moyen_jours"]
            or statique.DELAI_NEGOCIE_MOYEN_JOURS,
            "dette_xof": dette_posee_xof,
            "dette_echue_xof": round(dette_posee_xof * (100 - statique.DPO_TRANCHES_STATIQUES[0]["part_pct"]) / 100),
            "nb_factures_fournisseurs": 0,
            "tranches": [
                {
                    "code": t["code"],
                    "libelle": t["libelle"],
                    "part_pct": round(t["part_pct"] / total_part * 100, 1),
                    "montant_xof": round(dette_posee_xof * t["part_pct"] / total_part),
                    "nb_factures": None,
                }
                for t in statique.DPO_TRANCHES_STATIQUES
            ],
            "base_mesuree": base_mesuree,
            "note": (
                "Le DPO affiché est posé. Ce qui est mesuré, ce sont les achats engagés de "
                "l'exercice — des commandes, pas des factures : ni échéance, ni reste dû. La dette "
                "du gabarit est calibrée sur un trimestre d'achats réels pour rester vérifiable, "
                "mais elle ne correspond à aucune facture existante."
            ),
        }

    # ── Régime mesuré (dès que les factures fournisseurs seront synchronisées) ──
    reglees = [f for f in factures_fournisseurs if f["date_reglement"]]
    delais_reels, retards_reels = [], []
    for f in reglees:
        reglement, facture, echeance = jour(f["date_reglement"]), jour(f["date_facture"]), jour(f["echeance"])
        if reglement and facture:
            delais_reels.append((reglement - facture).days)
        if reglement and echeance:
            retards_reels.append((reglement - echeance).days)

    ouvertes = [f for f in factures_fournisseurs if f["reste_du_xof"] > 0]
    dette_xof = sum(f["reste_du_xof"] for f in ouvertes)
    tranches = []
    for code, libelle, borne_min, borne_max in TRANCHES_AGE:
        lignes = []
        for f in ouvertes:
            echeance = jour(f["echeance"])
            if not echeance:
                continue
            retard = (aujourdhui - echeance).days
            if code == "non_echu":
                if retard <= 0:
                    lignes.append(f)
            elif borne_max is None:
                if retard >= borne_min:
                    lignes.append(f)
            elif borne_min <= retard <= borne_max:
                lignes.append(f)
        montant = sum(f["reste_du_xof"] for f in lignes)
        tranches.append({
            "code": code, "libelle": libelle, "nb_factures": len(lignes),
            "montant_xof": montant, "part_pct": pct(montant, dette_xof),
        })

    return {
        "source": statique.SOURCE_REELLE,
        "raison": None,
        "avertissement": None,
        "as_of": aujourdhui.isoformat(),
        "annee": annee,
        "dpo_jours": round(sum(delais_reels) / len(delais_reels), 1) if delais_reels else None,
        "retard_moyen_jours": round(sum(retards_reels) / len(retards_reels), 1) if retards_reels else None,
        "delai_negocie_moyen_jours": base_mesuree["delai_negocie_moyen_jours"],
        "dette_xof": dette_xof,
        "dette_echue_xof": sum(
            f["reste_du_xof"] for f in ouvertes
            if (jour(f["echeance"]) and jour(f["echeance"]) < aujourdhui)
        ),
        "nb_factures_fournisseurs": len(factures_fournisseurs),
        "tranches": tranches,
        "base_mesuree": base_mesuree,
        "note": (
            "DPO mesuré sur les factures fournisseurs synchronisées : délai entre la facture et son "
            "règlement effectif. À comparer au délai négocié sur la fiche fournisseur — payer plus "
            "vite que négocié est un financement gratuit consenti au fournisseur."
        ),
    }
