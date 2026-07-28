"""Teste generate_bid_strategy avec un LLM FACTICE (aucun appel réseau).

Vérifie : merge des actions LLM dans le squelette, PHASE_0 = préalables du scoring,
copie des appendices, passage du partenaire, sélection express, et fallback JSON invalide.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta

from core.domain.offer import (
    ScoringResult, BidRecommendation, MarketIdentity, EvaluationModalities,
    Precondition, Appendix, Partner,
)
from modules.uc10_presales.use_case import PresalesUseCase

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


class FakeLLM:
    """LLMGateway minimal : renvoie une réponse figée."""
    def __init__(self, response: str):
        self._r = response

    async def generate(self, system: str, user: str, max_tokens: int = 1024) -> str:
        self.last_user = user
        return self._r


def make_use_case(response: str) -> PresalesUseCase:
    uc = PresalesUseCase.__new__(PresalesUseCase)  # bypass __init__ (pas de deps réelles)
    uc._llm_sonnet = FakeLLM(response)
    return uc


def make_scoring(deadline: str) -> ScoringResult:
    return ScoringResult(
        ao_filename="AO-Test.pdf", summary="Résumé.", key_elements=[], matched_documents=[],
        gaps_analysis="", strengths=[], risks=[], score=70,
        recommendation=BidRecommendation.CONDITIONAL, justification="j",
        preconditions=[
            Precondition(label="Confirmer CA ≥ 500M FCFA", type="FINANCIER", blocking=True,
                         pieces_requises=["Bilan 2023", "Bilan 2024"]),
        ],
        appendices=[Appendix(code="5A", label="Déclaration de conformité", type="ADMIN")],
        market_identity=MarketIdentity(deadline_soumission=deadline),
        evaluation_modalities=EvaluationModalities(),
    )


_HAPPY = json.dumps({
    "strategy": "§1 ...\n\n§2 ...",
    "phases": [
        {"id": "PHASE_0", "actions": [
            {"day_label": "J1", "action": "Kick-off et décision Go", "responsable": "Directeur Commercial",
             "duree_estimee": "2h", "deliverable": "PV de décision"},
            {"day_label": "J1", "action": "", "responsable": "X"},  # action vide -> ignorée
        ]},
        {"id": "PHASE_3", "actions": [
            {"day_label": "J8", "action": "Rédaction technique", "responsable": "Équipe de rédaction technique"},
        ]},
        {"id": "PHASE_INCONNUE", "actions": [{"day_label": "J1", "action": "ignorée"}]},  # id hors squelette
    ],
    "response_plan": "§1 ...\n\n§2 ...",
}, ensure_ascii=False)


def test_happy_standard() -> None:
    far = (datetime.now() + timedelta(days=40)).strftime("%d/%m/%Y")
    uc = make_use_case(_HAPPY)
    partner = Partner(name="BI Corp", role="membre_groupement")
    bs = asyncio.run(uc.generate_bid_strategy(make_scoring(far), client_name="C", partner=partner))

    ids = [p.id for p in bs.phases]
    check(ids == ["PHASE_0", "PHASE_1", "PHASE_2", "PHASE_3", "PHASE_4"],
          f"standard attendu (5 phases), obtenu {ids}")
    p0 = next(p for p in bs.phases if p.id == "PHASE_0")
    check(len(p0.actions) == 1, f"PHASE_0 doit avoir 1 action (vide ignorée), a {len(p0.actions)}")
    check(p0.actions[0].deliverable == "PV de décision", "deliverable PHASE_0 mal mappé")
    p3 = next(p for p in bs.phases if p.id == "PHASE_3")
    check(len(p3.actions) == 1 and p3.actions[0].action == "Rédaction technique", "PHASE_3 mal mappée")
    p1 = next(p for p in bs.phases if p.id == "PHASE_1")
    check(p1.actions == [], "PHASE_1 (non remplie par le LLM) doit rester vide")
    # PHASE_0 validation = préalables du scoring (réutilisés)
    check(len(bs.partner_validation) == 1 and bs.partner_validation[0].pieces_requises == ["Bilan 2023", "Bilan 2024"],
          "partner_validation doit reprendre scoring.preconditions")
    check(bs.partner is not None and bs.partner.name == "BI Corp", "partenaire non transmis")
    check(len(bs.appendices) == 1 and bs.appendices[0].code == "5A", "appendices non copiés")
    check(bs.generated_at != "", "generated_at non renseigné")
    print(f"  happy/standard : {ids}, actions PHASE_0={len(p0.actions)}, partner_validation={len(bs.partner_validation)}")


def test_express_selection() -> None:
    soon = (datetime.now() + timedelta(days=3)).strftime("%d/%m/%Y")
    uc = make_use_case(_HAPPY)
    bs = asyncio.run(uc.generate_bid_strategy(make_scoring(soon)))
    ids = [p.id for p in bs.phases]
    check(ids == ["PHASE_0", "PHASE_1", "PHASE_2"], f"express attendu (3 phases), obtenu {ids}")
    print(f"  express        : {ids} (deadline J-3)")


def test_fallback() -> None:
    far = (datetime.now() + timedelta(days=40)).strftime("%d/%m/%Y")
    uc = make_use_case("ceci n'est pas du JSON valide { oops")
    bs = asyncio.run(uc.generate_bid_strategy(make_scoring(far)))
    check(len(bs.phases) == 5, "fallback doit garder le squelette (5 phases)")
    check(all(p.actions == [] for p in bs.phases), "fallback : phases sans actions")
    check(bs.strategy_text != "", "fallback : strategy_text non vide (message de secours)")
    check(len(bs.partner_validation) == 1, "fallback : préalables conservés")
    print(f"  fallback       : {len(bs.phases)} phases vides, strategy_text='{bs.strategy_text[:40]}...'")


def main() -> None:
    print("=" * 70)
    print("Pipeline stratégie (LLM factice)")
    print("=" * 70)
    test_happy_standard()
    test_express_selection()
    test_fallback()
    print("-" * 70)
    if failures:
        print(f"ÉCHEC ({len(failures)}) :")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("OK : merge actions, étape 0 = préalables, express, fallback — tout fonctionne.")


if __name__ == "__main__":
    main()
