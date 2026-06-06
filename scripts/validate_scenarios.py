"""Validate all benchmark attack scenarios against schema and semantics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcpdrift.harness.scenario_runner import (  # noqa: E402
    _load_scenario,
    _validate_scenario,
    list_benchmark_scenarios,
)


def main() -> int:
    errors: list[str] = []
    scenario_files = list_benchmark_scenarios()

    for path in scenario_files:
        try:
            _validate_scenario(_load_scenario(str(path)))
        except Exception as error:
            errors.append(f"{path.relative_to(ROOT)}: {error}")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print(f"All scenarios valid ({len(scenario_files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
