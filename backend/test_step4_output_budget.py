"""GATE TOKEN — vérifie que max_tokens=20000 suffit pour la sortie JSON de step4.

Le nouveau _step4_analyze produit un JSON bien plus volumineux qu'avant :
grille scorée (8-15 critères) + risques avec mitigation + préalables.
Sur Haiku, si l'output dépasse max_tokens il est TRONQUÉ → JSON invalide → fallback score=50.

Ce test NE fait AUCUN appel LLM. Il construit le pire cas réaliste (15 critères avec
justifications verbeuses en français, 5 risques complets, 5 préalables), puis compte les
tokens avec le MÊME tokenizer que count_tokens() de l'adapter (tiktoken cl100k_base).

Verdict : l'output doit tenir sous max_tokens AVEC marge (cl100k ≈ proxy de Claude ;
les accents FR peuvent coûter un peu plus → on exige ~20% de marge).
"""
import json
import sys

import tiktoken

MAX_TOKENS = 20000         # cf. ScoringPipeline._ANALYZE_OUTPUT_BUDGET_TOKENS
SAFETY_TARGET = 16000      # marge ~20% pour absorber l'écart tokenizer Claude/cl100k

# Chaînes verbeuses représentatives (worst-case crédible, FR avec accents)
_RATIONALE = (
    "Nous disposons de références solides sur ce périmètre mais il manque une attestation "
    "de bonne fin récente ; le score est plafonné car deux des trois projets cités datent "
    "de plus de trois ans et le volume traité reste inférieur à l'exigence de l'AO."
)
_MITIGATION = (
    "Constituer un groupement avec un partenaire BI disposant des CVs certifiés manquants, "
    "et joindre les attestations de bonne fin des projets Ecobank et SGBCI pour combler l'écart."
)
_POURQUOI = (
    "Vingt points de la grille dépendent de livrables analytiques concrets que nos références "
    "actuelles ne couvrent que partiellement, ce qui fragilise la note technique globale."
)


def build_worst_case() -> dict:
    criteria = [
        {
            "id": f"{(i // 3) + 1}.{(i % 3) + 1}",
            "estimated_score": 7,
            "risk_level": "CRITIQUE",
            "rationale": _RATIONALE,
            "sources_ged": [
                "Offre-SGBCI-Infrastructure-2024.docx",
                "CV-Konan-Expert-Cloud.docx",
                "Offre-Ecobank-Datacenter-2023.docx",
            ],
        }
        for i in range(15)  # 15 = haut de la fourchette 8-15
    ]
    risks = [
        {
            "label": "Absence de livrables BI/Analytics démontrables sur les trois dernières années",
            "criticite": "CRITIQUE",
            "pourquoi": _POURQUOI,
            "mitigation": _MITIGATION,
            "items_affected": ["3.3", "7.1", "2.2"],
        }
        for _ in range(5)
    ]
    preconditions = [
        {
            "label": "Confirmer un chiffre d'affaires consolidé supérieur ou égal à 500 millions FCFA",
            "type": "FINANCIER",
            "deadline": "avant J-5 ouvrés précédant la remise de l'offre",
            "responsable": "Responsable Financier / Direction Administrative et Financière",
            "blocking": True,
        }
        for _ in range(5)
    ]
    return {
        "criteria": criteria,
        "gaps_analysis": _RATIONALE + " " + _POURQUOI,
        "strengths": [
            "Expertise reconnue en virtualisation et infrastructure bancaire (VMware, Nutanix).",
            "Équipe certifiée AWS Solutions Architect et VMware VCP disponible immédiatement.",
            "Références multiples sur le secteur bancaire ouest-africain (Ecobank, SGBCI).",
            "Méthodologie de migration éprouvée avec SLA 99.9% tenus sur projets antérieurs.",
            "Capacité de mobilisation rapide d'une équipe pluridisciplinaire.",
            "Maîtrise des contraintes réglementaires et de conformité du secteur financier.",
        ],
        "risks": risks,
        "recommendation": "CONDITIONAL",
        "justification": (
            "Le dossier présente une forte adéquation technique mais reste conditionné à la "
            "constitution d'un groupement et à la confirmation des seuils financiers exigés."
        ),
        "preconditions": preconditions,
    }


def main() -> None:
    enc = tiktoken.get_encoding("cl100k_base")  # identique à ClaudeHaikuAdapter.count_tokens
    payload = build_worst_case()
    # ensure_ascii=False + indent=2 : c'est ainsi que Claude produit réellement l'output
    # (JSON indenté, cf. dumps data/debug/llm_failures). Mesurer compact sous-comptait.
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    tokens = len(enc.encode(raw))

    print("=" * 70)
    print("GATE TOKEN — sortie JSON worst-case de _step4_analyze")
    print("=" * 70)
    print(f"  critères      : {len(payload['criteria'])}")
    print(f"  risques       : {len(payload['risks'])}")
    print(f"  préalables    : {len(payload['preconditions'])}")
    print(f"  forces        : {len(payload['strengths'])}")
    print(f"  taille JSON   : {len(raw):,} chars")
    print(f"  tokens (cl100k): {tokens:,}")
    print(f"  budget max    : {MAX_TOKENS:,}")
    print(f"  cible (marge) : {SAFETY_TARGET:,}")
    headroom = (1 - tokens / MAX_TOKENS) * 100
    print(f"  marge / budget: {headroom:.1f}%")
    print("-" * 70)

    if tokens >= MAX_TOKENS:
        print(f"ÉCHEC : {tokens} ≥ {MAX_TOKENS} — l'output SERAIT TRONQUÉ. Augmenter max_tokens.")
        sys.exit(1)
    if tokens > SAFETY_TARGET:
        print(f"ALERTE : {tokens} tient sous {MAX_TOKENS} mais dépasse la cible {SAFETY_TARGET}.")
        print("        Marge insuffisante face à l'écart tokenizer Claude/cl100k — à surveiller.")
        sys.exit(2)
    print(f"OK : {tokens} tokens < cible {SAFETY_TARGET} < budget {MAX_TOKENS}. Marge confortable.")
    print(f"=> max_tokens={MAX_TOKENS} suffit pour le pire cas. Feu vert pour l'export Word.")


if __name__ == "__main__":
    main()
