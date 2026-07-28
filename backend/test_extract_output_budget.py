"""GATE TOKEN — vérifie que le max_tokens de l'étape 1 suffit pour sa sortie JSON.

L'étape 1 (_step1_extract) produit en un seul JSON : key_points (5-10 objets
{label, value} aux valeurs longues) + 5 listes thématiques (criteres_selection,
besoins, prerequis, ressources_demandees, points_vigilance) + date_remise.
Sur un AO dense (type ABI/Commvault), ces listes montent à ~15 items chacune.
Si l'output dépasse max_tokens il est TRONQUÉ → JSON invalide → extraction vide
(`return [], empty_extra`) → tous les champs métier vides dans le résultat.

Ce test NE fait AUCUN appel LLM. Il construit le pire cas réaliste et compte les tokens
avec le MÊME tokenizer que count_tokens() de l'adapter (tiktoken cl100k_base), sur du
JSON INDENTÉ (comme Claude l'émet réellement — cf. dumps data/debug/llm_failures).

Si le gate échoue : relever max_tokens de _step1_extract.
"""
import json
import sys

import tiktoken

MAX_TOKENS = 8000          # cf. ScoringPipeline._step1_extract (relevé : items {texte, source_section})
SAFETY_TARGET = 6400       # marge ~20% pour absorber l'écart tokenizer Claude/cl100k

# Valeurs verbeuses représentatives d'un AO dense (FR avec accents) — cf. dump ABI réel.
_VALUE = (
    "Fourniture et déploiement d'une solution complète de sauvegarde basée exclusivement sur "
    "Commvault Complete Backup & Recovery pour postes de travail et serveurs, modèle autonome "
    "par filiale sans mutualisation inter-sites, avec immutabilité WORM et détection ransomware"
)
_ITEM = (
    "Présentation de minimum 5 attestations de bonne fin sur des projets similaires réalisés "
    "dans les trois dernières années, avec certifications Commvault et équipe pluridisciplinaire"
)


# Chaque item des 5 listes porte désormais {texte, source_section} (enrichissement
# traçabilité) → on modélise le pire cas avec une référence source réaliste.
_SOURCE = "Section III — Article 12.4 (page 8)"


def _obj():
    return {"texte": _ITEM, "source_section": _SOURCE}


def build_worst_case() -> dict:
    return {
        "key_points": [
            {"label": f"Point critique numéro {i + 1}", "value": _VALUE}
            for i in range(10)   # haut de la fourchette 5-10
        ],
        "criteres_selection": [_obj() for _ in range(15)],
        "besoins": [_obj() for _ in range(15)],
        "prerequis": [_obj() for _ in range(15)],
        "ressources_demandees": [_obj() for _ in range(13)],
        "points_vigilance": [_obj() for _ in range(15)],
        "date_remise": "15/06/2026 à 15h00 GMT",
    }


def main() -> None:
    enc = tiktoken.get_encoding("cl100k_base")  # identique à ClaudeHaikuAdapter.count_tokens
    payload = build_worst_case()
    # indent=2 : Claude émet du JSON indenté (cf. dumps). Mesurer compact sous-compterait.
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    tokens = len(enc.encode(raw))

    n_items = sum(
        len(payload[k]) for k in
        ("criteres_selection", "besoins", "prerequis", "ressources_demandees", "points_vigilance")
    )

    print("=" * 70)
    print("GATE TOKEN — sortie JSON worst-case de l'étape 1 (extract)")
    print("=" * 70)
    print(f"  key_points    : {len(payload['key_points'])}")
    print(f"  items listes  : {n_items} (5 listes thématiques)")
    print(f"  taille JSON   : {len(raw):,} chars")
    print(f"  tokens (cl100k): {tokens:,}")
    print(f"  budget max    : {MAX_TOKENS:,}")
    print(f"  cible (marge) : {SAFETY_TARGET:,}")
    print(f"  marge / budget: {(1 - tokens / MAX_TOKENS) * 100:.1f}%")
    print("-" * 70)

    if tokens >= MAX_TOKENS:
        print(f"ÉCHEC : {tokens} ≥ {MAX_TOKENS} — l'output SERAIT TRONQUÉ. Relever max_tokens.")
        sys.exit(1)
    if tokens > SAFETY_TARGET:
        print(f"ALERTE : {tokens} sous {MAX_TOKENS} mais > cible {SAFETY_TARGET} — marge juste.")
        sys.exit(2)
    print(f"OK : {tokens} tokens < cible {SAFETY_TARGET} < budget {MAX_TOKENS}. Marge confortable.")
    print(f"=> max_tokens={MAX_TOKENS} suffit pour l'étape 1 sur AO dense.")


if __name__ == "__main__":
    main()
