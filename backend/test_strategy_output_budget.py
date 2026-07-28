"""GATE TOKEN — vérifie que max_tokens=4000 suffit pour la sortie JSON de la stratégie.

generate_bid_strategy demande à Sonnet : strategy (5§) + phases (jusqu'à 5 × 4 actions)
+ response_plan (4§). Si l'output dépasse max_tokens → tronqué → JSON invalide → fallback
(squelette sans actions). Ce test NE fait AUCUN appel LLM : il construit le pire cas
réaliste (squelette standard = 5 phases, 4 actions chacune) et compte les tokens avec le
même tokenizer proxy (cl100k_base).
"""
import json
import sys

import tiktoken

MAX_TOKENS = 4000
SAFETY_TARGET = 3200       # marge ~20% pour l'écart tokenizer Claude/cl100k (accents FR)

_PARA = (
    "Lecture stratégique de l'appel d'offres : le commanditaire cherche un partenaire "
    "capable de sécuriser son infrastructure critique tout en maîtrisant les délais ; "
    "Neurones se positionne sur sa double expertise infrastructure et cybersécurité, "
    "avec des références bancaires comparables et une présence locale différenciante."
)
_ACTION = "Rédaction du corpus technique : méthodologie d'intervention, planning projet détaillé et fiches profils"


def build_worst_case() -> dict:
    phases = []
    for i in range(5):  # squelette standard = 5 phases (le plus volumineux)
        phases.append({
            "id": f"PHASE_{i}",
            "actions": [
                {
                    "day_label": f"J{i * 3 + j + 1}",
                    "action": _ACTION,
                    "responsable": "Responsable Administratif & Juridique",
                    "duree_estimee": "1 journée",
                    "deliverable": "Document validé et archivé dans l'espace projet partagé",
                }
                for j in range(4)  # 4 actions par phase (haut de la fourchette)
            ],
        })
    return {
        "strategy": "\\n\\n".join(f"§{k + 1} — {_PARA}" for k in range(5)),
        "phases": phases,
        "response_plan": "\\n\\n".join(f"§{k + 1} — {_PARA}" for k in range(4)),
    }


def main() -> None:
    enc = tiktoken.get_encoding("cl100k_base")
    payload = build_worst_case()
    raw = json.dumps(payload, ensure_ascii=False, indent=None)
    tokens = len(enc.encode(raw))
    n_actions = sum(len(p["actions"]) for p in payload["phases"])

    print("=" * 70)
    print("GATE TOKEN — sortie JSON worst-case de generate_bid_strategy")
    print("=" * 70)
    print(f"  phases        : {len(payload['phases'])} ({n_actions} actions)")
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
    print(f"=> max_tokens={MAX_TOKENS} suffit pour la stratégie 5 phases.")


if __name__ == "__main__":
    main()
