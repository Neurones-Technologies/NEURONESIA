"""Identité des commerciaux : texte libre Odoo → identité stable.

Section 6 du cadrage DC : « les commerciaux sont aujourd'hui de simples champs
texte, sans référentiel. Une même personne apparaît sous plusieurs orthographes,
et il n'existe aucune notion d'équipe, de manager ni de territoire. Un classement
fiable suppose de fiabiliser ce référentiel au préalable. »

Ce module fait ce préalable, et il le fait de façon VISIBLE : il ne se contente
pas de produire une liste propre, il rend compte de ce qu'il a dû décider. Trois
constats mesurés sur le miroir qu'il faut porter jusqu'à l'écran :

1. 28 orthographes dans `opportunities`, 36 dans `sale_orders`, avec des doublons
   de pure casse — « Segui Mireille  KOUADIO » et « SEGUI MIREILLE  KOUADIO »
   sont la même personne, et les compter séparément coupe son portefeuille en deux.
2. Des porteurs NON NOMINATIFS pèsent lourd : « Administrateur » porte 1 106
   opportunités, « Assistance Commerciale » 6 323 M FCFA de CA 2025 — près de la
   moitié du CA de l'exercice. Les exclure d'un classement individuel est correct ;
   les exclure SILENCIEUSEMENT laisserait croire que le classement couvre tout le
   CA. D'où `porteurs_non_nominatifs`, servi avec son poids.
3. Le rattachement automatique est une PROPOSITION. Il est écrit en base avec
   `confirmed = False` et le cockpit affiche combien d'alias restent non validés :
   c'est la marge d'erreur du palmarès.

Les fonctions sont pures ; la persistance est dans `queries.py`.
"""
from __future__ import annotations

import re
import unicodedata

# Porteurs qui ne sont pas des personnes. Classés par NATURE, car les deux cas ne
# se lisent pas pareil : un compte technique est une anomalie de saisie, une
# entité collective est une organisation commerciale réelle dont le CA existe
# bel et bien — il ne disparaît pas, il n'est simplement attribuable à personne.
NON_NOMINATIFS: dict[str, str] = {
    "ADMINISTRATEUR": "technique",
    "ADMIN": "technique",
    "USER TEST": "technique",
    "USERTEST": "technique",
    "USER_TEST": "technique",
    "ODOOBOT": "technique",
    "ODOO BOT": "technique",
    "ODOO AGENT": "technique",
    "ASSISTANCE COMMERCIALE": "collectif",
    "SERVICE COMMERCIAL": "collectif",
    "NEURONES ACADEMY": "collectif",
    "NEURONES TECHNOLOGIES": "collectif",
    "DIRECTION COMMERCIALE": "collectif",
}

MOTIFS_EXCLUSION = {
    "technique": "compte technique de l'ERP, pas un vendeur",
    "collectif": "entité collective : le CA existe mais n'est attribuable à aucune personne",
}


def normaliser(nom: str | None) -> str:
    """Clé de rapprochement : majuscules, sans accent, ponctuation et espaces réduits.

    `_` et `-` sont ramenés à l'espace pour que « User_test » et « User test »
    tombent sur la même clé. Volontairement PAS de rapprochement phonétique ni de
    distance d'édition : « KOUADIO » et « KOUADIA » peuvent être deux personnes,
    et un faux rapprochement fusionne deux portefeuilles sans laisser de trace.
    """
    if not nom:
        return ""
    decompose = unicodedata.normalize("NFKD", str(nom))
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    nettoye = re.sub(r"[_\-.,;']+", " ", sans_accent)
    return " ".join(nettoye.upper().split())


def _identifiant(cle: str) -> str:
    """Identifiant stable dérivé de la clé normalisée (jamais un compteur : un
    identifiant positionnel changerait au prochain import)."""
    return re.sub(r"[^a-z0-9]+", "-", cle.lower()).strip("-")[:120]


def construire_referentiel(noms_observes: list[dict]) -> dict:
    """Regroupe les orthographes observées en identités, et rend compte des choix.

    `noms_observes` : sortie de `queries.fetch_noms_commerciaux()`
    (`nom`, `occurrences`, `sources`).
    """
    groupes: dict[str, dict] = {}
    for entree in noms_observes:
        brut = (entree.get("nom") or "").strip()
        cle = normaliser(brut)
        if not cle:
            continue
        g = groupes.setdefault(cle, {
            "cle": cle,
            "orthographes": [],
            "occurrences": 0,
            "sources": set(),
        })
        g["orthographes"].append({"brut": brut, "occurrences": entree.get("occurrences", 0)})
        g["occurrences"] += entree.get("occurrences", 0)
        g["sources"].update(entree.get("sources") or [])

    personnes: list[dict] = []
    non_nominatifs: list[dict] = []
    # Les alias sont indexés par CLÉ NORMALISÉE et non par orthographe brute :
    # « Segui Mireille  KOUADIO » et « SEGUI MIREILLE  KOUADIO » tombent sur la
    # même clé, et la table `salesperson_aliases` porte un index unique dessus.
    # Émettre une ligne par orthographe brute violait cette contrainte — c'est
    # précisément le doublon de casse que ce module est censé résoudre.
    alias_par_cle: dict[str, dict] = {}

    for cle, g in sorted(groupes.items(), key=lambda kv: -kv[1]["occurrences"]):
        # L'orthographe retenue à l'affichage est la plus FRÉQUENTE, pas la
        # première rencontrée : « Segui Mireille  KOUADIO » (529 lignes) doit
        # gagner sur « SEGUI MIREILLE  KOUADIO » (201).
        orthographes = sorted(g["orthographes"], key=lambda o: -o["occurrences"])
        libelle = orthographes[0]["brut"]
        nature = NON_NOMINATIFS.get(cle)
        identifiant = _identifiant(cle)
        entree = {
            "salesperson_id": identifiant,
            "display_name": libelle,
            "cle": cle,
            "occurrences": g["occurrences"],
            "nb_orthographes": len(orthographes),
            "orthographes": [o["brut"] for o in orthographes],
            "sources": sorted(g["sources"]),
        }
        if nature:
            entree["nature"] = nature
            entree["motif"] = MOTIFS_EXCLUSION[nature]
            non_nominatifs.append(entree)
        else:
            personnes.append(entree)
        for o in orthographes:
            cle_alias = normaliser(o["brut"])
            existant = alias_par_cle.get(cle_alias)
            if existant is not None:
                # Même clé, orthographe différente : on cumule le volume et on
                # garde l'écriture la plus fréquente comme représentante.
                existant["occurrences"] += o["occurrences"]
                continue
            alias_par_cle[cle_alias] = {
                "alias_normalized": cle_alias,
                "alias_raw": o["brut"],
                # Un porteur non nominatif est rattaché à RIEN, volontairement :
                # l'exclusion est tracée en base au lieu d'être refaite en mémoire
                # à chaque lecture.
                "salesperson_id": None if nature else identifiant,
                "occurrences": o["occurrences"],
                "source_tables": sorted(g["sources"]),
            }

    # Doublons de casse : le signal le plus parlant pour le DC, car il montre que
    # deux lignes du classement d'aujourd'hui sont en réalité une seule personne.
    doublons = [
        {"display_name": p["display_name"], "orthographes": p["orthographes"]}
        for p in personnes if p["nb_orthographes"] > 1
    ]

    return {
        "personnes": personnes,
        "porteurs_non_nominatifs": non_nominatifs,
        "alias": sorted(alias_par_cle.values(), key=lambda a: -a["occurrences"]),
        "doublons_orthographe": doublons,
        "totaux": {
            "nb_orthographes_observees": len(noms_observes),
            "nb_personnes": len(personnes),
            "nb_non_nominatifs": len(non_nominatifs),
            "nb_doublons_orthographe": len(doublons),
        },
    }


def index_resolution(referentiel: dict) -> dict[str, dict]:
    """Clé normalisée → {salesperson_id, display_name, nature}.

    `nature` vaut `None` pour une personne, "technique" ou "collectif" pour un
    porteur exclu du classement nominatif.
    """
    index: dict[str, dict] = {}
    for p in referentiel["personnes"]:
        for orth in p["orthographes"]:
            index[normaliser(orth)] = {
                "salesperson_id": p["salesperson_id"],
                "display_name": p["display_name"],
                "nature": None,
            }
    for np_ in referentiel["porteurs_non_nominatifs"]:
        for orth in np_["orthographes"]:
            index[normaliser(orth)] = {
                "salesperson_id": np_["salesperson_id"],
                "display_name": np_["display_name"],
                "nature": np_["nature"],
            }
    return index


def resoudre(index: dict[str, dict], nom: str | None) -> dict:
    """Résolution d'un nom brut. Un nom inconnu n'est jamais écarté en silence :
    il ressort en nature "inconnu", ce qui le rend comptabilisable à l'écran."""
    cle = normaliser(nom)
    if not cle:
        return {"salesperson_id": None, "display_name": "(non renseigné)", "nature": "absent"}
    trouve = index.get(cle)
    if trouve:
        return trouve
    return {"salesperson_id": _identifiant(cle), "display_name": (nom or "").strip(), "nature": "inconnu"}
