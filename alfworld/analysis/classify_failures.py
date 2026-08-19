"""Classify observable failure modes using deterministic trajectory rules."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.experiment_common import ROOT, rows_from, write_json


def classify(row: dict) -> str:
    termination = row.get("termination")
    if termination == "invalid_model_output":
        return "format_failure"
    if termination in {"max_steps", "generation_length_failure"}:
        return "max_steps" if termination == "max_steps" else "generation_length_failure"
    actions = [step.get("action") or "" for step in row.get("trajectory", [])]
    if any(step.get("format_error") for step in row.get("trajectory", [])):
        return "format_failure"
    if any(actions[i] == actions[i - 1] for i in range(1, len(actions))):
        return "redundant_loop"
    goal = (row.get("task") or "").lower()
    if "clean" in goal and "clean " not in " ".join(actions): return "prerequisite_violation"
    if "heat" in goal and "heat " not in " ".join(actions): return "prerequisite_violation"
    if "cool" in goal and "cool " not in " ".join(actions): return "prerequisite_violation"
    if not any(action.startswith("take ") for action in actions) and "pick" in goal:
        return "object_not_found"
    if any(action.startswith("move ") for action in actions): return "premature_placement"
    return "other"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "analysis/failure_taxonomy.json")
    args = parser.parse_args()
    result = {}
    for path in args.results:
        rows = rows_from(path)
        counts = {}
        for row in rows:
            label = classify(row)
            counts[label] = counts.get(label, 0) + 1
        result[str(path)] = {"counts": counts, "n": len(rows)}
    write_json(args.output, result)
    print(result)


if __name__ == "__main__":
    main()
