from __future__ import annotations

from time import perf_counter
from typing import Any

from mcpdrift.logging_utils import get_logger
from mcpdrift.providers.base import LLMProvider, ProviderResponse


logger = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.0,
    ) -> None:
        import anthropic

        self.model = model
        self.temperature = temperature
        self.client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ProviderResponse:
        system_prompt = str(kwargs.get("system_prompt", ""))
        max_tokens = int(kwargs.get("max_tokens", 4096))
        temperature = float(kwargs.get("temperature", self.temperature))
        if kwargs.get("seed") is not None:
            logger.warning(
                "Anthropic API does not support a 'seed' parameter; "
                "ignoring seed=%s for model %s.",
                kwargs.get("seed"),
                self.model,
            )

        started_at = perf_counter()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
            tools=tools or None,
        )
        latency_ms = (perf_counter() - started_at) * 1000.0

        response_text = ""
        tool_calls: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                response_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "tool_name": block.name,
                        "parameters": block.input if isinstance(block.input, dict) else {},
                    }
                )

        raw = response.model_dump() if hasattr(response, "model_dump") else {}
        return ProviderResponse(
            text=response_text,
            tool_calls=tool_calls,
            raw=raw,
            latency_ms=latency_ms,
        )