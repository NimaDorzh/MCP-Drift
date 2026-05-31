"""Agent harness: wraps LLM providers for benchmark execution.

Provides ``AgentHarness`` (real provider-backed API calls) and
``MockAgentHarness`` (deterministic canned responses for testing without API
keys).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mcpdrift.environments.multi_turn_engine import ToolCall
from mcpdrift.providers import LLMProvider, get_provider


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class TurnResult(BaseModel):
    response_text: str
    tool_calls: list[ToolCall]
    raw_response: dict[str, Any]


# ---------------------------------------------------------------------------
# Real harness — provider-backed API
# ---------------------------------------------------------------------------

class AgentHarness:
    """Wraps an LLM provider with MCP-style tool definitions."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        provider_name: str = "anthropic",
        temperature: float = 0.0,
        provider: LLMProvider | None = None,
        seed: int | None = None,
    ) -> None:
        self.model = model
        self.provider_name = provider_name
        self.temperature = temperature
        self.seed = seed
        self.provider = provider or get_provider(provider_name=provider_name, model=model)
        self.last_latency_ms = 0.0

    # ------------------------------------------------------------------

    def run_turn(
        self,
        system_prompt: str,
        tool_descriptions: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        user_query: str,
    ) -> TurnResult:
        """Send one turn to the configured provider and normalize the response."""
        api_messages = _build_api_messages(messages, user_query)
        tools = _build_tool_schemas(tool_descriptions, provider_name=self.provider_name)

        response = self.provider.complete(
            messages=api_messages,
            tools=tools,
            system_prompt=system_prompt,
            temperature=self.temperature,
            max_tokens=4096,
            seed=self.seed,
        )
        self.last_latency_ms = response.latency_ms
        return TurnResult(
            response_text=response.text,
            tool_calls=[
                ToolCall(
                    tool_name=tool_call["tool_name"],
                    parameters=tool_call.get("parameters", {}),
                    result="",
                )
                for tool_call in response.tool_calls
            ],
            raw_response={
                **response.raw,
                "provider": self.provider_name,
                "latency_ms": response.latency_ms,
            },
        )


# ---------------------------------------------------------------------------
# Mock harness — deterministic responses for testing
# ---------------------------------------------------------------------------

class MockAgentHarness:
    """Returns canned responses; no API calls.

    Parameters
    ----------
    responses : list[str | dict]
        One entry per turn.  A plain string is returned as the assistant text.
        A dict may contain ``response_text`` and/or ``tool_calls``.
    """

    def __init__(self, responses: list[str | dict[str, Any]] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_index = 0
        self.model = "mock-model"

    def run_turn(
        self,
        system_prompt: str,
        tool_descriptions: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        user_query: str,
    ) -> TurnResult:
        if self._call_index < len(self._responses):
            entry = self._responses[self._call_index]
        else:
            entry = f"Mock response for: {user_query}"

        self._call_index += 1

        if isinstance(entry, str):
            return TurnResult(
                response_text=entry,
                tool_calls=[],
                raw_response={"mock": True, "text": entry},
            )

        tool_calls = [
            ToolCall(**tc) for tc in entry.get("tool_calls", [])
        ]
        return TurnResult(
            response_text=entry.get("response_text", ""),
            tool_calls=tool_calls,
            raw_response={"mock": True, **entry},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_api_messages(
    history: list[dict[str, Any]], user_query: str
) -> list[dict[str, Any]]:
    """Convert internal history format to chat-style messages."""
    api_msgs: list[dict[str, Any]] = []
    for msg in history:
        role = msg["role"]
        if role in ("user", "assistant"):
            api_msgs.append({"role": role, "content": msg["content"]})
        elif role == "tool_result":
            tool_name = msg.get("tool_name", "unknown_tool")
            api_msgs.append(
                {
                    "role": "user",
                    "content": f"Tool result from {tool_name}: {msg['content']}",
                }
            )
    api_msgs.append({"role": "user", "content": user_query})
    return api_msgs


def _build_tool_schemas(
    tool_descriptions: list[dict[str, Any]],
    provider_name: str = "anthropic",
) -> list[dict[str, Any]]:
    """Convert internal tool descriptions into provider tool schemas."""
    schemas: list[dict[str, Any]] = []
    for td in tool_descriptions:
        input_schema = td.get(
            "input_schema",
            {"type": "object", "properties": {}},
        )
        if provider_name == "anthropic":
            schema = {
                "name": td["name"],
                "description": td.get("description", ""),
                "input_schema": input_schema,
            }
        else:
            schema = {
                "type": "function",
                "function": {
                    "name": td["name"],
                    "description": td.get("description", ""),
                    "parameters": input_schema,
                },
            }
        schemas.append(schema)
    return schemas
