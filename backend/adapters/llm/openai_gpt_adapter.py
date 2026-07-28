import json
import logging
from typing import AsyncIterator

import tiktoken
from openai import AsyncOpenAI

from core.ports.llm_gateway import LLMGateway, AgentStep, OutputTruncatedError
from config.settings import settings

logger = logging.getLogger(__name__)


class OpenAIGPTAdapter(LLMGateway):
    """
    GPT-4o-mini — fallback si Anthropic est indisponible.
    Supporte le tool use et le streaming.
    Convertit en interne le format Anthropic (format canonique) ↔ format OpenAI.
    """

    def __init__(self):
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_chat_model
        self._encoder = tiktoken.get_encoding("cl100k_base")

    async def generate(
        self, system: str, user: str, max_tokens: int = 1024,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        # `cacheable` ignoré ici : OpenAI met en cache automatiquement les préfixes de
        # prompt côté serveur (>1024 tokens), sans marquage explicite requis côté appelant.
        kwargs = dict(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await self._client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        if raise_on_truncation and response.choices[0].finish_reason == "length":
            logger.warning("Réponse OpenAI/Ollama TRONQUÉE (finish_reason=length, budget=%d).", max_tokens)
            raise OutputTruncatedError(partial_text=text, max_tokens=max_tokens)
        return text

    async def stream(self, system: str, user: str, max_tokens: int = 1024) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            stream=True,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                yield token

    async def extract(
        self, prompt: str, text: str, max_tokens: int = 512,
        raise_on_truncation: bool = False, temperature: float | None = None,
        cacheable: bool = False,
    ) -> str:
        return await self.generate(
            system=prompt, user=text, max_tokens=max_tokens,
            raise_on_truncation=raise_on_truncation, temperature=temperature,
        )

    async def classify(self, text: str, categories: list[str], default: str | None = None) -> str:
        system = (
            f"Tu es un classificateur. Réponds UNIQUEMENT avec l'une de ces catégories : "
            f"{', '.join(categories)}. Pas d'explication."
        )
        result = (await self.generate(system=system, user=text, max_tokens=20)).strip()
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
    ) -> AgentStep:
        openai_messages = self._to_openai_messages(system, messages)
        openai_tools = self._to_openai_tools(tools)

        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=openai_messages,
            tools=openai_tools,
            tool_choice="auto",
        )

        choice = response.choices[0]
        msg = choice.message
        text = msg.content or ""
        tool_calls_raw = msg.tool_calls or []

        # Convertir la réponse OpenAI → format Anthropic canonique
        tool_calls = []
        assistant_content = []
        if text:
            assistant_content.append({"type": "text", "text": text})
        for call in tool_calls_raw:
            try:
                input_data = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                input_data = {}
            tool_calls.append({"id": call.id, "name": call.function.name, "input": input_data})
            assistant_content.append({
                "type": "tool_use",
                "id": call.id,
                "name": call.function.name,
                "input": input_data,
            })

        # Normaliser le stop_reason au format Anthropic
        stop_reason = "tool_use" if tool_calls else "end_turn"

        return AgentStep(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            assistant_message={"role": "assistant", "content": assistant_content},
        )

    def count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))

    # ─── Conversions de format (Anthropic ↔ OpenAI) ──────────────────────────

    @staticmethod
    def _to_openai_tools(tools: list[dict]) -> list[dict]:
        """Anthropic tool definitions → OpenAI function definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

    @staticmethod
    def _to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
        """Messages au format Anthropic → messages au format OpenAI."""
        result: list[dict] = [{"role": "system", "content": system}]

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                result.append({"role": role, "content": content})
                continue

            # Contenu en liste (tool calls / tool results)
            if role == "user":
                tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]

                if text_blocks:
                    result.append({"role": "user", "content": " ".join(b["text"] for b in text_blocks)})
                for block in tool_results:
                    result.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": block.get("content", ""),
                    })

            elif role == "assistant":
                text = ""
                tool_calls = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })
                assistant_msg: dict = {"role": "assistant", "content": text or None}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                result.append(assistant_msg)

        return result
