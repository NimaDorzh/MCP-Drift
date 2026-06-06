"""Tests for attack scenario JSON files — schema validation and structural checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

from mcpdrift.environments.mock_mcp_server import MOCK_FILESYSTEM
from mcpdrift.harness.scenario_runner import (
    ATTACKS_DIR,
    _validate_scenario,
    list_benchmark_scenarios,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ATTACKS_DIR = Path(__file__).resolve().parent.parent / "mcpdrift" / "attacks"
SCHEMA_PATH = ATTACKS_DIR / "schema.json"
BASELINE_DIR = ATTACKS_DIR / "baseline"
MULTITURN_DIR = ATTACKS_DIR / "multiturn"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenario_files(directory: Path) -> list[Path]:
    """Return all .json scenario files in the given directory."""
    return sorted(p for p in directory.glob("*.json") if p.name != ".gitkeep")


def _extract_first_path(text: str) -> str | None:
    """Extract the first absolute-style path from a scenario query."""
    match = re.search(r"(/[A-Za-z0-9_./-]+)", text)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def schema() -> dict:
    return _load_json(SCHEMA_PATH)


@pytest.fixture(scope="module")
def baseline_scenarios() -> list[tuple[str, dict]]:
    return [(p.name, _load_json(p)) for p in _scenario_files(BASELINE_DIR)]


@pytest.fixture(scope="module")
def multiturn_scenarios() -> list[tuple[str, dict]]:
    return [(p.name, _load_json(p)) for p in _scenario_files(MULTITURN_DIR)]


# ---------------------------------------------------------------------------
# Schema validation — every scenario must pass jsonschema
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    """Validate all scenario files against attacks/schema.json."""

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(BASELINE_DIR),
        ids=lambda p: p.name,
    )
    def test_baseline_schema(self, schema, scenario_file):
        scenario = _load_json(scenario_file)
        jsonschema.validate(instance=scenario, schema=schema)

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(MULTITURN_DIR),
        ids=lambda p: p.name,
    )
    def test_multiturn_schema(self, schema, scenario_file):
        scenario = _load_json(scenario_file)
        jsonschema.validate(instance=scenario, schema=schema)


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------

class TestPoisonedToolComponents:
    """Every poisoned_tool must have all 3 MCPTox components."""

    REQUIRED_COMPONENTS = [
        "trigger_condition",
        "malicious_action",
        "plausible_justification",
    ]

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(BASELINE_DIR) + _scenario_files(MULTITURN_DIR),
        ids=lambda p: p.name,
    )
    def test_poisoned_tool_has_all_components(self, scenario_file):
        scenario = _load_json(scenario_file)
        pt = scenario["poisoned_tool"]
        for component in self.REQUIRED_COMPONENTS:
            assert component in pt, f"Missing {component} in {scenario_file.name}"
            assert pt[component].strip(), f"Empty {component} in {scenario_file.name}"


class TestBaselineStructure:
    """Baseline scenarios must have exactly 1 turn."""

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(BASELINE_DIR),
        ids=lambda p: p.name,
    )
    def test_single_turn(self, scenario_file):
        scenario = _load_json(scenario_file)
        assert len(scenario["turns"]) == 1, (
            f"{scenario_file.name} should have exactly 1 turn"
        )
        assert scenario["attack_class"] == "baseline"


class TestMultiturnStructure:
    """Multi-turn scenarios must have 3–5 turns."""

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(MULTITURN_DIR),
        ids=lambda p: p.name,
    )
    def test_three_to_five_turns(self, scenario_file):
        scenario = _load_json(scenario_file)
        n_turns = len(scenario["turns"])
        assert 3 <= n_turns <= 5, (
            f"{scenario_file.name} has {n_turns} turns, expected 3–5"
        )
        assert scenario["attack_class"] == "multi-turn"

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(MULTITURN_DIR),
        ids=lambda p: p.name,
    )
    def test_turn_numbers_sequential(self, scenario_file):
        scenario = _load_json(scenario_file)
        turn_numbers = [t["turn"] for t in scenario["turns"]]
        expected = list(range(1, len(turn_numbers) + 1))
        assert turn_numbers == expected, (
            f"{scenario_file.name}: turn numbers {turn_numbers} != {expected}"
        )


class TestScenarioCount:
    """Verify we have the expected number of scenarios."""

    def test_five_baseline_scenarios(self, baseline_scenarios):
        assert len(baseline_scenarios) == 5, (
            f"Expected 5 baseline scenarios, found {len(baseline_scenarios)}"
        )

    def test_five_multiturn_scenarios(self, multiturn_scenarios):
        assert len(multiturn_scenarios) == 5, (
            f"Expected 5 multi-turn scenarios, found {len(multiturn_scenarios)}"
        )


class TestScenarioLoadable:
    """Scenarios must be loadable by ScenarioRunner (basic structural check)."""

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(BASELINE_DIR) + _scenario_files(MULTITURN_DIR),
        ids=lambda p: p.name,
    )
    def test_has_required_runner_fields(self, scenario_file):
        scenario = _load_json(scenario_file)
        assert "scenario_id" in scenario
        assert "turns" in scenario
        assert all("user_query" in t for t in scenario["turns"])


class TestScenarioEnvironmentCompatibility:
    """Scenario turns should fit the current mock tool and file surface."""

    SUPPORTED_PREFIXES = (
        "what time",
        "read",
        "write",
        "create",
        "send",
    )

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(BASELINE_DIR) + _scenario_files(MULTITURN_DIR),
        ids=lambda p: p.name,
    )
    def test_turn_queries_use_supported_mock_operations(self, scenario_file):
        scenario = _load_json(scenario_file)
        for turn in scenario["turns"]:
            query = turn["user_query"].strip().lower()
            assert query.startswith(self.SUPPORTED_PREFIXES), (
                f"Unsupported mock-server operation in {scenario_file.name}: "
                f"{turn['user_query']}"
            )

    @pytest.mark.parametrize(
        "scenario_file",
        _scenario_files(BASELINE_DIR) + _scenario_files(MULTITURN_DIR),
        ids=lambda p: p.name,
    )
    def test_read_queries_reference_known_mock_files(self, scenario_file):
        scenario = _load_json(scenario_file)
        for turn in scenario["turns"]:
            query = turn["user_query"].strip()
            if not query.lower().startswith("read"):
                continue

            path = _extract_first_path(query)
            assert path is not None, f"No readable path found in {scenario_file.name}: {query}"
            assert path in MOCK_FILESYSTEM, (
                f"Scenario {scenario_file.name} references missing mock file: {path}"
            )


class TestScenarioDiscovery:
    def test_list_benchmark_scenarios_matches_baseline_and_multiturn(self):
        paths = list_benchmark_scenarios()
        expected = _scenario_files(BASELINE_DIR) + _scenario_files(MULTITURN_DIR)
        assert [path.resolve() for path in paths] == [path.resolve() for path in expected]

    def test_recovery_scenarios_excluded_by_default(self):
        paths = list_benchmark_scenarios()
        assert all(path.parent.name != "recovery" for path in paths)

    def test_recovery_scenarios_included_when_requested(self):
        paths = list_benchmark_scenarios(include_recovery=True)
        recovery_paths = sorted((ATTACKS_DIR / "recovery").glob("*.json"))
        assert recovery_paths
        assert all(path in paths for path in recovery_paths)


class TestScenarioSemanticValidation:
    def test_non_sequential_turn_numbers_raise(self):
        scenario = _load_json(BASELINE_DIR / "p1_email_redirect.json")
        scenario["turns"] = [{"turn": 2, "user_query": "Send email"}]
        with pytest.raises(ValueError, match="turn numbers"):
            _validate_scenario(scenario)

    def test_out_of_range_removal_turn_raises(self):
        scenario = _load_json(MULTITURN_DIR / "mt_delayed_ssh.json")
        scenario["removal_turn"] = len(scenario["turns"]) + 1
        with pytest.raises(ValueError, match="removal_turn"):
            _validate_scenario(scenario)
