"""GATE TOKEN — vérifie que le max_tokens de l'étape 1b-EXIGENCES suffit.

L'étape 1b-EXIGENCES (_step1b_extract_requirements) produit le JSON le plus volumineux
de l'extraction : appendices (~21) + profils RICHEMENT détaillés (~14, avec compétences,
certifications, missions) + seuils éligibilité + données financières. C'est exactement
pourquoi 1b a été scindée : tout ça dans un seul JSON tronquait au plafond.

Sur Haiku, si l'output dépasse max_tokens il est TRONQUÉ → OutputTruncatedError
(raise_on_truncation=True) → dégradation gracieuse (listes vides). Ce gate garantit que
le pire cas dense type BAD (14 profils) tient sous le budget AVEC marge.

Ce test NE fait AUCUN appel LLM (tiktoken cl100k_base, comme count_tokens de l'adapter).
"""
import json
import sys

import tiktoken

MAX_TOKENS = 16000         # cf. ScoringPipeline._REQUIREMENTS_OUTPUT_BUDGET_TOKENS
SAFETY_TARGET = 12800      # marge ~20% pour absorber l'écart tokenizer Claude/cl100k


def build_worst_case() -> dict:
    # 14 profils distincts richement détaillés (cas BAD : catalogue des 14 profils)
    profils = [
        {
            "profil": "Analyste Cybersécurité C-SOC senior avec spécialisation détection d'intrusion",
            "domaine": "Cybersécurité / Security Operations Center",
            "quantite": 1,
            "niveau": "Spécialiste — BAC+5 / Ingénieur grandes écoles",
            "experience_min": "2 à 4 ans d'expérience opérationnelle en SOC/CERT",
            "competences": [
                "Exploitation d'un SIEM (corrélation, règles de détection)",
                "Splunk (recherche, dashboards, alerting)",
                "Analyse d'incidents et réponse à incident (IR)",
                "Threat intelligence et chasse aux menaces",
            ],
            "certifications": ["CEH (Certified Ethical Hacker)", "CISSP", "Splunk Core Certified User"],
            "missions": [
                "Surveillance continue du C-SOC en rotation 24h/7j",
                "Qualification et escalade des alertes de sécurité",
                "Rédaction des rapports d'incident et recommandations",
            ],
            "rattachement": "Division Cybersécurité TCIS6",
            "source_section": "Section IV — Termes de référence, profil 14",
        }
        for _ in range(14)
    ]
    appendices = [
        {"code": f"Appendice 5{chr(65 + (i % 14))}",
         "label": "Déclaration de garantie de soumission signée et cachetée, valide 28 jours au-delà de la validité de l'offre",
         "type": "ADMIN", "obligatoire": True, "langue": "FR",
         "source_section": "Section III — Pièces constitutives, Appendice 5D"}
        for i in range(21)
    ]
    seuils = [
        {"libelle": "Chiffre d'affaires annuel moyen minimum sur les 3 derniers exercices",
         "valeur": "500 000 000", "unite": "FCFA/an", "type": "FINANCIER",
         "blocking": True, "source_section": "Section III, Appendice 5D, critère éliminatoire"}
        for _ in range(5)
    ]
    return {
        "appendices": appendices,
        "profils_demandes": profils,
        "seuils_eligibilite": seuils,
        "donnees_financieres": {
            "budget_estime": "Non communiqué dans le dossier de consultation",
            "modalites_paiement": "30% à la notification, 70% à la réception définitive sous 30 jours",
            "garantie_soumission": "Caution bancaire de 2% du montant de l'offre, valide 120 jours",
            "penalites": "Pénalités de retard de 1/1000 du montant par jour, plafonnées à 10%",
            "source_section": "Section V — Conditions financières",
        },
    }


def main() -> None:
    enc = tiktoken.get_encoding("cl100k_base")
    payload = build_worst_case()
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    tokens = len(enc.encode(raw))

    print("=" * 70)
    print("GATE TOKEN — sortie JSON worst-case de l'étape 1b-EXIGENCES")
    print("=" * 70)
    print(f"  profils       : {len(payload['profils_demandes'])} (richement détaillés)")
    print(f"  appendices    : {len(payload['appendices'])}")
    print(f"  seuils        : {len(payload['seuils_eligibilite'])}")
    print(f"  taille JSON   : {len(raw):,} chars")
    print(f"  tokens (cl100k): {tokens:,}")
    print(f"  budget max    : {MAX_TOKENS:,}")
    print(f"  cible (marge) : {SAFETY_TARGET:,}")
    print(f"  marge / budget: {(1 - tokens / MAX_TOKENS) * 100:.1f}%")
    print("-" * 70)

    if tokens >= MAX_TOKENS:
        print(f"ÉCHEC : {tokens} ≥ {MAX_TOKENS} — l'output SERAIT TRONQUÉ. Relever _REQUIREMENTS_OUTPUT_BUDGET_TOKENS.")
        sys.exit(1)
    if tokens > SAFETY_TARGET:
        print(f"ALERTE : {tokens} tient sous {MAX_TOKENS} mais dépasse la cible {SAFETY_TARGET}.")
        print("        Marge insuffisante face à l'écart tokenizer Claude/cl100k.")
        sys.exit(2)
    print(f"OK : {tokens} tokens < cible {SAFETY_TARGET} < budget {MAX_TOKENS}. Marge confortable.")
    print(f"=> max_tokens={MAX_TOKENS} suffit pour 1b-EXIGENCES (14 profils détaillés).")


if __name__ == "__main__":
    main()
