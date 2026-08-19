"""Live protocol test for installed Ollama candidates.

Run with: python tests/test_model_protocol.py --models qwen3:4b-instruct ministral-3:3b
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_alf_bench as bench


CASES = [
    ("You need to inspect what you are currently carrying.", ["go to cabinet 1", "inventory", "look"], "inventory"),
    ("The fridge 1 is closed. You must inspect its contents.", ["go to fridge 1", "open fridge 1", "inventory"], "open fridge 1"),
    ("Copy the only admissible action exactly.", ["take mug 3 from countertop 2"], "take mug 3 from countertop 2"),
    ("Go to the countertop.", ["go to cabinet 1", "go to countertop 2", "inventory"], "go to countertop 2"),
    ("Open the drawer.", ["open drawer 1", "go to drawer 1", "look"], "open drawer 1"),
    ("Inspect the object.", ["examine mug 1", "take mug 1 from shelf 1", "inventory"], "examine mug 1"),
    ("Pick up the spoon.", ["take spoon 1 from countertop 1", "go to sinkbasin 1", "look"], "take spoon 1 from countertop 1"),
    ("Navigate to the sink.", ["go to sinkbasin 1", "go to stoveburner 1", "inventory"], "go to sinkbasin 1"),
    ("Clean the mug.", ["clean mug 1 with sinkbasin 1", "go to sinkbasin 1", "inventory"], "clean mug 1 with sinkbasin 1"),
    ("Heat the potato.", ["heat potato 1 with microwave 1", "go to microwave 1", "look"], "heat potato 1 with microwave 1"),
    ("Cool the apple.", ["cool apple 1 with fridge 1", "go to fridge 1", "look"], "cool apple 1 with fridge 1"),
    ("Place the cup on the table.", ["move cup 1 to countertop 1", "go to countertop 1", "inventory"], "move cup 1 to countertop 1"),
    ("Take the bowl from the counter.", ["take bowl 1 from countertop 2", "take fork 1 from countertop 2", "look"], "take bowl 1 from countertop 2"),
    ("Look around.", ["inventory", "look", "go to shelf 1"], "look"),
    ("Check the cabinet.", ["examine cabinet 2", "go to cabinet 2", "open cabinet 2"], "examine cabinet 2"),
    ("Open the fridge.", ["go to fridge 1", "open fridge 1", "inventory"], "open fridge 1"),
    ("Move to the safe.", ["go to safe 1", "go to sofa 1", "look"], "go to safe 1"),
    ("Pick up the vase exactly as listed.", ["take vase 1 from dresser 1", "take vase 2 from dresser 1"], "take vase 1 from dresser 1"),
    ("Examine the lamp.", ["examine lamp 1", "go to lamp 1", "inventory"], "examine lamp 1"),
    ("Put the object in the box.", ["move keychain 1 to box 1", "go to box 1", "look"], "move keychain 1 to box 1"),
]


def run_model(model: str) -> dict:
    os.environ["MODEL_PROVIDER"] = "ollama"
    os.environ["OLLAMA_MODEL"] = model
    client = bench.ModelClient("ollama")
    rows = []
    for index, (instruction, actions, expected) in enumerate(CASES, 1):
        prompt = f"{instruction}\n\nCurrent admissible actions:\n" + "\n".join(f"- {a}" for a in actions) + "\n\nChoose one action exactly."
        started = time.perf_counter()
        raw = client.complete(prompt)
        latency = time.perf_counter() - started
        parsed = bench.parse_action(raw, actions)
        rows.append({
            "case": index,
            "raw_output": raw,
            "format_success": "FINAL_ACTION:" in raw.upper(),
            "valid_action": parsed is not None,
            "semantic_accuracy": parsed == expected,
            "latency_seconds": latency,
            "output_tokens": client.last_usage.get("eval_count") or client.last_usage.get("completion_tokens"),
            "length_failure": client.last_usage.get("done_reason") in {"length", "max_tokens"},
        })
    n = len(rows)
    return {
        "model": model,
        "cases": rows,
        "format_success_rate": sum(r["format_success"] for r in rows) / n,
        "valid_action_rate": sum(r["valid_action"] for r in rows) / n,
        "semantic_accuracy": sum(r["semantic_accuracy"] for r in rows) / n,
        "average_latency": statistics.mean(r["latency_seconds"] for r in rows),
        "average_output_tokens": statistics.mean(r["output_tokens"] for r in rows if r["output_tokens"] is not None) if any(r["output_tokens"] is not None for r in rows) else 0,
        "length_failure_rate": sum(r["length_failure"] for r in rows) / n,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=Path("results/protocol_test.json"))
    args = parser.parse_args()
    reports = []
    for model in args.models:
        try:
            report = run_model(model)
        except Exception as exc:
            report = {"model": model, "error": repr(exc)}
        reports.append(report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
