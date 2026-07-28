import logging
import httpx
from openai import AsyncOpenAI

from adapters.llm.openai_gpt_adapter import OpenAIGPTAdapter
from core.ports.llm_gateway import AgentStep
from config.settings import settings

logger = logging.getLogger(__name__)


class OllamaAdapter(OpenAIGPTAdapter):
    """
    Modèle local via Ollama (API compatible OpenAI).
    Sert de dernier recours si Anthropic ET OpenAI sont indisponibles.

    Modèles recommandés avec tool use :
      - llama3.1, llama3.2, mistral-nemo, qwen2.5 (7B+ pour les agrégats SQL)

    Installation : https://ollama.ai  →  ollama pull llama3.1
    """

    def __init__(self):
        # OpenAI SDK peut parler à Ollama avec base_url
        self._client = AsyncOpenAI(
            api_key="ollama",  # valeur quelconque — Ollama n'exige pas de clé
            base_url=settings.ollama_base_url + "/v1",
            timeout=settings.ollama_timeout_seconds,
        )
        self._model = settings.ollama_model
        # Encoder OpenAI pour estimation tokens (approximatif mais suffisant)
        import tiktoken
        self._encoder = tiktoken.get_encoding("cl100k_base")

    @classmethod
    async def is_available(cls) -> bool:
        """Vérifie si Ollama est démarré et le modèle est présent."""
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                resp = await c.get(settings.ollama_base_url + "/api/tags")
                if resp.status_code != 200:
                    return False
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                # Vérifie que le modèle demandé (ou son préfixe) est dispo
                return any(settings.ollama_model.split(":")[0] in m for m in models)
        except Exception:
            return False

    async def agentic_step(self, system, messages, tools, max_tokens=1500) -> AgentStep:
        """
        Tente le tool use Ollama. Si le modèle ne le supporte pas, génère du texte pur
        avec les données incluses dans le prompt système.
        """
        try:
            return await super().agentic_step(system, messages, tools, max_tokens)
        except Exception as e:
            # Certains modèles Ollama ne supportent pas le tool use → fallback texte
            if "does not support tools" in str(e).lower() or "function_call" in str(e).lower():
                logger.warning("Ollama tool use non supporté pour %s → mode texte seul", self._model)
                text = await self.generate(
                    system=system + "\n\n[Note: réponds directement sans utiliser d'outils]",
                    user=_messages_to_text(messages),
                    max_tokens=max_tokens,
                )
                return AgentStep(
                    stop_reason="end_turn",
                    text=text,
                    tool_calls=[],
                    assistant_message={"role": "assistant", "content": [{"type": "text", "text": text}]},
                )
            raise

    async def agentic_stream(self, system, messages, tools, max_tokens=1000):
        """Stream agentic identique à OpenAI (Ollama supporte le stream)."""
        try:
            async for event in super().agentic_stream(system, messages, tools, max_tokens):
                yield event
        except Exception as e:
            if "does not support tools" in str(e).lower() or "function_call" in str(e).lower():
                logger.warning("Ollama tool use non supporté → stream texte seul")
                text = ""
                async for token in self.stream(
                    system=system + "\n\n[Note: réponds directement sans utiliser d'outils]",
                    user=_messages_to_text(messages),
                    max_tokens=max_tokens,
                ):
                    text += token
                    yield {"type": "token", "content": token}
                yield {"type": "end", "text": text}
            else:
                raise


def _messages_to_text(messages: list[dict]) -> str:
    """Convertit l'historique de messages en texte simple pour les modèles sans tool use."""
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(f"{role}: {content}")
        elif isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                parts.append(f"{role}: {' '.join(texts)}")
    return "\n".join(parts) or "Question?"
