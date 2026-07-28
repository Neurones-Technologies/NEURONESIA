"""GATE TOKEN — vérifie que le max_tokens de l'étape 1b-CADRE suffit pour sa sortie JSON.

Depuis le split de 1b, le CADRE (_step1b_extract_frame) ne produit plus que :
market_identity + calendar + evaluation_modalities + grille (8-15). Les annexes et les
exigences chiffrées sont parties dans 1b-EXIGENCES (cf. test_requirements_output_budget.py).
Sur Haiku, si l'output dépasse max_tokens il est TRONQUÉ → désormais OutputTruncatedError
(raise_on_truncation=True) → dégradation gracieuse (grille standard YAML).

Ce test NE fait AUCUN appel LLM. Il construit le pire cas réaliste et compte les tokens
avec le MÊME tokenizer que count_tokens() de l'adapter (tiktoken cl100k_base).
"""
import json
import sys

import tiktoken

MAX_TOKENS = 6000          # cf. ScoringPipeline._FRAME_OUTPUT_BUDGET_TOKENS
SAFETY_TARGET = 4800       # marge ~20% pour absorber l'écart tokenizer Claude/cl100k


def build_worst_case() -> dict:
    return {
        "market_identity": {
            "type_marche": "Marché public de prestation de services informatiques (accord-cadre)",
            "reference": "ADB/RFP/TCGS/2026/0104",
            "autorite_contractante": "Banque Africaine de Développement — Département des Services Généraux",
            "duree_contrat": "1 an renouvelable deux fois (36 mois maximum)",
            "date_demarrage": "à compter de la notification du marché",
            "deadline_soumission": "15/06/2026 à 15h00 GMT",
            "validite_offre": "120 jours à compter de la date limite de soumission",
            "perimetre_geographique": "Côte d'Ivoire, avec interventions ponctuelles dans la sous-région",
            "eligibilite_candidat": "Entreprises ou groupements régulièrement constitués, à jour de leurs obligations fiscales et sociales",
            "confidence": 0.9,
        },
        "calendar": [
            {"label": f"Jalon critique numéro {i} du calendrier de la consultation",
             "date": "01/06/2026", "criticite": "CRITIQUE",
             "source_section": "Section II — Calendrier de la consultation"}
            for i in range(10)
        ],
        "evaluation_modalities": {
            "ponderation_technique": 70,
            "ponderation_financiere": 30,
            "seuil_minimum_technique": 75,
            "formule_notation_financiere": "Nf = 100 × (Offre financière la moins-disante / Offre financière évaluée)",
            "modalites": ["Démonstration orale obligatoire devant le comité", "POC technique requis sur environnement de test", "Présentation de l'équipe projet"],
            "confidence": 0.8,
        },
        "criteria": [
            {"id": f"{(i // 3) + 1}.{(i % 3) + 1}",
             "label": "Qualification et expérience des profils clés proposés avec attestations de bonne fin",
             "max_points": 7, "category": "Ressources humaines et expérience", "is_inferred": False}
            for i in range(15)
        ],
    }


def main() -> None:
    enc = tiktoken.get_encoding("cl100k_base")  # identique à ClaudeHaikuAdapter.count_tokens
    payload = build_worst_case()
    # indent=2 : Claude émet du JSON INDENTÉ (cf. dumps data/debug/llm_failures). Mesurer en
    # compact (indent=None) sous-comptait les tokens et masquait la troncature réelle.
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    tokens = len(enc.encode(raw))

    print("=" * 70)
    print("GATE TOKEN — sortie JSON worst-case de l'étape 1b-CADRE (frame)")
    print("=" * 70)
    print(f"  calendar      : {len(payload['calendar'])} événements")
    print(f"  critères      : {len(payload['criteria'])}")
    print(f"  taille JSON   : {len(raw):,} chars")
    print(f"  tokens (cl100k): {tokens:,}")
    print(f"  budget max    : {MAX_TOKENS:,}")
    print(f"  cible (marge) : {SAFETY_TARGET:,}")
    print(f"  marge / budget: {(1 - tokens / MAX_TOKENS) * 100:.1f}%")
    print("-" * 70)

    if tokens >= MAX_TOKENS:
        print(f"ÉCHEC : {tokens} ≥ {MAX_TOKENS} — l'output SERAIT TRONQUÉ. Relever _FRAME_OUTPUT_BUDGET_TOKENS.")
        sys.exit(1)
    if tokens > SAFETY_TARGET:
        print(f"ALERTE : {tokens} tient sous {MAX_TOKENS} mais dépasse la cible {SAFETY_TARGET}.")
        print("        Marge insuffisante face à l'écart tokenizer Claude/cl100k.")
        sys.exit(2)
    print(f"OK : {tokens} tokens < cible {SAFETY_TARGET} < budget {MAX_TOKENS}. Marge confortable.")
    print(f"=> max_tokens={MAX_TOKENS} suffit pour 1b-CADRE.")


if __name__ == "__main__":
    main()
