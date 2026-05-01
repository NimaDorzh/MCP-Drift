from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROOT_DIR = Path(__file__).resolve().parent
ATTACKS_DIR = ROOT_DIR / "mcpdrift" / "attacks"
DEFAULT_TRACE_DIR = ROOT_DIR / "traces"
DEFAULT_REPORT_PATH = ROOT_DIR / "results" / "benchmark_report.md"
SECTION_HEADING = "## Multi-Model Real LLM Results"

PROVIDER_COLUMNS: list[tuple[str, str]] = [
    ("anthropic", "Claude 4.6"),
    ("together", "Llama 3.3 70B"),
    ("deepseek", "DeepSeek V4 Flash"),
]


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
    traces = _load_traces(trace_dir)
    section = build_multi_model_section(traces)

    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else "# MCPDrift Benchmark Report\n"
    updated = _replace_or_append_section(report_text, section)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(updated, encoding="utf-8")
    return updated


def build_multi_model_section(traces: list[dict[str, Any]]) -> str:
    lines: list[str] = [f"{SECTION_HEADING}\n"]

    if not traces:
        lines.append("No real-model traces found in traces/.\n")
        return "\n".join(lines)

    no_defense_traces = [
        trace for trace in traces if trace.get("meta", {}).get("defense") == "no_defense"
    ]

    lines.append("Summary over `no_defense` traces:\n")
    lines.append("| Model | ASR@max | Mean latency of compromise (ms) | Degradation rate | Runs |")
    lines.append("|-------|---------|---------------------------------|------------------|------|")
    for provider_name, display_name in PROVIDER_COLUMNS:
        summary = _compute_provider_summary(no_defense_traces, provider_name)
        lines.append(
            f"| {display_name} | {summary['asr_max']} | {summary['mean_latency']} | {summary['degradation_rate']} | {summary['runs']} |"
        )

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


def _load_traces(trace_dir: Path) -> list[dict[str, Any]]:
    if not trace_dir.exists():
        return []

    latest_by_key: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
    for trace_path in sorted(trace_dir.glob("*.json")):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        key = _trace_identity(trace)
        timestamp = _trace_timestamp(trace)
        current = latest_by_key.get(key)
        if current is None or timestamp >= current[0]:
            latest_by_key[key] = (timestamp, trace)

    deduplicated = sorted(
        latest_by_key.values(),
        key=lambda item: (item[1].get("meta", {}).get("provider", ""), item[1].get("meta", {}).get("scenario_id", ""), item[1].get("meta", {}).get("defense", "")),
    )
    return [trace for _timestamp, trace in deduplicated]


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
    turns = np.array(list(range(1, max_turns + 1)), dtype=np.float64)
    for turn_index in range(1, max_turns + 1):
        compromised_by_turn = 0
        for trace in traces:
            compromise_turn = trace.get("verdict", {}).get("compromise_turn")
            if compromise_turn is not None and int(compromise_turn) <= turn_index:
                compromised_by_turn += 1
        aggregated.append(compromised_by_turn / len(traces))

    coeffs = np.polyfit(turns, np.array(aggregated, dtype=np.float64), deg=1)
    return float(coeffs[0])


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