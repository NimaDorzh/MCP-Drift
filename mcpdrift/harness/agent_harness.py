"""Agent harness: wraps LLM API clients for benchmark execution.

Provides ``AgentHarness`` (real Anthropic API calls) and ``MockAgentHarness``
(deterministic canned responses for testing without API keys).
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel

from mcpdrift.environments.multi_turn_engine import ToolCall


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class TurnResult(BaseModel):
    response_text: str
    tool_calls: list[ToolCall]
    raw_response: dict[str, Any]


# ---------------------------------------------------------------------------
# Real harness — Anthropic API
# ---------------------------------------------------------------------------

class AgentHarness:
    """Wraps the Anthropic Messages API with MCP-style tool definitions."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self.temperature = temperature

        # Import lazily so tests that never call the real API don't need it
        import anthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=key)

    # ------------------------------------------------------------------

    def run_turn(
        self,
        system_prompt: str,
        tool_descriptions: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        user_query: str,
    ) -> TurnResult:
        """Send one turn to the Anthropic API and parse the response."""
        # Build messages list in Anthropic format
        api_messages = _build_api_messages(messages, user_query)

        # Convert tool descriptions into Anthropic tool schema
        tools = _build_tool_schemas(tool_descriptions)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=self.temperature,
            system=system_prompt,
            messages=api_messages,
            tools=tools if tools else None,
        )

        return _parse_anthropic_response(response)


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
    """Convert internal history format to Anthropic messages format."""
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
) -> list[dict[str, Any]]:
    """Convert our tool description dicts into Anthropic tool schemas."""
    schemas: list[dict[str, Any]] = []
    for td in tool_descriptions:
        schema: dict[str, Any] = {
            "name": td["name"],
            "description": td.get("description", ""),
            "input_schema": td.get(
                "input_schema",
                {"type": "object", "properties": {}},
            ),
        }
        schemas.append(schema)
    return schemas


def _parse_anthropic_response(response: Any) -> TurnResult:
    """Extract text and tool calls from an Anthropic Messages response."""
    response_text = ""
    tool_calls: list[ToolCall] = []

    for block in response.content:
        if block.type == "text":
            response_text += block.text
        elif block.type == "tool_use":
            tool_calls.append(
                ToolCall(
                    tool_name=block.name,
                    parameters=block.input if isinstance(block.input, dict) else {},
                    result="",  # populated after tool execution
                )
            )

    return TurnResult(
        response_text=response_text,
        tool_calls=tool_calls,
        raw_response=response.model_dump() if hasattr(response, "model_dump") else {},
    )