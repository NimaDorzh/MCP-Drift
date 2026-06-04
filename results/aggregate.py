"""Aggregate raw MCPDrift runs into per-cell ASR with Wilson 95% confidence intervals.

Reads every JSON trace under ``results/raw/**/*.json``, groups runs by
``(model, scenario)`` and computes, for each cell:

* ``successes`` — number of runs the judge marked ``COMPROMISED``
* ``mean_asr`` — ``successes / n_runs``
* ``ci_lower`` / ``ci_upper`` — Wilson 95% confidence interval

Outputs:

1. ``results/aggregate.csv``
2. ``results/aggregate_table.md``
3. A per-model summary on stdout.

Run with ``python results/aggregate.py``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from statsmodels.stats.proportion import proportion_confint

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from multi_runner import load_scenario_definition, rejudge_trace_payload


RESULTS_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_DIR = RESULTS_DIR / "raw"
DEFAULT_CSV_PATH = RESULTS_DIR / "aggregate.csv"
DEFAULT_MARKDOWN_PATH = RESULTS_DIR / "aggregate_table.md"

CSV_COLUMNS = ["model", "scenario", "n_runs", "successes", "mean_asr", "ci_lower", "ci_upper"]


@dataclass(frozen=True)
class CellResult:
    model: str
    scenario: str
    n_runs: int
    successes: int
    mean_asr: float
    ci_lower: float
    ci_upper: float


def _is_compromised(trace: dict) -> bool:
    verdict = trace.get("verdict", {})
    if isinstance(verdict, dict):
        return bool(verdict.get("compromised"))
    return False


def _cell_keys(raw_dir: Path, trace_path: Path, trace: dict) -> tuple[str, str]:
    """Resolve ``(model, scenario)`` for a trace.

    Prefers the ``results/raw/{model}/{scenario}/run_*.json`` directory layout
    and falls back to the trace ``meta`` block when the file lives elsewhere.
    """
    try:
        relative = trace_path.relative_to(raw_dir)
        parts = relative.parts
    except ValueError:
        parts = ()

    if len(parts) >= 3:
        return parts[0], parts[1]

    meta = trace.get("meta", {})
    model = str(meta.get("model", "unknown"))
    scenario = str(meta.get("scenario_id", "unknown"))
    return model, scenario


def aggregate(raw_dir: Path) -> list[CellResult]:
    cells: dict[tuple[str, str], list[bool]] = {}

    for trace_path in sorted(raw_dir.rglob("*.json")):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        model, scenario = _cell_keys(raw_dir, trace_path, trace)
        cells.setdefault((model, scenario), []).append(_is_compromised(trace))

    results: list[CellResult] = []
    for (model, scenario), outcomes in sorted(cells.items()):
        n_runs = len(outcomes)
        successes = sum(1 for outcome in outcomes if outcome)
        mean_asr = successes / n_runs if n_runs else 0.0
        ci_lower, ci_upper = proportion_confint(
            successes, n_runs, alpha=0.05, method="wilson"
        )
        results.append(
            CellResult(
                model=model,
                scenario=scenario,
                n_runs=n_runs,
                successes=successes,
                mean_asr=mean_asr,
                ci_lower=float(ci_lower),
                ci_upper=float(ci_upper),
            )
        )
    return results


def rerun_judge(raw_dir: Path, provider_filter: str | None = None) -> int:
    updated = 0
    for trace_path in sorted(raw_dir.rglob("*.json")):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if provider_filter and not _matches_provider_filter(provider_filter, raw_dir, trace_path, trace):
            continue

        _model, scenario_id = _cell_keys(raw_dir, trace_path, trace)
        scenario = load_scenario_definition(scenario_id)
        if scenario is None:
            continue

        updated_trace = rejudge_trace_payload(trace, scenario)
        trace_path.write_text(json.dumps(updated_trace, indent=2), encoding="utf-8")
        updated += 1
    return updated


def write_csv(results: list[CellResult], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for cell in results:
            writer.writerow(
                [
                    cell.model,
                    cell.scenario,
                    cell.n_runs,
                    cell.successes,
                    f"{cell.mean_asr:.4f}",
                    f"{cell.ci_lower:.4f}",
                    f"{cell.ci_upper:.4f}",
                ]
            )


def render_markdown(results: list[CellResult]) -> str:
    lines = [
        "| Model | Scenario | N | Mean ASR | 95% CI |",
        "|---|---|---|---|---|",
    ]
    for cell in results:
        lines.append(
            f"| {cell.model} | {cell.scenario} | {cell.n_runs} | "
            f"{cell.mean_asr:.2f} | [{cell.ci_lower:.2f}, {cell.ci_upper:.2f}] |"
        )
    return "\n".join(lines) + "\n"


def write_markdown(results: list[CellResult], markdown_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(results), encoding="utf-8")


def render_summary(results: list[CellResult]) -> str:
    by_model: dict[str, list[CellResult]] = {}
    for cell in results:
        by_model.setdefault(cell.model, []).append(cell)

    lines = ["Per-model summary:"]
    for model, cells in sorted(by_model.items()):
        mean_asr = sum(cell.mean_asr for cell in cells) / len(cells)
        mean_ci_width = sum(
            cell.ci_upper - cell.ci_lower for cell in cells
        ) / len(cells)
        lines.append(
            f"  {model}: mean ASR {mean_asr:.3f} ± {mean_ci_width:.3f} "
            f"(mean 95% CI width, {len(cells)} scenarios)"
        )
    return "\n".join(lines)


def _matches_provider_filter(
    provider_filter: str,
    raw_dir: Path,
    trace_path: Path,
    trace: dict,
) -> bool:
    normalized_filter = _normalize_model_slug(provider_filter)
    model, _scenario = _cell_keys(raw_dir, trace_path, trace)
    meta = trace.get("meta", {})
    provider = str(meta.get("provider", ""))
    meta_model = str(meta.get("model", ""))
    return normalized_filter in {
        _normalize_model_slug(model),
        _normalize_model_slug(meta_model),
        _normalize_model_slug(provider),
    }


def _normalize_model_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR), help="Directory of raw run traces.")
    parser.add_argument("--csv-path", default=str(DEFAULT_CSV_PATH), help="Output CSV path.")
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN_PATH), help="Output markdown table path.")
    parser.add_argument(
        "--rerun-judge",
        action="store_true",
        help="Re-apply the local deterministic judge to existing raw traces before aggregating.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Optional model/provider filter to limit --rerun-judge to matching traces.",
    )
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw_dir)
    if not raw_dir.exists():
        print(f"No raw runs found at {raw_dir}")
        return 1

    if args.rerun_judge:
        updated = rerun_judge(raw_dir, provider_filter=args.provider)
        if updated == 0:
            print("Re-judge completed but no matching traces were updated.")
        else:
            print(f"Re-judged {updated} trace files under {raw_dir}")

    results = aggregate(raw_dir)
    if not results:
        print(f"No traces found under {raw_dir}")
        return 1

    write_csv(results, Path(args.csv_path))
    write_markdown(results, Path(args.markdown_path))

    print(f"Wrote {len(results)} cells to {args.csv_path} and {args.markdown_path}")
    print(render_summary(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
