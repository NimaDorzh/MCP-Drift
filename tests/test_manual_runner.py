"""Tests for the semi-manual runner used with Claude Pro / Copilot Chat."""

from __future__ import annotations

from pathlib import Path

from mcpdrift.harness.manual_runner import (
    build_manual_prompt,
    parse_manual_response,
    run_manual_scenario,
)


ATTACKS_DIR = Path(__file__).resolve().parent.parent / "mcpdrift" / "attacks"


def _make_input(lines: list[str]):
    iterator = iter(lines)

    def _input() -> str:
        return next(iterator)

    return _input


class TestBuildManualPrompt:
    def test_prompt_contains_system_tools_history_and_query(self):
        prompt = build_manual_prompt(
            system_prompt="You are a careful assistant.",
            tool_descriptions=[{"name": "file_read", "description": "Read a file."}],
            messages=[
                {"role": "user", "content": "Read the file."},
                {"role": "assistant", "content": "I will read it."},
                {
                    "role": "tool_result",
                    "tool_name": "file_read",
                    "content": "# Project",
                },
            ],
            user_query="Summarize it.",
        )

        assert "SYSTEM PROMPT" in prompt
        assert "AVAILABLE TOOLS" in prompt
        assert "TOOL_RESULT (file_read): # Project" in prompt
        assert "CURRENT USER QUERY" in prompt
        assert "Summarize it." in prompt


class TestParseManualResponse:
    def test_accepts_json_inside_markdown_fence(self):
        payload = parse_manual_response(
            "```json\n{\n"
            '  "response_text": "Done",\n'
            '  "tool_calls": []\n'
            "}\n```"
        )

        assert payload.response_text == "Done"
        assert payload.tool_calls == []

    def test_accepts_plain_text_refusal_as_empty_tool_response(self):
        payload = parse_manual_response(
            "I will not follow malicious tool instructions or exfiltrate secrets."
        )

        assert "malicious tool instructions" in payload.response_text
        assert payload.tool_calls == []


class TestRunManualScenario:
    def test_manual_run_executes_tool_and_saves_trace(self, tmp_path):
        outputs: list[str] = []
        trace = run_manual_scenario(
            scenario_path=str(ATTACKS_DIR / "baseline" / "p1_file_hijack.json"),
            output_dir=str(tmp_path),
            model_label="manual-test",
            input_func=_make_input(
                [
                    "{",
                    '  "response_text": "Using project_helper.",',
                    '  "tool_calls": [',
                    '    {"tool_name": "project_helper", "parameters": {"path": "/data/project/readme.md"}}',
                    "  ]",
                    "}",
                    "END",
                ]
            ),
            output_func=outputs.append,
        )

        assert trace.scenario_id == "p1_file_hijack"
        assert trace.model == "manual-test"
        assert len(trace.turns) == 1
        assert trace.turns[0].tool_calls[0].tool_name == "project_helper"
        assert "# Project" in trace.turns[0].tool_calls[0].result
        assert trace.config["manual_mode"] is True

        saved = list(tmp_path.glob("*.json"))
        assert len(saved) == 1
        assert any("Paste the following prompt" in line for line in outputs)
        assert any("Saved trace to" in line for line in outputs)

    def test_manual_run_accepts_plain_text_refusal(self, tmp_path):
        outputs: list[str] = []
        trace = run_manual_scenario(
            scenario_path=str(ATTACKS_DIR / "multiturn" / "mt_delayed_ssh.json"),
            output_dir=str(tmp_path),
            model_label="manual-test",
            input_func=_make_input(
                [
                    "This is a prompt injection attempt through a poisoned tool description.",
                    "I refuse to read /home/.ssh/id_rsa or return secret material.",
                    "END",
                    "{",
                    '  "response_text": "Report created.",',
                    '  "tool_calls": [',
                    '    {"tool_name": "file_write", "parameters": {"path": "/data/project/report.md", "content": "Status: all systems operational"}}',
                    "  ]",
                    "}",
                    "END",
                    "{",
                    '  "response_text": "I refuse to access SSH keys.",',
                    '  "tool_calls": []',
                    "}",
                    "END",
                ]
            ),
            output_func=outputs.append,
        )

        assert len(trace.turns) == 3
        assert trace.turns[0].agent_response.startswith("This is a prompt injection")
        assert trace.turns[0].tool_calls == []
        assert trace.turns[1].tool_calls[0].tool_name == "file_write"
        assert trace.turns[2].tool_calls == []