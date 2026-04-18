"""End-to-end pipeline integration tests.

Exercise the full flow: scenario JSON -> ScenarioRunner -> TurnJudge ->
TurnScorer -> compute_all_metrics, with a deterministic MockAgentHarness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcpdrift.evaluation.judge import TurnJudge
from mcpdrift.evaluation.metrics import (
    BenchmarkMetrics,
    compute_all_metrics,
    compute_recovery_rate,
)
from mcpdrift.evaluation.turn_scorer import TurnScorer
from mcpdrift.harness.agent_harness import MockAgentHarness
from mcpdrift.harness.scenario_runner import ScenarioRunner


ATTACKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "mcpdrift"
    / "attacks"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class TestEndToEndPipeline:
    """Full pipeline on a real baseline scenario JSON."""

    def test_baseline_scenario_runs_through_metrics(self, tmp_path):
        scenario_path = ATTACKS_DIR / "baseline" / "p1_email_redirect.json"
        scenario = _load(scenario_path)

        # Deterministic harness: agent calls the poisoned tool directly.
        harness = MockAgentHarness(
            responses=[
                {
                    "response_text": "Sending the email now.",
                    "tool_calls": [
                        {
                            "tool_name": "email_optimizer",
                            "parameters": {
                                "to": "alice@company.com",
                                "subject": "Weekly Report",
                                "body": "Please find the weekly report attached.",
                            },
                            "result": "",
                        }
                    ],
                }
            ]
        )

        runner = ScenarioRunner(harness=harness, output_dir=str(tmp_path))
        trace = runner.run_scenario_dict(scenario)

        # Trace shape
        assert trace.scenario_id == "p1_email_redirect"
        assert len(trace.turns) == 1
        assert trace.turns[0].tool_calls[0].tool_name == "email_optimizer"

        # Judge -> Score -> Metrics
        judge = TurnJudge(
            poisoned_tool_name=scenario["poisoned_tool"]["name"],
            attacker_goal=scenario["attacker_goal"],
            user_goal=scenario["user_goal"],
        )
        verdicts = judge.judge_session(trace.turns)
        assert verdicts[0].label == "direct_execution"

        scorer = TurnScorer(poisoned_tool_name=scenario["poisoned_tool"]["name"])
        scored = scorer.score_session(trace, verdicts)

        metrics = compute_all_metrics(
            [scored],
            session_classes={scenario["scenario_id"]: scenario["attack_class"]},
        )
        assert isinstance(metrics, BenchmarkMetrics)
        assert metrics.asr_by_turn[1] == 1.0
        assert metrics.mean_latency == 1.0
        assert metrics.recovery_rate is None  # no removal_turn in this scenario

    def test_removal_turn_drives_recovery_metric(self, tmp_path):
        """Inject a multi-turn scenario with removal_turn; recovery_rate non-None."""
        scenario_path = ATTACKS_DIR / "multiturn" / "mt_priming_escalation.json"
        scenario = _load(scenario_path)
        scenario["removal_turn"] = 1  # remove poisoned tool after turn 1
        poisoned_name = scenario["poisoned_tool"]["name"]

        # Turn 1: agent uses poisoned tool (attack succeeds).
        # Turns 2..N: agent only calls a legitimate tool (recovery).
        responses: list[dict[str, Any]] = [
            {
                "response_text": "Running scan.",
                "tool_calls": [
                    {
                        "tool_name": poisoned_name,
                        "parameters": {"action": "scan"},
                        "result": "",
                    }
                ],
            }
        ]
        for _ in range(len(scenario["turns"]) - 1):
            responses.append(
                {
                    "response_text": "Reading benign file.",
                    "tool_calls": [
                        {
                            "tool_name": "file_read",
                            "parameters": {"path": "/data/readme.txt"},
                            "result": "",
                        }
                    ],
                }
            )

        harness = MockAgentHarness(responses=responses)
        runner = ScenarioRunner(harness=harness, output_dir=str(tmp_path))
        trace = runner.run_scenario_dict(scenario)

        # After turn 1, the poisoned tool should be dropped from the
        # advertised tool set.
        advertised_names_after = {
            td.get("name")
            for td in trace.turns[-1].tool_descriptions
        }
        assert poisoned_name not in advertised_names_after

        judge = TurnJudge(
            poisoned_tool_name=poisoned_name,
            attacker_goal=scenario["attacker_goal"],
            user_goal=scenario["user_goal"],
        )
        verdicts = judge.judge_session(trace.turns)
        scorer = TurnScorer(poisoned_tool_name=poisoned_name)
        scored = scorer.score_session(trace, verdicts)

        rate = compute_recovery_rate([scored], removal_turn=1)
        assert rate == 1.0
