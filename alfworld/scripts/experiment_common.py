"""Shared helpers for the ALFWorld skill-transfer experiment."""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows_from(path: str | Path) -> list[dict]:
    value = read_json(path)
    return value if isinstance(value, list) else [value]


def write_json(path: str | Path, value) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def find_result_files(directory: str | Path, pattern="*.json") -> list[Path]:
    return sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime)


def latest_teacher_result(results_dir: str | Path = ROOT / "results") -> Path:
    candidates = [p for p in find_result_files(results_dir) if "deepseek" in p.name.lower()]
    if not candidates:
        raise FileNotFoundError(f"No DeepSeek result JSON found under {results_dir}")
    return candidates[-1]


def result_summary(rows: list[dict]) -> dict:
    episodes = len(rows)
    successes = sum(bool(row.get("success")) for row in rows)
    steps = [row.get("steps") for row in rows if isinstance(row.get("steps"), (int, float))]
    format_failures = sum(
        1
        for row in rows
        for step in row.get("trajectory", [])
        if step.get("format_error")
    )
    invalid = sum(row.get("termination") == "invalid_model_output" for row in rows)
    length = sum(
        row.get("termination") in {"length_failure", "generation_length_failure"}
        or any(step.get("model_usage", {}).get("done_reason") == "length" for step in row.get("trajectory", []))
        for row in rows
    )
    times = [
        step.get("model_call_seconds")
        for row in rows
        for step in row.get("trajectory", [])
        if isinstance(step.get("model_call_seconds"), (int, float))
    ]
    tokens = [
        step.get("model_usage", {}).get("eval_count")
        for row in rows
        for step in row.get("trajectory", [])
        if isinstance(step.get("model_usage", {}).get("eval_count"), (int, float))
    ]
    return {
        "episodes": episodes,
        "successes": successes,
        "success_rate": successes / episodes if episodes else 0.0,
        "avg_steps": sum(steps) / len(steps) if steps else 0.0,
        "format_failures": format_failures,
        "format_failure_rate": invalid / episodes if episodes else 0.0,
        "length_failure_rate": length / episodes if episodes else 0.0,
        "avg_model_seconds_per_step": sum(times) / len(times) if times else 0.0,
        "avg_output_tokens_per_step": sum(tokens) / len(tokens) if tokens else 0.0,
        "termination_counts": dict(Counter(row.get("termination") for row in rows)),
    }


def task_key(task_id: str) -> str:
    value = str(task_id or "").replace("\\", "/").lower()
    return value.rstrip("/")


def align_by_task_id(*condition_rows: list[dict]) -> dict[str, list[dict | None]]:
    maps = [{task_key(row.get("task_id")): row for row in rows} for rows in condition_rows]
    keys = []
    for mapping in maps:
        for key in mapping:
            if key not in keys:
                keys.append(key)
    return {key: [mapping.get(key) for mapping in maps] for key in keys}


def infer_family(row: dict | None) -> str:
    return (row or {}).get("task_type") or "unknown"


def task_suffix(task_id: str) -> str:
    parts = re.split(r"[/\\]", str(task_id or ""))
    return "/".join(parts[-3:])
