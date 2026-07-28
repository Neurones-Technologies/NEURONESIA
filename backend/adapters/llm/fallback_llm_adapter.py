import logging
from typing import AsyncIterator

from core.ports.llm_gateway import LLMGateway, AgentStep, OutputTruncatedError

logger = logging.getLogger(__name__)

# Erreurs Anthropic qui déclenchent le fallback
_ANTHROPIC_FALLBACK_ERRORS: tuple = ()
try:
    import anthropic as _ant
    _ANTHROPIC_FALLBACK_ERRORS = (
        _ant.RateLimitError,
        _ant.AuthenticationError,
        _ant.InternalServerError,
        _ant.APIStatusError,
    )
except ImportError:
    pass

# Erreurs OpenAI qui déclenchent le fallback
_OPENAI_FALLBACK_ERRORS: tuple = ()
try:
    import openai as _oai
    _OPENAI_FALLBACK_ERRORS = (
        _oai.RateLimitError,
        _oai.AuthenticationError,
        _oai.InternalServerError,
        _oai.APIStatusError,
    )
except ImportError:
    pass

_FALLBACK_ERRORS = _ANTHROPIC_FALLBACK_ERRORS + _OPENAI_FALLBACK_ERRORS


class FallbackLLMAdapter(LLMGateway):
    """
    Wraps deux LLMs : si le primaire lève une erreur API (quota, auth, 5xx, overload),
    bascule automatiquement sur le secondaire sans interruption de service.

    Pour une chaîne à 3 niveaux (Claude → GPT → Ollama), imbriquer :
        FallbackLLMAdapter(
            primary=ClaudeHaikuAdapter(),
            fallback=FallbackLLMAdapter(
                primary=OpenAIGPTAdapter(),
                fallback=OllamaAdapter(),
            )
        )
    Le fallback interne (GPT → Ollama) se déclenche automatiquement si GPT est en quota.
    """

    def __init__(self, primary: LLMGateway, fallback: LLMGateway):
        self._primary = primary
        self._fallback = fallback
        self._primary_name = type(primary).__name__
        self._fallback_name = type(fallback).__name__

    def _should_fallback(self, exc: Exception) -> bool:
        # Troncature ≠ panne du provider : changer de LLM ne réglerait rien. On laisse remonter.
        if isinstance(exc, OutputTruncatedError):
            return False
        # Si la liste d'erreurs spécifiques est vide, fallback sur toute erreur
        if not _FALLBACK_ERRORS:
            return True
        # Anthropic overloaded_error (529) arrive parfois comme str dans l'exception
        if "overloaded_error" in str(exc).lower() or "overloaded" in str(exc).lower():
            return True
        return isinstance(exc, _FALLBACK_ERRORS)

    def _is_quota_error(self, exc: Exception) -> bool:
        """Détecte les erreurs de quota/crédits OpenAI — inutile de réessayer sur le même provider."""
        return "insufficient_quota" in str(exc).lower()

    async def generate(
        self, system: str, user: str, max_tokens: int = 1024,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        try:
            return await self._primary.generate(system, user, max_tokens, raise_on_truncation, temperature, cacheable)
        except Exception as primary_exc:
            if self._should_fallback(primary_exc):
                logger.warning("LLM primaire (%s) indisponible → fallback (%s) : %s",
                               self._primary_name, self._fallback_name, primary_exc)
                try:
                    return await self._fallback.generate(system, user, max_tokens, raise_on_truncation, temperature, cacheable)
                except Exception as fallback_exc:
                    if self._is_quota_error(fallback_exc):
                        logger.error("LLM fallback (%s) quota épuisé : %s", self._fallback_name, fallback_exc)
                        raise primary_exc  # plus utile que l'erreur quota OpenAI
                    raise
            raise

    async def stream(self, system: str, user: str, max_tokens: int = 1024) -> AsyncIterator[str]:
        try:
            async for token in self._primary.stream(system, user, max_tokens):
                yield token
        except Exception as e:
            if self._should_fallback(e):
                logger.warning("LLM stream primaire (%s) indisponible → fallback (%s) : %s",
                               self._primary_name, self._fallback_name, e)
                async for token in self._fallback.stream(system, user, max_tokens):
                    yield token
            else:
                raise

    async def extract(
        self, prompt: str, text: str, max_tokens: int = 512,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        try:
            return await self._primary.extract(prompt, text, max_tokens, raise_on_truncation, temperature, cacheable)
        except Exception as primary_exc:
            if self._should_fallback(primary_exc):
                logger.warning("LLM extract primaire → fallback : %s", primary_exc)
                try:
                    return await self._fallback.extract(prompt, text, max_tokens, raise_on_truncation, temperature, cacheable)
                except Exception as fallback_exc:
                    if self._is_quota_error(fallback_exc):
                        raise primary_exc
                    raise
            raise

    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        try:
            return await self._primary.classify(text, categories, default)
        except Exception as primary_exc:
            if self._should_fallback(primary_exc):
                logger.warning("LLM classify primaire → fallback : %s", primary_exc)
                try:
                    return await self._fallback.classify(text, categories, default)
                except Exception as fallback_exc:
                    if self._is_quota_error(fallback_exc):
                        raise primary_exc
                    raise
            raise

    async def agentic_step(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 1500,
    ) -> AgentStep:
        try:
            return await self._primary.agentic_step(system, messages, tools, max_tokens)
        except Exception as primary_exc:
            if self._should_fallback(primary_exc):
                logger.warning("LLM agentic_step primaire (%s) → fallback (%s) : %s",
                               self._primary_name, self._fallback_name, primary_exc)
                try:
                    return await self._fallback.agentic_step(system, messages, tools, max_tokens)
                except Exception as fallback_exc:
                    if self._is_quota_error(fallback_exc):
                        raise primary_exc
                    raise
            raise

    async def agentic_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 1000,
    ):
        primary_failed = False
        primary_exc = None
        try:
            async for event in self._primary.agentic_stream(system, messages, tools, max_tokens):
                yield event
            return
        except Exception as e:
            primary_failed = True
            primary_exc = e

        if primary_failed and self._should_fallback(primary_exc):
            logger.warning("LLM agentic_stream primaire (%s) → fallback (%s) : %s",
                           self._primary_name, self._fallback_name, primary_exc)
            try:
                async for event in self._fallback.agentic_stream(system, messages, tools, max_tokens):
                    yield event
            except Exception as fallback_exc:
                if self._is_quota_error(fallback_exc):
                    logger.error("LLM fallback (%s) quota épuisé : %s", self._fallback_name, fallback_exc)
                    raise primary_exc  # plus utile que l'erreur quota OpenAI
                raise
        elif primary_failed:
            raise primary_exc

    def count_tokens(self, text: str) -> int:
        return self._primary.count_tokens(text)

    @property
    def active_provider(self) -> str:
        return self._primary_name
