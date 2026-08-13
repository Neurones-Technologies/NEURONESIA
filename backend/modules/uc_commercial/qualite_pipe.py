"""Opportunités à closer et opportunités à compléter — §4 du compte-rendu DC.

Le CR distingue « les opportunités à closer (finalisation en cours) » et « les
opportunités à compléter (informations manquantes ou dossier incomplet) ». Aucune
des deux notions n'existe dans Odoo : il faut les DÉFINIR, et la définition doit
être lisible à l'écran, sinon le DC conteste un chiffre dont il ignore la règle.

Règle de complétude retenue, faute de règle d'équipe admise (question 40 du
cadrage) : une opportunité ouverte est incomplète dès qu'un des quatre champs qui
la rendent pilotable manque. Les quatre sont pondérés par leur CONSÉQUENCE, pas
par goût :

- ÉCHÉANCE ABSENTE : l'affaire n'apparaît dans aucun trimestre de forecast. C'est
  le défaut le plus coûteux — il fausse directement le chiffre annoncé.
- MONTANT nul : l'affaire ne pèse rien dans le forecast alors qu'elle existe.
- CLIENT non rattaché au référentiel : l'affaire n'est rattachable à aucun compte,
  donc à aucune animation de portefeuille.
- LIBELLÉ non qualifiant : le libellé ne dit pas ce qui est vendu, donc l'affaire
  ne se ventile dans aucune famille d'offre ni aucun axe de marché.

L'ÉCHÉANCE DÉPASSÉE est délibérément SORTIE de la complétude, dans un troisième
panier (`a_requalifier`). Mesuré sur ce pipe : 4 903 des 5 030 opportunités
ouvertes portent une échéance absente ou dépassée, dont 4 276 dépassées. Les
compter comme « incomplètes » ferait un indicateur qui signale 98 % du pipe — donc
aucun indicateur du tout, et une liste de travail inutilisable. Ce sont d'ailleurs
deux gestes différents : compléter un dossier, ou reprendre une date qui n'a pas
été tenue à jour.

Le COMMERCIAL manquant est compté à part pour la même raison de nature : c'est un
défaut d'attribution, pas de qualification, et il se corrige dans le référentiel,
pas dans le dossier.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime

from modules.uc_commercial.comptes import est_ouverte

# Étapes qui signent une finalisation en cours. Détectées par MOTIF sur l'étape
# normalisée : le référentiel Odoo porte « 4-Négociation », « Negotiation »,
# « 5-Décision », et les comparer par égalité en perdrait la moitié.
MOTIFS_A_CLOSER = ("negoc", "decision", "closing", "signature", "contrat", "commande")
# Une échéance à moins de 45 jours vaut aussi « à closer », quelle que soit
# l'étape : sur ce pipe, l'étape est souvent moins à jour que la date.
HORIZON_A_CLOSER_JOURS = 45

POIDS_DEFAUTS = {
    "echeance_absente": 3,
    "montant": 2,
    "client": 2,
    "libelle": 1,
}

LIBELLE_DEFAUTS = {
    "echeance_absente": "aucune échéance renseignée",
    "montant": "montant nul",
    "client": "compte non rattaché au référentiel",
    "libelle": "libellé ne disant pas ce qui est vendu",
}


def _parse_date(valeur: str | None) -> date | None:
    if not valeur:
        return None
    try:
        return datetime.strptime(str(valeur)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalise(texte: str | None) -> str:
    """Minuscules, SANS ACCENT, tirets et espaces réduits.

    L'accent n'est pas cosmétique ici : les étapes réelles du miroir s'écrivent
    « 4-Négociation » et « 5-Décision ». Un motif « negoc » comparé à une chaîne
    accentuée ne matche jamais — le critère « étape de finalisation » restait
    silencieusement vide, et « à closer » se réduisait aux échéances proches.
    """
    d = unicodedata.normalize("NFKD", (texte or "").lower())
    sans_accent = "".join(c for c in d if not unicodedata.combining(c))
    return " ".join(sans_accent.replace("-", " ").split())


def build_qualite_pipe(opportunites: list[dict], today: date | None = None, limit: int = 12) -> dict:
    """Sépare le pipe ouvert en « à closer », « à compléter » et « à requalifier ».

    Une affaire peut figurer dans plusieurs paniers : proche de la signature ET
    incomplète, c'est même le cas le plus urgent, signalé par `prioritaire`.
    """
    jour = today or date.today()
    ouvertes = [o for o in opportunites if est_ouverte(o.get("stage"))]

    a_closer: list[dict] = []
    a_completer: list[dict] = []
    a_requalifier: list[dict] = []
    compteur_defauts = {k: 0 for k in POIDS_DEFAUTS}
    sans_commercial = 0
    nb_echeance_depassee = 0

    for o in ouvertes:
        echeance = _parse_date(o.get("deadline"))
        etape = _normalise(o.get("stage"))
        montant = o.get("montant_xof", 0)
        depassee = echeance is not None and echeance < jour
        if depassee:
            nb_echeance_depassee += 1

        defauts: list[str] = []
        if echeance is None:
            defauts.append("echeance_absente")
        if not montant:
            defauts.append("montant")
        if not (o.get("client_id") or "").strip():
            defauts.append("client")
        if not (o.get("famille") or "").strip():
            defauts.append("libelle")
        for d in defauts:
            compteur_defauts[d] += 1
        if not (o.get("commercial") or "").strip():
            sans_commercial += 1

        proche = echeance is not None and jour <= echeance <= _plus_jours(jour, HORIZON_A_CLOSER_JOURS)
        etape_finale = any(m in etape for m in MOTIFS_A_CLOSER)
        gravite = sum(POIDS_DEFAUTS[d] for d in defauts)

        ligne = {
            "opp_id": o.get("opp_id"),
            "name": o.get("name"),
            "client": o.get("client") or "(client non renseigné)",
            "stage": o.get("stage") or "",
            "montant_xof": montant,
            "probabilite_pct": o.get("probabilite_pct", 0),
            "commercial": o.get("commercial") or "",
            "deadline": o.get("deadline"),
            "jours_avant_echeance": (echeance - jour).days if echeance else None,
            "jours_de_retard": (jour - echeance).days if depassee else None,
            "echeance_depassee": depassee,
            "defauts": defauts,
            "defauts_libelles": [LIBELLE_DEFAUTS[d] for d in defauts],
            "gravite": gravite,
        }

        if (etape_finale or proche) and echeance is not None and echeance >= jour:
            a_closer.append({**ligne, "motif_closer": "étape de finalisation" if etape_finale else "échéance proche",
                             "prioritaire": bool(defauts)})
        if defauts:
            a_completer.append(ligne)
        if depassee:
            a_requalifier.append(ligne)

    a_closer.sort(key=lambda l: (-l["montant_xof"],))
    a_completer.sort(key=lambda l: (-l["gravite"], -l["montant_xof"]))
    # Le panier « à requalifier » se trie par MONTANT et non par ancienneté : ce
    # qui fausse le forecast, c'est le poids de l'affaire, pas son retard.
    a_requalifier.sort(key=lambda l: -l["montant_xof"])

    montant_ouvert = sum(o.get("montant_xof", 0) for o in ouvertes)
    montant_a_closer = sum(l["montant_xof"] for l in a_closer)
    montant_a_completer = sum(l["montant_xof"] for l in a_completer)
    montant_a_requalifier = sum(l["montant_xof"] for l in a_requalifier)

    return {
        "as_of": jour.isoformat(),
        "totaux": {
            "nb_ouvertes": len(ouvertes),
            "montant_ouvert_xof": montant_ouvert,
            "nb_a_closer": len(a_closer),
            "montant_a_closer_xof": montant_a_closer,
            "nb_a_completer": len(a_completer),
            "montant_a_completer_xof": montant_a_completer,
            "part_a_completer_pct": round(100 * len(a_completer) / len(ouvertes), 1) if ouvertes else 0.0,
            "part_montant_a_completer_pct": round(100 * montant_a_completer / montant_ouvert, 1) if montant_ouvert else 0.0,
            "nb_a_requalifier": len(a_requalifier),
            "montant_a_requalifier_xof": montant_a_requalifier,
            "part_montant_a_requalifier_pct": round(100 * montant_a_requalifier / montant_ouvert, 1) if montant_ouvert else 0.0,
            "nb_echeance_depassee": nb_echeance_depassee,
            "nb_prioritaires": sum(1 for l in a_closer if l["prioritaire"]),
            "nb_sans_commercial": sans_commercial,
        },
        "a_closer": a_closer[:limit],
        "a_completer": a_completer[:limit],
        "a_requalifier": a_requalifier[:limit],
        "defauts": [
            {
                "code": code,
                "libelle": LIBELLE_DEFAUTS[code],
                "poids": POIDS_DEFAUTS[code],
                "nb_opportunites": nb,
                "part_pct": round(100 * nb / len(ouvertes), 1) if ouvertes else 0.0,
            }
            for code, nb in sorted(compteur_defauts.items(), key=lambda kv: -kv[1])
        ],
        "regle": {
            "horizon_closer_jours": HORIZON_A_CLOSER_JOURS,
            "motifs_etape_closer": list(MOTIFS_A_CLOSER),
            "champs_completude": LIBELLE_DEFAUTS,
        },
        "note": (
            "Aucune règle de complétude n'existe aujourd'hui dans l'équipe : celle appliquée ici est une "
            "proposition, affichée pour être discutée. « À closer » retient les affaires en étape de "
            f"finalisation OU à moins de {HORIZON_A_CLOSER_JOURS} jours d'échéance — sur ce pipe, l'étape est "
            "souvent moins à jour que la date. L'échéance DÉPASSÉE n'est pas comptée comme un défaut de "
            "complétude mais dans un panier séparé : compléter un dossier et reprendre une date non tenue "
            "sont deux gestes différents, et confondre les deux produirait un indicateur qui signale la "
            "quasi-totalité du pipe. Le commercial manquant est compté à part : c'est un défaut "
            "d'attribution, pas de qualification."
        ),
    }


def _plus_jours(jour: date, n: int) -> date:
    from datetime import timedelta
    return jour + timedelta(days=n)
