import base64
import json
import logging
from typing import AsyncIterator

import anthropic
import tiktoken

from core.ports.llm_gateway import LLMGateway, OutputTruncatedError
from config.settings import settings

logger = logging.getLogger(__name__)

_SYSTEM_CACHE_CONTROL = {"type": "ephemeral"}


class ClaudeHaikuAdapter(LLMGateway):
    """
    Claude Haiku 4.5 — rapide et économique.
    Utilisé pour : chat, extraction, classification, scoring.
    Prompt caching activé sur le system prompt.
    """

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.haiku_model
        self._encoder = tiktoken.get_encoding("cl100k_base")

    async def generate(
        self, system: str, user: str, max_tokens: int = 1024,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        # `cacheable=True` : `user` (souvent le plus gros bloc — l'AO entier ou un chunk)
        # devient lui aussi un point de coupure de prompt caching, en plus du system prompt
        # déjà caché. Utile sur un retry (même contenu renvoyé avec un budget de sortie
        # élargi) ou une ré-analyse forcée du même document dans les 5 minutes — le second
        # appel relit alors TOUT l'input (system + user) au tarif cache (~10% du prix), au
        # lieu de repayer le plein tarif à chaque tentative. cf. LLMGateway.generate.
        user_content = (
            [{"type": "text", "text": user, "cache_control": _SYSTEM_CACHE_CONTROL}]
            if cacheable else user
        )
        kwargs = dict(
            model=self._model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": _SYSTEM_CACHE_CONTROL}],
            messages=[{"role": "user", "content": user_content}],
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await self._client.messages.create(**kwargs)
        text = response.content[0].text
        if response.stop_reason == "max_tokens":
            # Sortie coupée net au plafond : tout JSON aval sera invalide. On le dit clairement
            # ici plutôt que de laisser le caller deviner via un "Expecting ',' delimiter" trompeur.
            logger.warning(
                "Réponse Claude Haiku TRONQUÉE (stop_reason=max_tokens, budget=%d tokens). "
                "Le contenu est incomplet — augmenter max_tokens pour cette étape.",
                max_tokens,
            )
            if raise_on_truncation:
                raise OutputTruncatedError(partial_text=text, max_tokens=max_tokens)
        return text

    async def stream(self, system: str, user: str, max_tokens: int = 1024) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": _SYSTEM_CACHE_CONTROL}],
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def extract(
        self, prompt: str, text: str, max_tokens: int = 512,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        return await self.generate(
            system=prompt, user=text, max_tokens=max_tokens,
            raise_on_truncation=raise_on_truncation, temperature=temperature,
            cacheable=cacheable,
        )

    async def generate_with_images(
        self,
        system: str,
        user: str,
        images: list[tuple[str, bytes]],
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        """Génération MULTIMODALE : `images` = liste de (media_type, octets) — ex.
        ("image/png", b"..."). Haiku 4.5 est multimodal. Méthode ADDITIVE (hors interface
        LLMGateway abstraite) : seul cet adaptateur la fournit, l'appelant teste sa présence
        via hasattr. Utilisé pour lire les logos de certifications dans les CV scannés."""
        content: list[dict] = []
        for media_type, raw in images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(raw).decode("ascii"),
                },
            })
        content.append({"type": "text", "text": user})
        kwargs = dict(
            model=self._model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": _SYSTEM_CACHE_CONTROL}],
            messages=[{"role": "user", "content": content}],
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await self._client.messages.create(**kwargs)
        return response.content[0].text if response.content else ""

    async def generate_with_web_search(
        self, system: str, user: str, max_tokens: int = 1024,
        max_uses: int = 5, temperature: float | None = None,
    ) -> str:
        """Génération avec recherche + récupération web côté serveur (outils natifs
        Claude, sans clé tierce). Méthode ADDITIVE (hors interface LLMGateway
        abstraite, même convention que generate_with_images) : seul cet adaptateur
        la fournit, l'appelant teste sa présence via hasattr. Utilisée par l'agent
        Watch-Tracker quand l'option « Explorer Internet » est activée.

        web_search seul renvoie souvent l'URL générique d'une page de LISTE (ex.
        « /appels-offres »), pas le lien direct vers l'annonce précise — de
        nombreux sites (BCEAO, DGMP…) n'indexent que la page de liste dans les
        moteurs de recherche. web_fetch permet à Claude d'ouvrir cette page de
        liste et d'en extraire le lien direct vers l'offre spécifique.
        `max_uses` plafonne le nombre d'appels de chaque outil (coût)."""
        kwargs = dict(
            model=self._model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": _SYSTEM_CACHE_CONTROL}],
            tools=[
                {
                    "type": "web_search_20260209", "name": "web_search", "max_uses": max_uses,
                    # Requis par l'API pour ce modèle : appel direct (pas d'appel programmatique
                    # depuis code execution) — sinon 400 invalid_request_error.
                    "allowed_callers": ["direct"],
                },
                {
                    "type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_uses,
                    "allowed_callers": ["direct"],
                },
            ],
            messages=[{"role": "user", "content": user}],
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await self._client.messages.create(**kwargs)
        # Ne garder que les blocs texte (la synthèse) ; les blocs de résultats de
        # recherche intercalés (server_tool_use / web_search_tool_result) sont déjà
        # pris en compte par Claude dans son raisonnement, pas à re-parser ici.
        return "".join(block.text for block in response.content if block.type == "text")

    async def generate_with_url_fetch(
        self, system: str, user: str, max_tokens: int = 1200,
        max_uses: int = 2, temperature: float | None = None,
    ) -> str:
        """Génération avec récupération d'une page web précise (outil natif Claude
        web_fetch seul, sans web_search). Méthode ADDITIVE (hors interface
        LLMGateway abstraite, même convention que generate_with_images) : seul cet
        adaptateur la fournit, l'appelant teste sa présence via hasattr. Utilisée
        pour le débriefing d'AO : l'URL exacte de l'annonce est déjà connue (donnée
        dans `user`), Claude l'ouvre et en extrait/synthétise le contenu — pas
        besoin de chercher, contrairement à generate_with_web_search."""
        kwargs = dict(
            model=self._model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": _SYSTEM_CACHE_CONTROL}],
            tools=[{
                "type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_uses,
                "allowed_callers": ["direct"],
            }],
            messages=[{"role": "user", "content": user}],
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await self._client.messages.create(**kwargs)
        # Séparateur "\n\n" (pas "") : Claude émet souvent plusieurs blocs texte
        # séparés par l'appel d'outil (ex. "Je vais l'ouvrir." puis la synthèse) —
        # un join sans séparateur les colle sans espace ("vous.Parfait...").
        return "\n\n".join(block.text for block in response.content if block.type == "text")

    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        system = (
            f"Tu es un classificateur. Réponds UNIQUEMENT avec l'une de ces catégories : "
            f"{', '.join(categories)}. Pas d'explication."
        )
        result = await self.generate(system=system, user=text, max_tokens=20)
        result = result.strip()
        if result in categories:
            return result
        for cat in categories:
            if cat.lower() in result.lower():
                return cat
        return default if default in categories else categories[0]

    async def agentic_step(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 1500,
    ):
        from core.ports.llm_gateway import AgentStep
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        text = ""
        tool_calls = []
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                text += block.text
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "input": block.input})
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return AgentStep(
            stop_reason=response.stop_reason,
            text=text,
            tool_calls=tool_calls,
            assistant_message={"role": "assistant", "content": assistant_content},
        )

    async def agentic_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 1000,
    ):
        collected_text = ""
        tool_input_buffers: dict[int, dict] = {}

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": _SYSTEM_CACHE_CONTROL}],
            tools=tools,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_input_buffers[event.index] = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input_json": "",
                        }
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        collected_text += delta.text
                        yield {"type": "token", "content": delta.text}
                    elif delta.type == "input_json_delta" and event.index in tool_input_buffers:
                        tool_input_buffers[event.index]["input_json"] += delta.partial_json

        tool_calls = []
        assistant_content = []
        if collected_text:
            assistant_content.append({"type": "text", "text": collected_text})
        for idx in sorted(tool_input_buffers.keys()):
            buf = tool_input_buffers[idx]
            try:
                input_data = json.loads(buf["input_json"])
            except json.JSONDecodeError:
                input_data = {}
            tool_calls.append({"id": buf["id"], "name": buf["name"], "input": input_data})
            assistant_content.append({
                "type": "tool_use", "id": buf["id"], "name": buf["name"], "input": input_data,
            })

        if tool_calls:
            yield {
                "type": "tool_calls",
                "calls": tool_calls,
                "assistant_message": {"role": "assistant", "content": assistant_content},
                "text": collected_text,
            }
        else:
            yield {"type": "end", "text": collected_text}

    def count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))
