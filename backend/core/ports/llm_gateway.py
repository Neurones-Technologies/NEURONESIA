from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class AgentStep:
    """Résultat normalisé d'une étape de l'agentic loop — indépendant du fournisseur LLM."""
    stop_reason: str          # "end_turn" | "tool_use"
    text: str                 # contenu textuel de cette étape
    tool_calls: list[dict]    # [{"id": str, "name": str, "input": dict}]
    assistant_message: dict   # message assistant en format Anthropic (prêt à append aux messages)


class OutputTruncatedError(RuntimeError):
    """Sortie coupée net au plafond `max_tokens` (stop_reason=max_tokens).

    Tout JSON aval est alors invalide. Levée UNIQUEMENT quand l'appelant passe
    `raise_on_truncation=True` (les appels qui tolèrent une réponse partielle —
    chat, classification — ne la déclenchent pas). `partial_text` porte la sortie
    incomplète pour un éventuel parse de récupération.
    """

    def __init__(self, partial_text: str, max_tokens: int):
        super().__init__(f"Sortie LLM tronquée au plafond de {max_tokens} tokens")
        self.partial_text = partial_text
        self.max_tokens = max_tokens


class LLMGateway(ABC):
    """Interface abstraite pour tout LLM — logique métier indépendante du fournisseur."""

    @abstractmethod
    async def generate(
        self, system: str, user: str, max_tokens: int = 1024,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        """Génère une réponse complète.

        Si `raise_on_truncation=True` et que la sortie est coupée au plafond
        `max_tokens`, lève `OutputTruncatedError` au lieu de renvoyer un texte
        incomplet silencieusement.

        `temperature` : None = défaut du fournisseur. 0 = quasi-déterministe (extraction,
        notation reproductibles) ; ~0.7 pour la rédaction créative (stratégie, offre).

        `cacheable` : marque `user` comme point de coupure de prompt caching (Anthropic
        uniquement — no-op ailleurs). À réserver aux appels où le MÊME `user` (identique
        au caractère près) sera renvoyé à nouveau dans les ~5 minutes qui suivent — un
        retry sur troncature (même contenu, budget de sortie élargi) ou une ré-analyse
        forcée du même document. Sans réutilisation réelle, ça ajoute un surcoût d'écriture
        (+25%) pour rien : ne pas l'activer par défaut sur tous les appels."""

    @abstractmethod
    async def stream(self, system: str, user: str, max_tokens: int = 1024) -> AsyncIterator[str]:
        """Génère une réponse en streaming (token par token)."""

    @abstractmethod
    async def extract(
        self, prompt: str, text: str, max_tokens: int = 512,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        """Extrait des informations structurées d'un texte.

        `raise_on_truncation` : cf. `generate` (lève `OutputTruncatedError` si coupé).
        `temperature` : cf. `generate` (None = défaut fournisseur).
        `cacheable` : cf. `generate` — marque `text` comme point de coupure de cache.
        """

    @abstractmethod
    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        """Classifie un texte parmi des catégories données."""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Estime le nombre de tokens d'un texte."""

    @abstractmethod
    async def agentic_step(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 1500,
    ) -> AgentStep:
        """
        Une itération de l'agentic loop (tool use).
        - messages : format Anthropic (format canonique interne)
        - tools    : format Anthropic (input_schema)
        Retourne un AgentStep normalisé ; l'adapter gère la conversion vers son API.
        """

    async def agentic_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 1000,
    ) -> AsyncIterator[dict]:
        """
        Streams an agentic step. Yields dicts:
          {"type": "token",      "content": str}                               — text token (real-time)
          {"type": "tool_calls", "calls": [...], "assistant_message": dict, "text": str}
          {"type": "end",        "text": str}                                  — final text, no tools
        Default implementation uses agentic_step (fake streaming char-by-char).
        Override in adapters that support real streaming.
        """
        step = await self.agentic_step(system, messages, tools, max_tokens)
        if step.tool_calls:
            yield {"type": "tool_calls", "calls": step.tool_calls,
                   "assistant_message": step.assistant_message, "text": step.text}
        else:
            for ch in step.text:
                yield {"type": "token", "content": ch}
            yield {"type": "end", "text": step.text}
