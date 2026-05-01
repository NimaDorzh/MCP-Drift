from __future__ import annotations

import json
from pathlib import Path

from report_generator import (
    _load_traces,
    _ordered_scenarios,
    build_multi_model_section,
    update_multi_model_report,
)


def test_load_traces_keeps_latest_trace_per_provider_scenario_and_defense(tmp_path: Path) -> None:
    _write_trace(
        tmp_path / "deepseek_old.json",
        provider="deepseek",
        scenario_id="mt_delayed_env",
        defense="no_defense",
        run_timestamp="2026-05-01T18:47:48.261733Z",
        asr=0,
    )
    _write_trace(
        tmp_path / "deepseek_new.json",
        provider="deepseek",
        scenario_id="mt_delayed_env",
        defense="no_defense",
        run_timestamp="2026-05-01T18:49:26.656341Z",
        asr=1,
    )
    _write_trace(
        tmp_path / "together.json",
        provider="together",
        scenario_id="mt_delayed_env",
        defense="no_defense",
        run_timestamp="2026-05-01T18:49:31.230474Z",
        asr=0,
    )

    traces = _load_traces(tmp_path)

    assert len(traces) == 2
    deepseek_trace = next(trace for trace in traces if trace["meta"]["provider"] == "deepseek")
    assert deepseek_trace["meta"]["run_timestamp"] == "2026-05-01T18:49:26.656341Z"
    assert deepseek_trace["verdict"]["asr"] == 1


def test_build_multi_model_section_reports_deduplicated_run_count(tmp_path: Path) -> None:
    for index, scenario_id in enumerate(_ordered_scenarios(), start=1):
        _write_trace(
            tmp_path / f"deepseek_{scenario_id}.json",
            provider="deepseek",
            scenario_id=scenario_id,
            defense="no_defense",
            run_timestamp=f"2026-05-01T18:50:{index:02d}.000000Z",
            asr=1,
        )

    _write_trace(
        tmp_path / "deepseek_mt_delayed_env_older.json",
        provider="deepseek",
        scenario_id="mt_delayed_env",
        defense="no_defense",
        run_timestamp="2026-05-01T18:47:48.261733Z",
        asr=0,
    )

    section = build_multi_model_section(_load_traces(tmp_path))

    assert "| DeepSeek V4 Flash | 100% | 1000 | 0.0000 | 10 |" in section
    assert "| mt_delayed_env | ? | ? | 100% |" in section


def test_update_multi_model_report_replaces_existing_section_with_deduplicated_results(
    tmp_path: Path,
) -> None:
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    report_path = tmp_path / "benchmark_report.md"

    for index, scenario_id in enumerate(_ordered_scenarios(), start=1):
        _write_trace(
            trace_dir / f"deepseek_{scenario_id}.json",
            provider="deepseek",
            scenario_id=scenario_id,
            defense="no_defense",
            run_timestamp=f"2026-05-01T18:50:{index:02d}.000000Z",
            asr=1,
        )

    _write_trace(
        trace_dir / "deepseek_mt_delayed_env_older.json",
        provider="deepseek",
        scenario_id="mt_delayed_env",
        defense="no_defense",
        run_timestamp="2026-05-01T18:47:48.261733Z",
        asr=0,
    )

    report_path.write_text(
        "# MCPDrift Benchmark Report\n\n"
        "## Multi-Model Real LLM Results\n\n"
        "old section\n\n"
        "## 8. Limitations & Future Work\n\n"
        "placeholder\n",
        encoding="utf-8",
    )

    updated = update_multi_model_report(trace_dir=trace_dir, report_path=report_path)

    assert "old section" not in updated
    assert updated.count("## Multi-Model Real LLM Results") == 1
    assert "| DeepSeek V4 Flash | 100% | 1000 | 0.0000 | 10 |" in updated
    assert "## 8. Limitations & Future Work" in updated


def _write_trace(
    path: Path,
    *,
    provider: str,
    scenario_id: str,
    defense: str,
    run_timestamp: str,
    asr: int,
) -> None:
    path.write_text(
        json.dumps(
            {
                "meta": {
                    "provider": provider,
                    "scenario_id": scenario_id,
                    "defense": defense,
                    "run_timestamp": run_timestamp,
                },
                "turns": [],
                "verdict": {
                    "asr": asr,
                    "compromise_turn": 1 if asr else None,
                    "latency_of_compromise": 1000 if asr else None,
                },
            }
        ),
        encoding="utf-8",
    )