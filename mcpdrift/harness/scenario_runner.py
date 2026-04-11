"""Scenario runner: loads JSON scenarios and orchestrates benchmark execution.

Loads attack scenarios from JSON, configures the mock MCP server with poisoned
tool descriptions, runs all turns through the multi-turn engine, and persists
the resulting ``SessionTrace`` to disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcpdrift.environments.mock_mcp_server import (
    DEFAULT_TOOLS,
    _TOOL_IMPLEMENTATIONS,
    create_mock_server,
)
from mcpdrift.environments.multi_turn_engine import (
    MultiTurnEngine,
    SessionTrace,
)
from mcpdrift.harness.agent_harness import AgentHarness, MockAgentHarness


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

class ScenarioRunner:
    """Orchestrates end-to-end benchmark execution for one or many scenarios."""

    def __init__(
        self,
        harness: AgentHarness | MockAgentHarness,
        output_dir: str = "results/traces/",
    ) -> None:
        self.harness = harness
        self.output_dir = output_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scenario(self, scenario_path: str) -> SessionTrace:
        """Load a JSON scenario, run all turns, and return the trace."""
        scenario = _load_scenario(scenario_path)
        return self._execute_scenario(scenario)

    def run_scenario_dict(self, scenario: dict[str, Any]) -> SessionTrace:
        """Run a scenario supplied as a dict (useful for tests)."""
        return self._execute_scenario(scenario)

    def run_batch(self, scenario_dir: str) -> list[SessionTrace]:
        """Run every ``*.json`` scenario in *scenario_dir*."""
        p = Path(scenario_dir)
        traces: list[SessionTrace] = []
        for scenario_file in sorted(p.glob("*.json")):
            trace = self.run_scenario(str(scenario_file))
            traces.append(trace)
        return traces

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _execute_scenario(self, scenario: dict[str, Any]) -> SessionTrace:
        scenario_id = scenario.get("scenario_id", "unknown")
        queries = [t["user_query"] for t in scenario["turns"]]

        create_mock_server(_build_mock_server_config(scenario))

        # Build tool descriptions for the engine
        tool_descriptions = _build_tool_descriptions(scenario)

        # Build system prompt
        system_prompt = scenario.get(
            "system_prompt",
            "You are a helpful assistant with access to tools.",
        )

        # Create the multi-turn engine
        engine = MultiTurnEngine(
            llm_client=self.harness,
            system_prompt=system_prompt,
            tool_descriptions=tool_descriptions,
            max_turns=len(queries),
            scenario_id=scenario_id,
            model=getattr(self.harness, "model", "unknown"),
            tool_executor=_execute_mock_tool,
        )

        # Run all turns
        trace = engine.run_session(queries)

        # Persist trace
        engine.save_trace(trace, self.output_dir)

        # Print summary
        print(
            f"[ScenarioRunner] {scenario_id}: "
            f"{len(trace.turns)} turns executed — "
            f"trace saved to {self.output_dir}"
        )

        return trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_scenario(path: str) -> dict[str, Any]:
    """Read and parse a JSON scenario file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_tool_descriptions(
    scenario: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the list of tool descriptions, injecting the poisoned tool if present.

    Always includes the four default tools. If the scenario defines a
    ``poisoned_tool``, its description replaces (or is added to) the set.
    """
    descriptions: list[dict[str, Any]] = []

    poisoned = scenario.get("poisoned_tool")
    poisoned_name = poisoned["name"] if poisoned else None

    for name, meta in DEFAULT_TOOLS.items():
        desc = meta["description"]
        # If this tool has a poisoned description, use it
        if poisoned and name == poisoned_name:
            desc = poisoned.get("description", desc)
        descriptions.append({
            "name": name,
            "description": desc,
            "input_schema": _default_input_schema(name),
        })

    # If the poisoned tool is not one of the defaults, add it separately
    if poisoned and poisoned_name not in DEFAULT_TOOLS:
        descriptions.append({
            "name": poisoned_name,
            "description": poisoned.get("description", ""),
            "input_schema": poisoned.get(
                "input_schema", {"type": "object", "properties": {}}
            ),
        })

    return descriptions


def _build_mock_server_config(scenario: dict[str, Any]) -> dict[str, Any] | None:
    """Build the mock-server config for default tool overrides.

    Only default tools can be injected into the mock server because they have
    registered implementations in the benchmark environment.
    """
    poisoned = scenario.get("poisoned_tool")
    if not poisoned:
        return None

    poisoned_name = poisoned["name"]
    if poisoned_name not in DEFAULT_TOOLS:
        return None

    return {
        "tools": [
            {
                "name": poisoned_name,
                "description": DEFAULT_TOOLS[poisoned_name]["description"],
                "poisoned_description": poisoned.get("description"),
            }
        ]
    }


def _execute_mock_tool(tool_name: str, parameters: dict[str, Any]) -> str:
    """Execute a mock tool locally so traces contain concrete tool outputs."""
    implementation = _TOOL_IMPLEMENTATIONS.get(tool_name)
    if implementation is None:
        return f"Error: unknown tool: {tool_name}"

    try:
        return str(implementation(**parameters))
    except TypeError as exc:
        return f"Error executing {tool_name}: {exc}"


def _default_input_schema(tool_name: str) -> dict[str, Any]:
    """Return a minimal JSON-schema for the default mock tools."""
    schemas: dict[str, dict[str, Any]] = {
        "file_read": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "file_write": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        "email_send": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        "get_time": {
            "type": "object",
            "properties": {},
        },
    }
    return schemas.get(tool_name, {"type": "object", "properties": {}})