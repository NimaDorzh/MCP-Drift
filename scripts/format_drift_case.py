"""Format a saved drift case as a human-readable dialog for the paper.

Reads a drift case JSON (as produced by ``scripts/hunt_drift.py`` or a
``--log-full-dialog`` trace) and prints each turn labelled SAFE or
COMPROMISED, ready to paste into Figure 1.

Usage::

    python scripts/format_drift_case.py results/drift_cases/<model>/<file>.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _turns_from_full_dialog(full_dialog: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Group a flat full_dialog list into per-turn {user, assistant, tool_calls}."""
    turns: dict[int, dict[str, Any]] = {}
    for entry in full_dialog:
        turn = int(entry.get("turn", 0))
        slot = turns.setdefault(turn, {"user": "", "assistant": "", "tool_calls": []})
        role = entry.get("role")
        if role == "user":
            slot["user"] = str(entry.get("content", ""))
        elif role == "assistant":
            slot["assistant"] = str(entry.get("content", ""))
            slot["tool_calls"] = [
                f"{call.get('name')}({json.dumps(call.get('args', {}))})"
                for call in entry.get("tool_calls", [])
            ]
    return turns


def _turns_from_trace(turns_list: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    turns: dict[int, dict[str, Any]] = {}
    for turn in turns_list:
        number = int(turn.get("turn", 0))
        turns[number] = {
            "user": str(turn.get("user_query", "")),
            "assistant": str(turn.get("response_text", "")),
            "tool_calls": [
                f"{call.get('tool_name')}({json.dumps(call.get('parameters', {}))})"
                for call in turn.get("tool_calls_made", [])
            ],
        }
    return turns


def format_drift_case(path: Path) -> str:
    trace = json.loads(path.read_text(encoding="utf-8"))
    compromise_turn = trace.get("verdict", {}).get("compromise_turn")

    full_dialog = trace.get("full_dialog")
    if full_dialog:
        turns = _turns_from_full_dialog(full_dialog)
    else:
        turns = _turns_from_trace(trace.get("turns", []))

    lines: list[str] = []
    for number in sorted(turns):
        slot = turns[number]
        compromised = compromise_turn is not None and number >= int(compromise_turn)
        label = "COMPROMISED \u26a0" if compromised else "SAFE"
        lines.append(f"[Turn {number} \u2014 {label}]")
        lines.append(f"User: {slot['user']}")
        lines.append(f"Assistant: {slot['assistant']}")
        if slot["tool_calls"]:
            lines.append("Tool calls: " + "; ".join(slot["tool_calls"]))
        else:
            lines.append("Tool calls: none")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Format a drift case JSON as a paper-ready dialog.")
    parser.add_argument("path", help="Path to a drift case JSON file.")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        parser.error(f"File not found: {path}")

    print(format_drift_case(path), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
