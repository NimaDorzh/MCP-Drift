"""Integration tests for the multi-turn engine, agent harness, and scenario runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcpdrift.environments.multi_turn_engine import (
    MultiTurnEngine,
    SessionTrace,
)
from mcpdrift.environments.mock_mcp_server import MOCK_TIMESTAMP
from mcpdrift.harness.agent_harness import MockAgentHarness, _build_api_messages
from mcpdrift.harness.scenario_runner import ScenarioRunner


FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_harness() -> MockAgentHarness:
    """Mock harness that returns a canned response for each of the 3 turns."""
    return MockAgentHarness(
        responses=[
            {
                "response_text": "The current time is 2025-01-15T12:00:00+00:00.",
                "tool_calls": [
                    {"tool_name": "get_time", "parameters": {}, "result": "2025-01-15T12:00:00+00:00"}
                ],
            },
            {
                "response_text": "Here is the content of /data/readme.txt: ...",
                "tool_calls": [
                    {"tool_name": "file_read", "parameters": {"path": "/data/readme.txt"}, "result": "File content here"}
                ],
            },
            {
                "response_text": "I have written the summary to /data/summary.txt.",
                "tool_calls": [
                    {"tool_name": "file_write", "parameters": {"path": "/data/summary.txt", "content": "Summary"}, "result": "Successfully wrote 7 bytes to /data/summary.txt"}
                ],
            },
        ]
    )


# ---------------------------------------------------------------------------
# Test: MultiTurnEngine directly
# ---------------------------------------------------------------------------

class TestMultiTurnEngine:
    def test_run_session_returns_correct_turn_count(self, mock_harness):
        engine = MultiTurnEngine(
            llm_client=mock_harness,
            system_prompt="You are a helpful assistant.",
            tool_descriptions=[{"name": "get_time", "description": "Get time"}],
            max_turns=3,
            scenario_id="test",
            model="mock",
        )

        queries = ["What time is it?", "Read /data/readme.txt", "Write summary"]
        trace = engine.run_session(queries)

        assert len(trace.turns) == 3

    def test_turn_numbers_are_sequential(self, mock_harness):
        engine = MultiTurnEngine(
            llm_client=mock_harness,
            system_prompt="Test",
            tool_descriptions=[],
            max_turns=3,
            scenario_id="test",
            model="mock",
        )
        trace = engine.run_session(["q1", "q2", "q3"])
        assert [t.turn_number for t in trace.turns] == [1, 2, 3]

    def test_each_snapshot_has_nonempty_response(self, mock_harness):
        engine = MultiTurnEngine(
            llm_client=mock_harness,
            system_prompt="Test",
            tool_descriptions=[],
            max_turns=3,
            scenario_id="test",
            model="mock",
        )
        trace = engine.run_session(["q1", "q2", "q3"])
        for snap in trace.turns:
            assert snap.agent_response != ""

    def test_history_grows_each_turn(self, mock_harness):
        engine = MultiTurnEngine(
            llm_client=mock_harness,
            system_prompt="Test",
            tool_descriptions=[],
            max_turns=3,
            scenario_id="test",
            model="mock",
        )
        trace = engine.run_session(["q1", "q2", "q3"])

        # Turn 3 should contain history from turns 1 and 2
        history_lengths = [len(t.full_history) for t in trace.turns]
        assert history_lengths[0] < history_lengths[1] < history_lengths[2]

    def test_max_turns_enforced(self, mock_harness):
        engine = MultiTurnEngine(
            llm_client=mock_harness,
            system_prompt="Test",
            tool_descriptions=[],
            max_turns=2,
            scenario_id="test",
            model="mock",
        )
        with pytest.raises(RuntimeError, match="Max turns"):
            engine.run_session(["q1", "q2", "q3"])

    def test_tool_calls_recorded(self, mock_harness):
        engine = MultiTurnEngine(
            llm_client=mock_harness,
            system_prompt="Test",
            tool_descriptions=[],
            max_turns=3,
            scenario_id="test",
            model="mock",
        )
        trace = engine.run_session(["q1", "q2", "q3"])

        # Turn 1 should have a get_time tool call
        assert trace.turns[0].tool_calls[0].tool_name == "get_time"
        # Turn 2 should have a file_read tool call
        assert trace.turns[1].tool_calls[0].tool_name == "file_read"

    def test_tool_executor_populates_missing_tool_results(self):
        harness = MockAgentHarness(
            responses=[
                {
                    "response_text": "Checking the time now.",
                    "tool_calls": [
                        {"tool_name": "get_time", "parameters": {}, "result": ""}
                    ],
                }
            ]
        )
        engine = MultiTurnEngine(
            llm_client=harness,
            system_prompt="Test",
            tool_descriptions=[],
            max_turns=1,
            scenario_id="tool_exec",
            model="mock",
            tool_executor=lambda tool_name, params: MOCK_TIMESTAMP,
        )

        snapshot = engine.run_turn("What time is it?")

        assert snapshot.tool_calls[0].result == MOCK_TIMESTAMP
        assert snapshot.full_history[-1]["content"] == MOCK_TIMESTAMP


# ---------------------------------------------------------------------------
# Test: JSON serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_session_trace_json_roundtrip(self, mock_harness):
        engine = MultiTurnEngine(
            llm_client=mock_harness,
            system_prompt="Test",
            tool_descriptions=[{"name": "get_time", "description": "Get time"}],
            max_turns=3,
            scenario_id="roundtrip_test",
            model="mock",
        )
        trace = engine.run_session(["q1", "q2", "q3"])

        # Serialize
        json_str = trace.model_dump_json(indent=2)
        data = json.loads(json_str)

        # Deserialize
        restored = SessionTrace.model_validate(data)

        assert restored.scenario_id == trace.scenario_id
        assert len(restored.turns) == len(trace.turns)
        assert restored.turns[0].user_query == trace.turns[0].user_query

    def test_save_trace_to_disk(self, mock_harness, tmp_path):
        engine = MultiTurnEngine(
            llm_client=mock_harness,
            system_prompt="Test",
            tool_descriptions=[],
            max_turns=3,
            scenario_id="disk_test",
            model="mock",
        )
        trace = engine.run_session(["q1", "q2", "q3"])
        path = engine.save_trace(trace, str(tmp_path))

        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["scenario_id"] == "disk_test"
        assert len(loaded["turns"]) == 3


# ---------------------------------------------------------------------------
# Test: MockAgentHarness
# ---------------------------------------------------------------------------

class TestMockAgentHarness:
    def test_string_responses(self):
        harness = MockAgentHarness(responses=["hello", "world"])
        r1 = harness.run_turn("sys", [], [], "q1")
        r2 = harness.run_turn("sys", [], [], "q2")
        assert r1.response_text == "hello"
        assert r2.response_text == "world"

    def test_fallback_response(self):
        harness = MockAgentHarness(responses=[])
        result = harness.run_turn("sys", [], [], "test query")
        assert "test query" in result.response_text

    def test_dict_responses_with_tool_calls(self):
        harness = MockAgentHarness(
            responses=[
                {
                    "response_text": "Done",
                    "tool_calls": [
                        {"tool_name": "file_read", "parameters": {"path": "/a"}, "result": "data"}
                    ],
                }
            ]
        )
        result = harness.run_turn("sys", [], [], "q")
        assert result.response_text == "Done"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "file_read"


class TestAnthropicMessageBuild:
    def test_tool_results_are_preserved_in_replayed_history(self):
        messages = _build_api_messages(
            [
                {"role": "user", "content": "Read the file."},
                {"role": "assistant", "content": "I will read it."},
                {
                    "role": "tool_result",
                    "tool_name": "file_read",
                    "content": "Important file contents",
                },
            ],
            "Summarize it.",
        )

        assert messages[2]["role"] == "user"
        assert "Tool result from file_read" in messages[2]["content"]
        assert "Important file contents" in messages[2]["content"]


# ---------------------------------------------------------------------------
# Test: ScenarioRunner end-to-end integration
# ---------------------------------------------------------------------------

class TestScenarioRunner:
    def test_run_scenario_from_fixture(self, mock_harness, tmp_path):
        runner = ScenarioRunner(harness=mock_harness, output_dir=str(tmp_path))
        scenario_path = str(FIXTURES_DIR / "test_benign_3turn.json")

        trace = runner.run_scenario(scenario_path)

        # Verify 3 turns
        assert len(trace.turns) == 3
        assert trace.scenario_id == "test_benign_3turn"

        # Verify each snapshot
        assert trace.turns[0].user_query == "What time is it?"
        assert trace.turns[1].user_query == "Read the file /data/readme.txt"
        assert trace.turns[2].user_query == "Write a summary to /data/summary.txt"

        # Verify responses are populated
        for snap in trace.turns:
            assert snap.agent_response != ""

        # Verify history accumulates
        assert len(trace.turns[2].full_history) > len(trace.turns[0].full_history)

        # Verify trace was saved
        saved = list(tmp_path.glob("*.json"))
        assert len(saved) == 1

    def test_run_scenario_dict(self, mock_harness, tmp_path):
        runner = ScenarioRunner(harness=mock_harness, output_dir=str(tmp_path))
        scenario = {
            "scenario_id": "inline_test",
            "turns": [
                {"turn": 1, "user_query": "Hello"},
                {"turn": 2, "user_query": "Goodbye"},
            ],
        }

        # Need a 2-response harness
        harness = MockAgentHarness(responses=["Hi there!", "See you!"])
        runner2 = ScenarioRunner(harness=harness, output_dir=str(tmp_path))
        trace = runner2.run_scenario_dict(scenario)

        assert len(trace.turns) == 2
        assert trace.scenario_id == "inline_test"

    def test_run_batch(self, mock_harness, tmp_path):
        runner = ScenarioRunner(harness=mock_harness, output_dir=str(tmp_path))
        traces = runner.run_batch(str(FIXTURES_DIR))

        # Should find at least the one fixture file
        assert len(traces) >= 1
        assert traces[0].scenario_id == "test_benign_3turn"

    def test_runner_executes_mock_tool_when_result_missing(self, tmp_path):
        harness = MockAgentHarness(
            responses=[
                {
                    "response_text": "Fetching the current time.",
                    "tool_calls": [
                        {"tool_name": "get_time", "parameters": {}, "result": ""}
                    ],
                }
            ]
        )
        runner = ScenarioRunner(harness=harness, output_dir=str(tmp_path))
        scenario = {
            "scenario_id": "tool_execution_trace",
            "turns": [{"turn": 1, "user_query": "What time is it?"}],
        }

        trace = runner.run_scenario_dict(scenario)

        assert trace.turns[0].tool_calls[0].result == MOCK_TIMESTAMP
