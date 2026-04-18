"""Multi-turn engine: wraps an LLM agent and manages context accumulation.

Core contribution of MCPDrift. After each turn the engine saves the full
conversation state (system prompt + tool descriptions + all prior queries and
responses) and passes the accumulated context into the next turn.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    tool_name: str
    parameters: dict[str, Any]
    result: str


class TurnSnapshot(BaseModel):
    turn_number: int
    user_query: str
    agent_response: str
    tool_calls: list[ToolCall]
    system_prompt: str
    tool_descriptions: list[dict[str, Any]]
    full_history: list[dict[str, Any]]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionTrace(BaseModel):
    scenario_id: str
    model: str
    turns: list[TurnSnapshot]
    config: dict[str, Any]


# ---------------------------------------------------------------------------
# LLM client protocol — anything with a ``run_turn`` that returns a result
# ---------------------------------------------------------------------------

class LLMClient(Protocol):
    def run_turn(
        self,
        system_prompt: str,
        tool_descriptions: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        user_query: str,
    ) -> Any:
        ...


# ---------------------------------------------------------------------------
# Multi-turn engine
# ---------------------------------------------------------------------------

class MultiTurnEngine:
    """Manages context accumulation across N turns of an LLM agent session."""

    def __init__(
        self,
        llm_client: LLMClient,
        system_prompt: str,
        tool_descriptions: list[dict[str, Any]],
        max_turns: int = 10,
        scenario_id: str = "",
        model: str = "",
        tool_executor: Callable[[str, dict[str, Any]], str] | None = None,
        poisoned_tool_name: str | None = None,
        removal_turn: int | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.system_prompt = system_prompt
        self.tool_descriptions = list(tool_descriptions)
        self.max_turns = max_turns
        self.scenario_id = scenario_id
        self.model = model
        self.tool_executor = tool_executor
        self.poisoned_tool_name = poisoned_tool_name
        self.removal_turn = removal_turn

        # Accumulated message history (user/assistant/tool_result messages)
        self._history: list[dict[str, Any]] = []
        self._turn_number: int = 0
        self._snapshots: list[TurnSnapshot] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_turn(self, user_query: str) -> TurnSnapshot:
        """Execute a single turn: send accumulated context + query to LLM."""
        if self._turn_number >= self.max_turns:
            raise RuntimeError(
                f"Max turns ({self.max_turns}) reached — cannot run another turn."
            )

        self._turn_number += 1

        # Call the LLM with full context
        turn_result = self.llm_client.run_turn(
            system_prompt=self.system_prompt,
            tool_descriptions=self.tool_descriptions,
            messages=list(self._history),  # copy
            user_query=user_query,
        )

        # Build tool call records
        tool_calls = [
            ToolCall(
                tool_name=tc.tool_name,
                parameters=tc.parameters,
                result=self._resolve_tool_result(tc.tool_name, tc.parameters, tc.result),
            )
            for tc in turn_result.tool_calls
        ]

        # Append user message to history
        self._history.append({"role": "user", "content": user_query})

        # Append assistant response to history
        self._history.append(
            {"role": "assistant", "content": turn_result.response_text}
        )

        # Append tool results into history (so future turns see them)
        for tc in tool_calls:
            self._history.append(
                {
                    "role": "tool_result",
                    "tool_name": tc.tool_name,
                    "content": tc.result,
                }
            )

        snapshot = TurnSnapshot(
            turn_number=self._turn_number,
            user_query=user_query,
            agent_response=turn_result.response_text,
            tool_calls=tool_calls,
            system_prompt=self.system_prompt,
            tool_descriptions=self.tool_descriptions,
            full_history=list(self._history),  # snapshot copy
        )

        self._snapshots.append(snapshot)

        # Phase 5 recovery support: drop the poisoned tool from the
        # advertised tool set after the configured removal turn so
        # subsequent turns can demonstrate recovery.
        if (
            self.removal_turn is not None
            and self.poisoned_tool_name is not None
            and self._turn_number == self.removal_turn
        ):
            self.tool_descriptions = [
                td
                for td in self.tool_descriptions
                if td.get("name") != self.poisoned_tool_name
            ]

        return snapshot

    def run_session(self, queries: list[str]) -> SessionTrace:
        """Run all turns sequentially, return the full trace."""
        for query in queries:
            self.run_turn(query)

        return SessionTrace(
            scenario_id=self.scenario_id,
            model=self.model,
            turns=list(self._snapshots),
            config={
                "system_prompt": self.system_prompt,
                "tool_descriptions": self.tool_descriptions,
                "max_turns": self.max_turns,
            },
        )

    def save_trace(self, trace: SessionTrace, output_dir: str) -> Path:
        """Serialize a SessionTrace to JSON on disk."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filename = f"{trace.scenario_id}_{trace.model}_{ts}.json"
        path = out / filename
        path.write_text(
            trace.model_dump_json(indent=2), encoding="utf-8"
        )
        return path

    def _resolve_tool_result(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        result: str,
    ) -> str:
        if result or self.tool_executor is None:
            return result

        return self.tool_executor(tool_name, parameters)