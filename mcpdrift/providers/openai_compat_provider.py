from __future__ import annotations

from time import perf_counter
from typing import Any

from mcpdrift.providers.base import LLMProvider, ProviderResponse


class OpenAICompatProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=self.base_url)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ProviderResponse:
        temperature = float(kwargs.get("temperature", 0.0))
        max_tokens = int(kwargs.get("max_tokens", 4096))

        started_at = perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = (perf_counter() - started_at) * 1000.0

        choice = response.choices[0]
        message = choice.message
        raw = response.model_dump() if hasattr(response, "model_dump") else {}

        normalized_calls: list[dict[str, Any]] = []
        for tool_call in message.tool_calls or []:
            arguments = tool_call.function.arguments or "{}"
            normalized_calls.append(
                {
                    "tool_name": tool_call.function.name,
                    "parameters": _parse_tool_arguments(arguments),
                }
            )

        return ProviderResponse(
            text=message.content or "",
            tool_calls=normalized_calls,
            raw=raw,
            latency_ms=latency_ms,
        )


def _parse_tool_arguments(arguments: str) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}