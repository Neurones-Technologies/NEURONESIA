"""Vérifie les 2 squelettes YAML de phases + la sélection standard/express.

NE fait AUCUN appel LLM. Valide la structure des YAML (ids uniques, dépendances
cohérentes, PHASE_0 bloquante) et la bascule express sur la deadline.
"""
import sys

from modules.uc10_presales.use_case import load_strategy_skeleton, _EXPRESS_THRESHOLD_DAYS

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def validate(variant_label: str, config: dict, phases: list) -> None:
    ids = [p.id for p in phases]
    check(len(ids) == len(set(ids)), f"{variant_label}: ids de phases non uniques: {ids}")
    check(ids and ids[0] == "PHASE_0", f"{variant_label}: la première phase doit être PHASE_0")
    check(phases[0].is_blocking_next, f"{variant_label}: PHASE_0 doit être bloquante")
    check(not phases[0].prerequisites, f"{variant_label}: PHASE_0 ne doit pas avoir de prérequis")
    # Les prérequis doivent référencer des phases existantes
    id_set = set(ids)
    for p in phases:
        for pre in p.prerequisites:
            check(pre in id_set, f"{variant_label}: prérequis inconnu '{pre}' dans {p.id}")
        check(p.start_day.startswith("J") and p.end_day.startswith("J"),
              f"{variant_label}: jours non calculés pour {p.id}")
    # Chaque phase du YAML a des typical_actions (guide pour le LLM)
    for raw in config.get("phases", []):
        check(bool(raw.get("typical_actions")),
              f"{variant_label}: typical_actions manquantes pour {raw.get('id')}")
    print(f"  {variant_label}: {len(phases)} phases - {' > '.join(ids)}")


def main() -> None:
    print("=" * 70)
    print("Squelettes de phases — structure + sélection")
    print("=" * 70)

    # Standard : pas de deadline ou deadline lointaine
    cfg_std, ph_std = load_strategy_skeleton(days_remaining=None)
    validate("standard", cfg_std, ph_std)
    check(len(ph_std) == 5, f"standard doit avoir 5 phases, a {len(ph_std)}")
    check(cfg_std.get("variant") == "standard", "variant standard attendu")

    cfg_std2, ph_std2 = load_strategy_skeleton(days_remaining=30)
    check([p.id for p in ph_std2] == [p.id for p in ph_std], "deadline lointaine = standard")

    # Express : deadline proche
    cfg_exp, ph_exp = load_strategy_skeleton(days_remaining=4)
    validate("express", cfg_exp, ph_exp)
    check(len(ph_exp) == 3, f"express doit avoir 3 phases, a {len(ph_exp)}")
    check(cfg_exp.get("variant") == "express", "variant express attendu")

    # Bascule exactement au seuil
    _, ph_threshold = load_strategy_skeleton(days_remaining=_EXPRESS_THRESHOLD_DAYS)
    check(len(ph_threshold) == 5, f"à J-{_EXPRESS_THRESHOLD_DAYS} (= seuil) on reste standard")
    _, ph_below = load_strategy_skeleton(days_remaining=_EXPRESS_THRESHOLD_DAYS - 1)
    check(len(ph_below) == 3, f"à J-{_EXPRESS_THRESHOLD_DAYS - 1} (< seuil) on passe express")

    print("-" * 70)
    if failures:
        print(f"ÉCHEC ({len(failures)}) :")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("OK : les 2 squelettes sont structurellement valides et la sélection fonctionne.")


if __name__ == "__main__":
    main()
