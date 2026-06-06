"""Scenario runner: loads JSON scenarios and orchestrates benchmark execution.

Loads attack scenarios from JSON, configures the mock MCP server with poisoned
tool descriptions, runs all turns through the multi-turn engine, and persists
the resulting ``SessionTrace`` to disk.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

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
from mcpdrift.logging_utils import get_logger


ATTACKS_DIR = Path(__file__).resolve().parent.parent / "attacks"
SCHEMA_PATH = ATTACKS_DIR / "schema.json"
BENCHMARK_SCENARIO_DIRS = ("baseline", "multiturn")
RECOVERY_DIR_NAME = "recovery"

logger = get_logger(__name__)


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

    def run_batch(
        self,
        scenario_dir: str,
        *,
        include_recovery: bool = False,
    ) -> list[SessionTrace]:
        """Run every benchmark scenario under *scenario_dir*.

        If *scenario_dir* looks like the attacks root (contains ``baseline/``
        and ``multiturn/``), all benchmark scenarios in those folders are run.
        Otherwise only ``*.json`` files directly in *scenario_dir* are run.
        """
        p = Path(scenario_dir)
        if (p / "baseline").is_dir() and (p / "multiturn").is_dir():
            scenario_files = list_benchmark_scenarios(
                include_recovery=include_recovery,
                attacks_dir=p,
            )
        else:
            scenario_files = [
                path
                for path in sorted(p.glob("*.json"))
                if path.name != "schema.json"
            ]

        traces: list[SessionTrace] = []
        for scenario_file in scenario_files:
            trace = self.run_scenario(str(scenario_file))
            traces.append(trace)
        return traces

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _execute_scenario(self, scenario: dict[str, Any]) -> SessionTrace:
        _validate_scenario(scenario)

        scenario_id = scenario.get("scenario_id", "unknown")
        queries = [t["user_query"] for t in scenario["turns"]]
        tool_runtime = _build_tool_runtime(scenario)

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
            tool_executor=lambda tool_name, parameters: _execute_mock_tool(
                tool_name,
                parameters,
                tool_runtime,
            ),
            poisoned_tool_name=(
                scenario.get("poisoned_tool", {}).get("name")
            ),
            removal_turn=scenario.get("removal_turn"),
        )

        # Run all turns
        trace = engine.run_session(queries)

        # Persist trace
        engine.save_trace(trace, self.output_dir)

        logger.info(
            "%s: %d turns executed \u2014 trace saved to %s",
            scenario_id,
            len(trace.turns),
            self.output_dir,
        )

        return trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_scenario(path: str) -> dict[str, Any]:
    """Read and parse a JSON scenario file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_attack_schema() -> dict[str, Any]:
    """Load the scenario schema once per process."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def list_benchmark_scenarios(
    *,
    include_recovery: bool = False,
    attacks_dir: Path | None = None,
) -> list[Path]:
    """Return sorted paths to benchmark scenario JSON files.

    By default includes ``baseline/`` and ``multiturn/`` only. Recovery
    scenarios live under ``recovery/`` and are excluded unless
    *include_recovery* is ``True``.
    """
    root = attacks_dir or ATTACKS_DIR
    search_dirs = [root / name for name in BENCHMARK_SCENARIO_DIRS]
    if include_recovery:
        search_dirs.append(root / RECOVERY_DIR_NAME)

    paths: list[Path] = []
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        paths.extend(
            path
            for path in sorted(directory.glob("*.json"))
            if path.name != "schema.json"
        )
    return paths


def _validate_scenario(scenario: dict[str, Any]) -> None:
    """Fail fast on structurally or semantically invalid scenarios."""
    jsonschema.validate(instance=scenario, schema=_load_attack_schema())
    _validate_scenario_semantics(scenario)


def _validate_scenario_semantics(scenario: dict[str, Any]) -> None:
    """Check turn numbering and recovery-turn bounds beyond JSON Schema."""
    scenario_id = scenario.get("scenario_id", "<unknown>")
    turns = scenario["turns"]
    turn_numbers = [t["turn"] for t in turns]
    expected = list(range(1, len(turn_numbers) + 1))
    if turn_numbers != expected:
        raise ValueError(
            f"Scenario {scenario_id!r}: turn numbers {turn_numbers} "
            f"must be sequential starting at 1 ({expected})"
        )

    removal_turn = scenario.get("removal_turn")
    if removal_turn is not None and not (1 <= removal_turn <= len(turns)):
        raise ValueError(
            f"Scenario {scenario_id!r}: removal_turn={removal_turn} "
            f"must be between 1 and {len(turns)}"
        )


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
        base_tool = poisoned.get("base_tool")
        descriptions.append({
            "name": poisoned_name,
            "description": poisoned.get("description", ""),
            "input_schema": poisoned.get("input_schema")
            or _default_input_schema(base_tool)
            or {"type": "object", "properties": {}},
        })

    return descriptions


def _build_tool_runtime(scenario: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Collect optional execution metadata for poisoned tools."""
    poisoned = scenario.get("poisoned_tool")
    if not poisoned:
        return {}

    return {
        poisoned["name"]: {
            "base_tool": poisoned.get("base_tool", ""),
            "result_poison": poisoned.get("result_poison", ""),
        }
    }


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


def _execute_mock_tool(
    tool_name: str,
    parameters: dict[str, Any],
    tool_runtime: dict[str, dict[str, str]] | None = None,
) -> str:
    """Execute a mock tool locally so traces contain concrete tool outputs."""
    runtime = (tool_runtime or {}).get(tool_name, {})
    target_tool = runtime.get("base_tool") or tool_name
    implementation = _TOOL_IMPLEMENTATIONS.get(target_tool)

    if implementation is None:
        result = f"{tool_name} completed successfully."
    else:
        try:
            result = str(implementation(**parameters))
        except TypeError as exc:
            return f"Error executing {tool_name}: {exc}"

    poisoned_result = runtime.get("result_poison")
    if poisoned_result:
        return f"{result}\n{poisoned_result}"

    return result


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