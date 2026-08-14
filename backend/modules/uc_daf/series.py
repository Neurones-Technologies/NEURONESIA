"""Séries temporelles du volet financier — la dimension que les écrans DAF n'avaient pas.

Les trois tableaux de bord affichaient des NIVEAUX : un encours, un DSO moyen, un
taux de marge, une consommation budgétaire. Un DAF ne pilote pas sur un niveau, il
pilote sur une PENTE — et deux chiffres de ce cockpit le montrent :

- le délai d'encoursement moyen affiché est de 65,9 jours, toutes périodes
  confondues. Reconstruit trimestre par trimestre, il vaut 48 à 65 jours de
  mi-2024 à fin 2025, puis 104 jours au T1 2026 et 113 au T2. La moyenne écrase
  un doublement ;
- l'encours client vaut 7,6 Md FCFA en mars 2024 et 15,6 Md en juin 2026, +105 %
  en 27 mois, quand le chiffre d'affaires, lui, ne double pas.

Ni l'un ni l'autre n'était visible avant ce module.

CE QUI REND CES SÉRIES POSSIBLES SANS HISTORISATION. Rien n'est archivé dans le
système : il n'existe aucun instantané mensuel du poste client. Mais une facture
porte sa date d'émission, son échéance et sa date de règlement : à n'importe
quelle date passée, on sait donc si elle était ouverte et depuis combien de temps.
L'historique est RECONSTRUIT, il n'est pas relu.

LA LIMITE DE CETTE RECONSTRUCTION, marquée jusqu'à l'écran : le montant RESTANT DÛ
à une date passée n'est pas connu — le miroir ne garde que le montant facturé et
la date du règlement final. Un règlement partiel n'est donc pas datable, et la
courbe d'encours compte la facture entière jusqu'à son solde. L'encours historique
est ainsi légèrement MAJORÉ par rapport à l'encours du jour, qui, lui, est calculé
sur le reste dû réel. Les deux chiffres ne se recouvrent pas exactement et c'est
normal : ce sont deux mesures différentes.

Aucune requête SQL nouvelle ici : tout se calcule sur les lectures déjà faites par
les endpoints (factures, achats, dossiers, CA mensuel). Le coût est une boucle
Python de quelques dizaines de milliers d'itérations, déportée hors de la boucle
d'événements comme le reste du module.
"""
from __future__ import annotations

from datetime import date

from modules.uc_daf import statique
from modules.uc_daf.commun import fin_de_mois, jour, libelle_mois, pct
from modules.uc_daf.relation_commerciale import SEUIL_CONTENTIEUX_JOURS

# Profondeur des séries reconstruites, en mois. 30 mois couvrent deux exercices
# pleins plus l'exercice courant : assez pour distinguer une saisonnalité d'une
# dérive, ce qu'une fenêtre de 12 mois ne permet pas.
PROFONDEUR_MOIS = 30

# Tranches d'ancienneté de la courbe d'encours. C'est une échelle ORDINALE (la
# sévérité croît), d'où une rampe d'une seule teinte côté écran plutôt que quatre
# couleurs d'identité : l'ordre doit se lire dans la couleur.
TRANCHES_SERIE = [
    ("non_echu", "Non échu", None, 0),
    ("0_30", "1 à 30 jours", 1, 30),
    ("31_90", "31 à 90 jours", 31, SEUIL_CONTENTIEUX_JOURS),
    ("90_plus", "Plus de 90 jours", SEUIL_CONTENTIEUX_JOURS + 1, None),
]

# Fenêtre du DSO glissant, en mois. Le délai d'encaissement est trop irrégulier
# d'un mois sur l'autre pour être lu brut : février 2026 encaisse 22 factures,
# juin 2026 une seule. Une moyenne sur trois mois glissants lisse ce bruit sans
# masquer une rupture de tendance — le doublement du T1 2026 reste visible.
FENETRE_GLISSANTE_MOIS = 3

# En dessous de ce nombre de règlements dans la fenêtre, le point n'est pas publié :
# un DSO calculé sur deux factures n'est pas une tendance, c'est une anecdote.
MIN_REGLEMENTS_FENETRE = 5

# Part de la médiane historique en dessous de laquelle un mois est déclaré
# incomplet. Les mois récents du miroir portent 0 à 1 règlement là où la médiane
# est à 22 : ce n'est pas un arrêt des encaissements, c'est une synchronisation
# des règlements en retard. Une courbe qui plongerait sans le dire ferait paniquer
# sur un trou de données.
SEUIL_MOIS_INCOMPLET = 0.30


def _mois_glissants(fin: date, profondeur: int) -> list[tuple[int, int]]:
    """Les `profondeur` derniers mois, du plus ancien au mois de `fin` inclus."""
    an, mo = fin.year, fin.month
    mois = []
    for _ in range(profondeur):
        mois.append((an, mo))
        mo -= 1
        if mo == 0:
            an, mo = an - 1, 12
    return list(reversed(mois))


# ── Courbe d'encours client par ancienneté ──────────────────────────────────

def build_serie_encours(factures: list[dict], aujourdhui: date,
                        profondeur: int = PROFONDEUR_MOIS) -> dict:
    """Encours client reconstruit à chaque fin de mois, ventilé par ancienneté.

    Une facture est comptée ouverte à la date T si elle est émise (`date_facture
    <= T`), non annulée, et pas encore réglée (`date_reglement` absente ou
    postérieure à T). Son ancienneté à T se compte depuis son échéance.

    C'est la courbe que le DAF n'avait pas : elle dit si le poste client se
    dégrade ou se redresse, là où la balance âgée du jour ne donne qu'une photo.
    """
    # Pré-calcul des dates : `jour()` sur 2 957 factures × 30 mois coûterait
    # 90 000 parsings de chaîne pour un résultat identique à chaque tour.
    lignes = []
    for f in factures:
        if f["annulee"]:
            continue
        emise = jour(f["date_facture"])
        if not emise:
            continue
        lignes.append((emise, jour(f["echeance"]), jour(f["date_reglement"]), f["montant_xof"]))

    points = []
    for an, mo in _mois_glissants(aujourdhui, profondeur):
        fin = min(fin_de_mois(an, mo), aujourdhui)
        tranches = {code: {"montant_xof": 0, "nb": 0} for code, _, _, _ in TRANCHES_SERIE}
        total, nb_total = 0, 0

        for emise, echeance, reglee, montant in lignes:
            if emise > fin or (reglee and reglee <= fin):
                continue
            retard = (fin - echeance).days if echeance else 0
            for code, _, borne_min, borne_max in TRANCHES_SERIE:
                if code == "non_echu":
                    ok = retard <= 0
                elif borne_max is None:
                    ok = retard >= borne_min
                else:
                    ok = borne_min <= retard <= borne_max
                if ok:
                    tranches[code]["montant_xof"] += montant
                    tranches[code]["nb"] += 1
                    break
            total += montant
            nb_total += 1

        points.append({
            "mois": f"{an:04d}-{mo:02d}",
            "libelle": libelle_mois(an, mo, court=True),
            "total_xof": total,
            "nb_factures": nb_total,
            "tranches": [
                {
                    "code": code,
                    "libelle": libelle,
                    "montant_xof": tranches[code]["montant_xof"],
                    "nb_factures": tranches[code]["nb"],
                    "part_pct": pct(tranches[code]["montant_xof"], total),
                }
                for code, libelle, _, _ in TRANCHES_SERIE
            ],
        })

    premier, dernier = (points[0], points[-1]) if points else (None, None)
    contentieux_debut = (
        next(t["montant_xof"] for t in premier["tranches"] if t["code"] == "90_plus") if premier else 0
    )
    contentieux_fin = (
        next(t["montant_xof"] for t in dernier["tranches"] if t["code"] == "90_plus") if dernier else 0
    )

    return {
        "source": statique.SOURCE_REELLE,
        "as_of": aujourdhui.isoformat(),
        "profondeur_mois": profondeur,
        "points": points,
        "tranches": [{"code": c, "libelle": lib} for c, lib, _, _ in TRANCHES_SERIE],
        "evolution": {
            "depuis": premier["mois"] if premier else None,
            "encours_debut_xof": premier["total_xof"] if premier else 0,
            "encours_fin_xof": dernier["total_xof"] if dernier else 0,
            "variation_pct": pct(
                (dernier["total_xof"] - premier["total_xof"]) if premier else 0,
                premier["total_xof"] if premier and premier["total_xof"] else 1,
            ),
            "contentieux_debut_xof": contentieux_debut,
            "contentieux_fin_xof": contentieux_fin,
            "part_contentieux_debut_pct": pct(contentieux_debut, premier["total_xof"] if premier else 1),
            "part_contentieux_fin_pct": pct(contentieux_fin, dernier["total_xof"] if dernier else 1),
        },
        "limite": (
            "Encours reconstruit sur le montant FACTURÉ : le reste dû à une date passée n'est pas "
            "conservé par le miroir, un règlement partiel n'est donc pas datable. La courbe compte "
            "la facture entière jusqu'à son solde et majore donc légèrement l'encours par rapport "
            "au chiffre du jour, calculé lui sur le reste dû réel."
        ),
        "note": (
            "Reconstruit facture par facture à chaque fin de mois — aucun instantané n'est archivé "
            "dans le système, mais les dates d'émission, d'échéance et de règlement suffisent à "
            "savoir quelles factures étaient ouvertes, et depuis combien de temps."
        ),
    }


# ── Courbe de DSO glissant ──────────────────────────────────────────────────

def build_serie_dso(factures: list[dict], aujourdhui: date, cible_jours: int,
                    profondeur: int = PROFONDEUR_MOIS,
                    fenetre: int = FENETRE_GLISSANTE_MOIS) -> dict:
    """Délai d'encaissement moyen sur `fenetre` mois glissants, par mois de règlement.

    Le point est placé sur le mois où l'argent est RENTRÉ, pas sur le mois de la
    facture : c'est la lecture que la trésorerie a vécue. Un mois dont la fenêtre
    porte moins de `MIN_REGLEMENTS_FENETRE` règlements n'est pas publié — un DSO
    calculé sur deux factures se lirait comme une tendance alors que c'est un
    accident d'échantillon.
    """
    par_mois: dict[str, list[tuple[int, int, int]]] = {}
    for f in factures:
        if f["annulee"]:
            continue
        reglement, emise, echeance = jour(f["date_reglement"]), jour(f["date_facture"]), jour(f["echeance"])
        if not reglement or not emise:
            continue
        cle = f"{reglement.year:04d}-{reglement.month:02d}"
        par_mois.setdefault(cle, []).append((
            (reglement - emise).days,
            (reglement - echeance).days if echeance else 0,
            f["montant_xof"],
        ))

    mois = _mois_glissants(aujourdhui, profondeur)
    volumes = [len(par_mois.get(f"{an:04d}-{mo:02d}", [])) for an, mo in mois]
    volumes_tries = sorted(v for v in volumes if v > 0)
    mediane_volume = volumes_tries[len(volumes_tries) // 2] if volumes_tries else 0

    points = []
    for i, (an, mo) in enumerate(mois):
        fenetre_mois = mois[max(0, i - fenetre + 1): i + 1]
        echantillon = [
            item for a, m in fenetre_mois for item in par_mois.get(f"{a:04d}-{m:02d}", [])
        ]
        nb_mois_courant = len(par_mois.get(f"{an:04d}-{mo:02d}", []))
        # Un mois presque vide face à la médiane historique n'est pas un mois sans
        # encaissement : c'est une synchronisation des règlements incomplète.
        incomplet = bool(mediane_volume) and nb_mois_courant < mediane_volume * SEUIL_MOIS_INCOMPLET
        exploitable = len(echantillon) >= MIN_REGLEMENTS_FENETRE

        points.append({
            "mois": f"{an:04d}-{mo:02d}",
            "libelle": libelle_mois(an, mo, court=True),
            "delai_moyen_jours": (
                round(sum(d for d, _, _ in echantillon) / len(echantillon), 1) if exploitable else None
            ),
            "retard_moyen_jours": (
                round(sum(r for _, r, _ in echantillon) / len(echantillon), 1) if exploitable else None
            ),
            "nb_reglements_mois": nb_mois_courant,
            "nb_reglements_fenetre": len(echantillon),
            "montant_encaisse_mois_xof": sum(
                m for _, _, m in par_mois.get(f"{an:04d}-{mo:02d}", [])
            ),
            "exploitable": exploitable,
            "synchronisation_incomplete": incomplet,
        })

    publies = [p for p in points if p["delai_moyen_jours"] is not None]
    # Le résumé ne se calcule QUE sur les points fiables. Sur ce miroir, les cinq
    # derniers mois portent 0 à 6 règlements contre une médiane de 22 : le délai y
    # monte à 127 jours, mais quand seuls les règlements les plus tardifs ont été
    # rapatriés, la moyenne monte sans que rien n'ait changé chez les clients.
    # Tirer une variation entre deux points bruités produirait un commentaire faux.
    fiables = [p for p in publies if not p["synchronisation_incomplete"]]
    debut = fiables[0] if fiables else None
    fin = fiables[-1] if fiables else None
    pire = max(fiables, key=lambda p: p["delai_moyen_jours"]) if fiables else None

    return {
        "source": statique.SOURCE_REELLE,
        "as_of": aujourdhui.isoformat(),
        "fenetre_mois": fenetre,
        "cible_jours": cible_jours,
        "points": points,
        "resume": {
            "depuis": debut["mois"] if debut else None,
            "delai_debut_jours": debut["delai_moyen_jours"] if debut else None,
            # Dernier point FIABLE, et non dernier point tracé : c'est le chiffre
            # sur lequel une décision peut se prendre.
            "dernier_mois_fiable": fin["libelle"] if fin else None,
            "delai_fin_jours": fin["delai_moyen_jours"] if fin else None,
            "variation_jours": (
                round(fin["delai_moyen_jours"] - debut["delai_moyen_jours"], 1)
                if debut and fin else None
            ),
            "ecart_cible_jours": (
                round(fin["delai_moyen_jours"] - cible_jours, 1) if fin else None
            ),
            "pire_mois": pire["libelle"] if pire else None,
            "pire_delai_jours": pire["delai_moyen_jours"] if pire else None,
            "nb_mois_au_dessus_cible": sum(
                1 for p in fiables if p["delai_moyen_jours"] > cible_jours
            ),
            "nb_mois_publies": len(publies),
            "nb_mois_fiables": len(fiables),
            "nb_mois_synchronisation_incomplete": sum(1 for p in points if p["synchronisation_incomplete"]),
        },
        "note": (
            f"Moyenne glissante sur {fenetre} mois du délai entre l'émission de la facture et son "
            "règlement, positionnée sur le mois où l'argent est rentré. Les mois dont la fenêtre "
            f"porte moins de {MIN_REGLEMENTS_FENETRE} règlements ne sont pas tracés, et les mois "
            "dont le volume de règlements s'effondre par rapport à l'historique sont signalés : "
            "sur ce miroir, ils traduisent une synchronisation incomplète, pas un arrêt des "
            "encaissements."
        ),
    }


# ── Courbe de consommation budgétaire (burn-down) ───────────────────────────

def build_burn_down(achats: list[dict], ca_mensuel: list[dict], budget_total_xof: int,
                    annee: int, aujourdhui: date) -> dict:
    """Achats cumulés, CA signé cumulé et droite de rythme budgétaire, sur l'exercice.

    Trois tracés sur une seule échelle de montants — jamais deux axes : la droite
    de rythme est le budget réparti linéairement, et le CA est là pour trancher la
    seule question qui compte quand la consommation est basse. Dans une ESN de
    négoce, les achats suivent les ventes : une sous-consommation de deux milliards
    n'est une économie que si le CA tient. Sinon c'est une activité en baisse, et
    les deux courbes le disent d'un regard.
    """
    achats_mois = {}
    for a in achats:
        d = jour(a["date"])
        if d and d.year == annee:
            achats_mois[d.month] = achats_mois.get(d.month, 0) + a["montant_xof"]
    ca_mois = {m["mois"]: m["ca_xof"] for m in ca_mensuel}

    dernier_mois = 12 if aujourdhui.year > annee else (aujourdhui.month if aujourdhui.year == annee else 0)
    points, cum_achats, cum_ca = [], 0, 0
    for mo in range(1, 13):
        if mo > dernier_mois:
            break
        cum_achats += achats_mois.get(mo, 0)
        cum_ca += ca_mois.get(mo, 0)
        points.append({
            "mois": mo,
            "libelle": libelle_mois(annee, mo, court=True),
            "achats_mois_xof": achats_mois.get(mo, 0),
            "achats_cumules_xof": cum_achats,
            "ca_mois_xof": ca_mois.get(mo, 0),
            "ca_cumule_xof": cum_ca,
            "rythme_budget_xof": round(budget_total_xof * mo / 12),
            "ecart_rythme_xof": cum_achats - round(budget_total_xof * mo / 12),
        })

    dernier = points[-1] if points else None
    return {
        # Achats et CA mesurés, budget posé : mixte, comme le bloc des lignes.
        "source": statique.SOURCE_MIXTE,
        "annee": annee,
        "as_of": aujourdhui.isoformat(),
        "budget_total_xof": budget_total_xof,
        "points": points,
        "resume": {
            "achats_cumules_xof": dernier["achats_cumules_xof"] if dernier else 0,
            "ca_cumule_xof": dernier["ca_cumule_xof"] if dernier else 0,
            "rythme_xof": dernier["rythme_budget_xof"] if dernier else 0,
            "ecart_rythme_xof": dernier["ecart_rythme_xof"] if dernier else 0,
            "taux_marge_flux_pct": pct(
                (dernier["ca_cumule_xof"] - dernier["achats_cumules_xof"]) if dernier else 0,
                dernier["ca_cumule_xof"] if dernier and dernier["ca_cumule_xof"] else 1,
            ),
            "mois_couverts": len(points),
        },
        "raison": statique.RAISON_BUDGET_STATIQUE,
        "avertissement": statique.AVERTISSEMENT_STATIQUE,
        "note": (
            "La droite de rythme répartit le budget posé en douze parts égales : elle ne prétend pas "
            "à une saisonnalité, elle sert de repère. Le CA signé cumulé est superposé sur la même "
            "échelle parce que, sur une activité de négoce, une consommation d'achats basse ne se "
            "lit pas seule — elle peut signer une économie comme une baisse d'activité."
        ),
    }


# ── Marge par exercice ──────────────────────────────────────────────────────

def build_marge_annuelle(dossiers: list[dict], aujourdhui: date, cible_pct: float,
                         nb_exercices: int = 6) -> dict:
    """Taux de marge par exercice, sur les seuls dossiers dont la dépense est imputée.

    L'écran ne montrait qu'un exercice à la fois. Mis bout à bout, les exercices
    racontent autre chose : 4,0 % en 2021, 16,1 % en 2022, puis un plateau à 40 %
    de 2023 à 2025. Savoir que 40 % est le régime de croisière est ce qui permet
    de juger l'exercice en cours — un point isolé ne le permet pas.

    La couverture accompagne chaque barre : un exercice dont deux dossiers sur
    238 portent une dépense n'est pas comparable aux autres, et l'écran doit
    pouvoir le griser plutôt que de le tracer comme les autres.
    """
    par_annee: dict[int, dict] = {}
    for d in dossiers:
        cree = jour(d["cree_le"])
        if not cree:
            continue
        a = par_annee.setdefault(cree.year, {
            "nb_dossiers": 0, "nb_imputes": 0,
            "ca_total_xof": 0, "ca_impute_xof": 0, "depense_xof": 0, "marge_xof": 0,
        })
        a["nb_dossiers"] += 1
        a["ca_total_xof"] += d["ca_definitif_xof"]
        if d["depense_definitive_xof"] > 0:
            a["nb_imputes"] += 1
            a["ca_impute_xof"] += d["ca_definitif_xof"]
            a["depense_xof"] += d["depense_definitive_xof"]
            a["marge_xof"] += d["ca_definitif_xof"] - d["depense_definitive_xof"]

    annees = sorted(par_annee)[-nb_exercices:]
    points = []
    for an in annees:
        a = par_annee[an]
        couverture = pct(a["ca_impute_xof"], a["ca_total_xof"])
        points.append({
            "annee": an,
            "libelle": str(an),
            "ca_impute_xof": a["ca_impute_xof"],
            "depense_xof": a["depense_xof"],
            "marge_xof": a["marge_xof"],
            "taux_pct": pct(a["marge_xof"], a["ca_impute_xof"]),
            "nb_dossiers": a["nb_dossiers"],
            "nb_imputes": a["nb_imputes"],
            "couverture_pct": couverture,
            # Même seuil que la lecture du jour : sous cette couverture, le taux
            # existe mais n'est pas comparable aux autres exercices.
            "exploitable": couverture >= 40.0 and a["nb_imputes"] >= 5,
            "en_cours": an == aujourdhui.year,
        })

    exploitables = [p for p in points if p["exploitable"]]
    return {
        "source": statique.SOURCE_REELLE,
        "as_of": aujourdhui.isoformat(),
        "cible_pct": cible_pct,
        "points": points,
        "resume": {
            "nb_exercices": len(points),
            "nb_exploitables": len(exploitables),
            "taux_moyen_exploitable_pct": (
                round(sum(p["taux_pct"] for p in exploitables) / len(exploitables), 1)
                if exploitables else None
            ),
            "dernier_exercice_exploitable": exploitables[-1]["annee"] if exploitables else None,
        },
        "note": (
            "Un exercice n'est tracé plein que si la dépense est imputée sur une part suffisante de "
            "son chiffre d'affaires. En dessous, le taux reste affiché mais grisé : il est calculé "
            "sur trop peu de dossiers pour se comparer aux exercices voisins."
        ),
    }
