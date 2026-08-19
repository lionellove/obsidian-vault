"""Deterministically map ALFWorld action strings to procedural events."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from scripts.experiment_common import ROOT, rows_from, write_json


def event_for(action: str) -> str:
    action = action.lower().strip()
    if action.startswith("go to "): return "NAVIGATE"
    if action.startswith("open "): return "OPEN"
    if action.startswith("close "): return "CLOSE"
    if action.startswith("take "): return "TAKE"
    if action.startswith("clean "): return "CLEAN"
    if action.startswith("heat "): return "HEAT"
    if action.startswith("cool "): return "COOL"
    if action.startswith("move "): return "PLACE"
    if action.startswith("examine ") or action == "look": return "SEARCH"
    if action == "inventory": return "STATE_CHECK"
    return "OTHER"


def extract(row: dict) -> dict:
    events = []
    seen_locations = set()
    repeated_locations = 0
    for step in row.get("trajectory", []):
        action = step.get("action")
        if not action:
            if step.get("format_error"): events.append({"event": "INVALID_ACTION", "step": step.get("step")})
            continue
        event = event_for(action)
        location = None
        match = re.search(r"(?:go to|examine|open|close) (.+)$", action.lower())
        if match and event in {"NAVIGATE", "SEARCH", "OPEN", "CLOSE"}:
            location = match.group(1)
            if event in {"SEARCH", "NAVIGATE"}:
                if location in seen_locations: repeated_locations += 1
                seen_locations.add(location)
        events.append({"event": event, "action": action, "step": step.get("step"), "location": location})
    return {"task_id": row.get("task_id"), "task": row.get("task"), "task_type": row.get("task_type"), "success": row.get("success"), "steps": row.get("steps"), "events": events, "unique_locations": len(seen_locations), "repeated_locations": repeated_locations}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "analysis/behavioral_events.json")
    args = parser.parse_args()
    payload = {str(path): [extract(row) for row in rows_from(path)] for path in args.results}
    write_json(args.output, payload)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
