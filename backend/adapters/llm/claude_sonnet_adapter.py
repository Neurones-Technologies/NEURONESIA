import json
import logging
from typing import AsyncIterator

import anthropic
import tiktoken

from core.ports.llm_gateway import LLMGateway, OutputTruncatedError
from config.settings import settings

logger = logging.getLogger(__name__)

_SYSTEM_CACHE_CONTROL = {"type": "ephemeral"}


class ClaudeSonnetAdapter(LLMGateway):
    """
    Claude Sonnet 4.6 — qualité supérieure pour les générations longues.
    Utilisé exclusivement pour : génération d'offres techniques complètes.
    """

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.sonnet_model
        self._encoder = tiktoken.get_encoding("cl100k_base")

    async def generate(
        self, system: str, user: str, max_tokens: int = 4096,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        # cf. ClaudeHaikuAdapter.generate — même logique de coupure de cache sur `user`.
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
            logger.warning(
                "Réponse Claude Sonnet TRONQUÉE (stop_reason=max_tokens, budget=%d tokens). "
                "Le contenu est incomplet — augmenter max_tokens pour cette génération.",
                max_tokens,
            )
            if raise_on_truncation:
                raise OutputTruncatedError(partial_text=text, max_tokens=max_tokens)
        return text

    async def stream(self, system: str, user: str, max_tokens: int = 4096) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": _SYSTEM_CACHE_CONTROL}],
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def extract(
        self, prompt: str, text: str, max_tokens: int = 1024,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        return await self.generate(
            system=prompt, user=text, max_tokens=max_tokens,
            raise_on_truncation=raise_on_truncation, temperature=temperature,
            cacheable=cacheable,
        )

    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        system = f"Réponds UNIQUEMENT avec l'une de ces catégories : {', '.join(categories)}."
        result = (await self.generate(system=system, user=text, max_tokens=20)).strip()
        if result in categories:
            return result
        for cat in categories:
            if cat.lower() in result.lower():
                return cat
        return default if default in categories else categories[0]

    async def agentic_step(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 1500):
        from core.ports.llm_gateway import AgentStep
        response = await self._client.messages.create(
            model=self._model, max_tokens=max_tokens, system=system, tools=tools, messages=messages,
        )
        text, tool_calls, assistant_content = "", [], []
        for block in response.content:
            if block.type == "text":
                text += block.text
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "input": block.input})
                assistant_content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
        return AgentStep(
            stop_reason=response.stop_reason, text=text, tool_calls=tool_calls,
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
