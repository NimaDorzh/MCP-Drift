from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from mcpdrift.environments.multi_turn_engine import SessionTrace
from mcpdrift.evaluation.judge import TurnJudge


ROOT_DIR = Path(__file__).resolve().parent
ATTACKS_DIR = ROOT_DIR / "mcpdrift" / "attacks"
DEFAULT_TRACE_DIR = ROOT_DIR / "traces"
DEFAULT_MANUAL_TRACE_DIR = ROOT_DIR / "results" / "traces"
DEFAULT_REPORT_PATH = ROOT_DIR / "results" / "benchmark_report.md"
SECTION_HEADING = "## Multi-Model Real LLM Results"

PROVIDER_COLUMNS: list[tuple[str, str]] = [
    ("anthropic", "Claude 4.6 †"),
    ("together", "Llama 3.3 70B"),
    ("deepseek", "DeepSeek V4 Flash"),
]

MANUAL_RUNNER_FOOTNOTE = "† Manual runner, n=1 per scenario; not directly comparable to automated sweep results."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update the MCPDrift benchmark report with multi-model real-run results."
    )
    parser.add_argument("--trace-dir", default=str(DEFAULT_TRACE_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args(argv)

    update_multi_model_report(
        trace_dir=Path(args.trace_dir),
        report_path=Path(args.report_path),
    )
    return 0


def update_multi_model_report(trace_dir: Path, report_path: Path) -> str:
    traces = _load_traces(_default_trace_dirs(trace_dir))
    section = build_multi_model_section(traces)

    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else "# MCPDrift Benchmark Report\n"
    updated = _replace_or_append_section(report_text, section)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(updated, encoding="utf-8")
    return updated


def _default_trace_dirs(trace_dir: Path) -> list[Path]:
    try:
        resolved = trace_dir.resolve()
    except OSError:
        resolved = trace_dir

    if resolved in {DEFAULT_TRACE_DIR.resolve(), DEFAULT_MANUAL_TRACE_DIR.resolve()}:
        return [DEFAULT_TRACE_DIR, DEFAULT_MANUAL_TRACE_DIR]
    return [trace_dir]


def build_multi_model_section(traces: list[dict[str, Any]]) -> str:
    lines: list[str] = [f"{SECTION_HEADING}\n"]

    if not traces:
        lines.append("No real-model traces found in traces/.\n")
        return "\n".join(lines)

    no_defense_traces = [
        trace for trace in traces if trace.get("meta", {}).get("defense") == "no_defense"
    ]

    lines.append("Summary over `no_defense` traces:\n")
    lines.append("| Model | ASR@max | Mean cumulative API latency (ms) | Degradation rate | Runs |")
    lines.append("|-------|---------|----------------------------------|------------------|------|")
    for provider_name, display_name in PROVIDER_COLUMNS:
        summary = _compute_provider_summary(no_defense_traces, provider_name)
        lines.append(
            f"| {display_name} | {summary['asr_max']} | {summary['mean_latency']} | {summary['degradation_rate']} | {summary['runs']} |"
        )

    lines.append("")
    lines.append(MANUAL_RUNNER_FOOTNOTE)

    lines.append("")
    lines.append("| Scenario | Claude 4.6 | Llama 3.3 70B | DeepSeek V4 Flash |")
    lines.append("|----------|------------|---------------|--------------------|")
    scenario_ids = _ordered_scenarios()
    scenario_matrix = _scenario_percentages(no_defense_traces)
    for scenario_id in scenario_ids:
        row = [scenario_id]
        for provider_name, _display_name in PROVIDER_COLUMNS:
            values = scenario_matrix.get((scenario_id, provider_name))
            row.append(_format_percent(values))
        lines.append(f"| {' | '.join(row)} |")

    return "\n".join(lines)


def _load_traces(trace_dir: Path | Iterable[Path]) -> list[dict[str, Any]]:
    trace_dirs = [trace_dir] if isinstance(trace_dir, Path) else list(trace_dir)

    latest_by_key: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
    for base_dir in _dedupe_paths(trace_dirs):
        if not base_dir.exists():
            continue

        for trace_path in sorted(base_dir.rglob("*.json")):
            try:
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue

            normalized = _normalize_trace(trace, trace_path)
            if normalized is None:
                continue

            key = _trace_identity(normalized)
            timestamp = _trace_timestamp(normalized)
            current = latest_by_key.get(key)
            if current is None or timestamp >= current[0]:
                latest_by_key[key] = (timestamp, normalized)

    deduplicated = sorted(
        latest_by_key.values(),
        key=lambda item: (item[1].get("meta", {}).get("provider", ""), item[1].get("meta", {}).get("scenario_id", ""), item[1].get("meta", {}).get("defense", "")),
    )
    return [trace for _timestamp, trace in deduplicated]


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def _normalize_trace(trace: dict[str, Any], trace_path: Path) -> dict[str, Any] | None:
    if "meta" in trace and "verdict" in trace:
        return trace

    if {"scenario_id", "model", "turns"}.issubset(trace):
        return _normalize_manual_trace(trace, trace_path)

    return None


def _normalize_manual_trace(trace: dict[str, Any], trace_path: Path) -> dict[str, Any] | None:
    scenario_id = str(trace.get("scenario_id", ""))
    model = str(trace.get("model", ""))
    provider = _infer_provider(model)
    scenario = _load_scenario_definition(scenario_id)
    if not scenario_id or provider is None or scenario is None:
        return None

    session_trace = SessionTrace.model_validate(trace)
    judge = TurnJudge(
        poisoned_tool_name=scenario["poisoned_tool"]["name"],
        attacker_goal=scenario["attacker_goal"],
        user_goal=scenario["user_goal"],
        poisoned_tool_result_poison=scenario["poisoned_tool"].get("result_poison"),
    )
    verdicts = judge.judge_session(session_trace.turns)
    compromise_turn = next(
        (verdict.turn_number for verdict in verdicts if verdict.attacker_goal_satisfied),
        None,
    )

    return {
        "meta": {
            "provider": provider,
            "model": model,
            "scenario_id": scenario_id,
            "defense": "no_defense",
            "run_timestamp": _manual_trace_timestamp(trace, trace_path),
        },
        "turns": trace.get("turns", []),
        "verdict": {
            "compromised": compromise_turn is not None,
            "compromise_turn": compromise_turn,
            # Manual traces do not record provider latency in milliseconds.
            "latency_of_compromise": None,
            "asr": int(compromise_turn is not None),
        },
    }


def _infer_provider(model: str) -> str | None:
    lower_model = model.lower()
    if "claude" in lower_model:
        return "anthropic"
    if "llama" in lower_model:
        return "together"
    if "deepseek" in lower_model:
        return "deepseek"
    return None


def _manual_trace_timestamp(trace: dict[str, Any], trace_path: Path) -> str:
    turns = trace.get("turns", [])
    if turns:
        timestamp = str(turns[-1].get("timestamp", ""))
        if timestamp:
            return timestamp

    stem = trace_path.stem
    if "_" in stem:
        return stem.rsplit("_", maxsplit=1)[-1]
    return stem


@lru_cache(maxsize=None)
def _load_scenario_definition(scenario_id: str) -> dict[str, Any] | None:
    for folder_name in ("baseline", "multiturn"):
        scenario_path = ATTACKS_DIR / folder_name / f"{scenario_id}.json"
        if scenario_path.exists():
            return json.loads(scenario_path.read_text(encoding="utf-8"))
    return None


def _trace_identity(trace: dict[str, Any]) -> tuple[str, str, str]:
    meta = trace.get("meta", {})
    return (
        str(meta.get("provider", "")),
        str(meta.get("scenario_id", "")),
        str(meta.get("defense", "")),
    )


def _trace_timestamp(trace: dict[str, Any]) -> str:
    meta = trace.get("meta", {})
    return str(meta.get("run_timestamp", ""))


def _ordered_scenarios() -> list[str]:
    scenario_ids: list[str] = []
    for folder_name in ("baseline", "multiturn"):
        for path in sorted((ATTACKS_DIR / folder_name).glob("*.json")):
            scenario_ids.append(path.stem)
    return scenario_ids


def _scenario_percentages(traces: list[dict[str, Any]]) -> dict[tuple[str, str], list[int]]:
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for trace in traces:
        meta = trace.get("meta", {})
        key = (str(meta.get("scenario_id", "")), str(meta.get("provider", "")))
        grouped[key].append(int(trace.get("verdict", {}).get("asr", 0)))
    return grouped


def _compute_provider_summary(traces: list[dict[str, Any]], provider_name: str) -> dict[str, str]:
    provider_traces = [trace for trace in traces if trace.get("meta", {}).get("provider") == provider_name]
    if not provider_traces:
        return {
            "asr_max": "?",
            "mean_latency": "?",
            "degradation_rate": "?",
            "runs": "0",
        }

    compromises = [int(trace.get("verdict", {}).get("asr", 0)) for trace in provider_traces]
    asr_max = sum(compromises) / len(compromises)

    latencies = [
        float(latency)
        for trace in provider_traces
        if (latency := trace.get("verdict", {}).get("latency_of_compromise")) is not None
    ]
    mean_latency = f"{(sum(latencies) / len(latencies)):.0f}" if latencies else "N/A"

    degradation_rate = _compute_degradation_rate(provider_traces)
    return {
        "asr_max": f"{asr_max:.0%}",
        "mean_latency": mean_latency,
        "degradation_rate": f"{degradation_rate:.4f}",
        "runs": str(len(provider_traces)),
    }


def _compute_degradation_rate(traces: list[dict[str, Any]]) -> float:
    if not traces:
        return 0.0

    max_turns = max(len(trace.get("turns", [])) for trace in traces)
    if max_turns < 2:
        return 0.0

    aggregated: list[float] = []
    turns = list(range(1, max_turns + 1))
    for turn_index in range(1, max_turns + 1):
        compromised_by_turn = 0
        for trace in traces:
            compromise_turn = trace.get("verdict", {}).get("compromise_turn")
            if compromise_turn is not None and int(compromise_turn) <= turn_index:
                compromised_by_turn += 1
        aggregated.append(compromised_by_turn / len(traces))

    x_mean = sum(turns) / len(turns)
    y_mean = sum(aggregated) / len(aggregated)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(turns, aggregated))
    denominator = sum((x - x_mean) ** 2 for x in turns)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _format_percent(values: list[int] | None) -> str:
    if not values:
        return "?"
    return f"{(sum(values) / len(values)):.0%}"


def _replace_or_append_section(report_text: str, section_text: str) -> str:
    escaped_heading = re.escape(SECTION_HEADING)
    pattern = re.compile(
        rf"{escaped_heading}.*?(?=^##\s+|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    if pattern.search(report_text):
        return pattern.sub(section_text.rstrip() + "\n\n", report_text)

    insertion_match = re.search(r"^##\s+8\. Limitations & Future Work", report_text, re.MULTILINE)
    if insertion_match:
        return report_text[: insertion_match.start()] + section_text.rstrip() + "\n\n" + report_text[insertion_match.start():]

    return report_text.rstrip() + "\n\n" + section_text.rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())