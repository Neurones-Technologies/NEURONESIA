import logging

import tiktoken

logger = logging.getLogger(__name__)

_COST_PER_1K = {
    "claude-haiku-4-5-20251001": {"input": 0.25, "output": 1.25, "cached": 0.03},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cached": 0.3},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0, "cached": 0.0},
}

_USD_TO_FCFA = 600


class TokenBudgetManager:
    """Contrôle la consommation de tokens et alerte si le budget mensuel est dépassé."""

    def __init__(self, monthly_budget_fcfa: int, alert_threshold_pct: int = 80):
        self._budget = monthly_budget_fcfa
        self._alert_threshold = monthly_budget_fcfa * alert_threshold_pct / 100
        self._encoder = tiktoken.get_encoding("cl100k_base")
        self._total_cost_fcfa = 0.0

    def estimate_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def compute_cost_fcfa(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> float:
        rates = _COST_PER_1K.get(model, _COST_PER_1K["claude-haiku-4-5-20251001"])
        cost_usd = (
            (input_tokens - cached_tokens) / 1000 * rates["input"]
            + cached_tokens / 1000 * rates["cached"]
            + output_tokens / 1000 * rates["output"]
        )
        return round(cost_usd * _USD_TO_FCFA, 2)

    def log_usage(self, use_case: str, model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0):
        cost = self.compute_cost_fcfa(model, input_tokens, output_tokens, cached_tokens)
        self._total_cost_fcfa += cost
        logger.info(
            "Tokens [%s|%s] in=%d out=%d cached=%d → %.0f FCFA (total mois: %.0f/%.0f FCFA)",
            use_case, model, input_tokens, output_tokens, cached_tokens,
            cost, self._total_cost_fcfa, self._budget,
        )
        if self._total_cost_fcfa >= self._alert_threshold:
            logger.warning(
                "ALERTE BUDGET : %.0f FCFA utilisés sur %.0f FCFA (%.0f%%)",
                self._total_cost_fcfa, self._budget,
                self._total_cost_fcfa / self._budget * 100,
            )

    def is_within_budget(self) -> bool:
        return self._total_cost_fcfa < self._budget

    def reset_monthly(self):
        logger.info("Reset budget mensuel (ancien total: %.0f FCFA)", self._total_cost_fcfa)
        self._total_cost_fcfa = 0.0
