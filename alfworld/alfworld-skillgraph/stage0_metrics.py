"""Stage 0 descriptive metrics and explicit stop/go gates."""

from __future__ import annotations

import copy
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from stage0_core import canonical, paired_outcomes, render_skill


PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
PRICING_MODEL = "deepseek-v4-flash"
PRICING_RATES_USD_PER_MILLION = {
    "cache_hit_tokens": 0.0028,
    "cache_miss_tokens": 0.14,
    "output_tokens": 0.28,
}


def pricing_metadata(*, captured_at: str | None = None, model: str = PRICING_MODEL) -> dict[str, Any]:
    stamp = captured_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "captured_at": stamp,
        "source": PRICING_SOURCE,
        "model": model,
        "rates_usd_per_million_tokens": dict(PRICING_RATES_USD_PER_MILLION),
        "basis": "estimated_base_rate_not_actual_invoice",
    }


def _usage_field(usage: dict[str, Any], field: str) -> Any:
    aliases = {
        "prompt_tokens": ("prompt_tokens", "input_tokens"),
        "cache_hit_tokens": ("cache_hit_tokens", "prompt_cache_hit_tokens", "cache_read_input_tokens"),
        "cache_miss_tokens": ("cache_miss_tokens", "prompt_cache_miss_tokens", "cache_creation_input_tokens"),
        "reasoning_tokens": ("reasoning_tokens",),
        "output_tokens": ("output_tokens", "completion_tokens"),
    }
    for key in aliases[field]:
        if key in usage:
            return usage[key]
    return None


def estimate_api_cost(
    records: Iterable[dict],
    *,
    captured_at: str | None = None,
    model: str = PRICING_MODEL,
) -> dict[str, Any]:
    """Estimate base-rate spend from real request usage, never invoice spend."""

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        marker = canonical(record)
        if marker not in seen:
            seen.add(marker)
            unique.append(copy.deepcopy(record))
    totals = {field: 0 for field in ("prompt_tokens", "cache_hit_tokens", "cache_miss_tokens", "reasoning_tokens", "output_tokens")}
    missing: list[str] = []
    for index, record in enumerate(unique):
        usage = record.get("usage")
        usage_map = usage if isinstance(usage, dict) else {}
        for field in totals:
            value = _usage_field(usage_map, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                if field in ("cache_hit_tokens", "cache_miss_tokens", "output_tokens"):
                    missing.append(f"{index}:{field}")
                continue
            totals[field] += value
    pricing = pricing_metadata(captured_at=captured_at, model=model)
    complete = bool(unique) and not missing
    cost = None
    if complete:
        cost = sum(
            totals[field] / 1_000_000 * PRICING_RATES_USD_PER_MILLION[field]
            for field in ("cache_hit_tokens", "cache_miss_tokens", "output_tokens")
        )
    return {
        "status": "complete" if complete else "incomplete",
        "estimated_api_cost_usd": cost,
        "basis": "estimated_base_rate_not_actual_invoice",
        "request_count": len(unique),
        "usage": totals,
        "missing_billing_usage": missing,
        "pricing": pricing,
    }


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def evaluate_calibration_gate(successes: int, *, total: int = 18) -> dict[str, Any]:
    if isinstance(successes, bool) or not isinstance(successes, int):
        raise ValueError("successes must be an integer")
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0 or successes < 0 or successes > total:
        raise ValueError("calibration counts are invalid")
    # Production is exactly 18 with the plan's 4-14 interval.  A reduced
    # testing plan preserves the same proportions while remaining executable.
    floor_max = 3 if total == 18 else math.floor(3 * total / 18)
    ceiling_min = 15 if total == 18 else math.ceil(15 * total / 18)
    status = "floor_stop" if successes <= floor_max else "ceiling_stop" if successes >= ceiling_min else "proceed"
    return {
        "status": status,
        "successes": successes,
        "total": total,
        "floor_max": floor_max,
        "ceiling_min": ceiling_min,
        "can_enter_evolution": status == "proceed",
        "s0_frozen": True,
    }


def evaluate_stage0_gate(
    *,
    calibration_successes: int,
    calibration_total: int,
    root_cause: Any,
    structured_candidate: Any,
    paired_summary: dict[str, Any],
    s0_words: int,
    structured_words: int,
    structured_successes: int,
    rewrite_successes: int | None,
    rewrite_candidate_valid: bool,
) -> dict[str, Any]:
    calibration = evaluate_calibration_gate(calibration_successes, total=calibration_total)
    root_ok = isinstance(root_cause, dict) and bool(root_cause.get("root_cause_id")) and root_cause.get("status") != "NO_ROOT_CAUSE"
    structural_ok = (
        _value(structured_candidate, "status") == "VALID"
        and bool((_value(structured_candidate, "structural_result") or {}).get("valid"))
    )
    net_gain = paired_summary.get("NetGain", paired_summary.get("net_gain")) if isinstance(paired_summary, dict) else None
    regressions = paired_summary.get("regressions") if isinstance(paired_summary, dict) else None
    net_gain_ok = isinstance(net_gain, (int, float)) and net_gain >= 2
    regressions_ok = isinstance(regressions, (int, float)) and regressions <= 1
    word_growth = None if not isinstance(s0_words, int) or s0_words <= 0 else (structured_words - s0_words) / s0_words
    word_growth_ok = word_growth is not None and word_growth <= 0.5
    rewrite_comparison = (
        rewrite_candidate_valid
        and isinstance(rewrite_successes, int)
        and isinstance(structured_successes, int)
        and structured_successes >= rewrite_successes - 1
    )
    conditions = {
        "calibration": calibration["status"] == "proceed",
        "root_cause": root_ok,
        "structured_structural": structural_ok,
        "net_gain": net_gain_ok,
        "regressions": regressions_ok,
        "word_growth": word_growth_ok,
        "rewrite_comparison": rewrite_comparison,
    }
    return {
        "go": all(conditions.values()),
        "conditions": conditions,
        "calibration": calibration,
        "NetGain": net_gain,
        "regressions": regressions,
        "word_growth": word_growth,
        "rewrite_candidate_valid": rewrite_candidate_valid,
        "rewrite_missing_is_not_a_win": not rewrite_candidate_valid,
    }


def _sum_usage(records: Iterable[dict]) -> dict[str, float]:
    totals = {key: 0 for key in ("prompt_tokens", "cache_hit_tokens", "cache_miss_tokens", "reasoning_tokens", "output_tokens")}
    latency = 0.0
    for record in records:
        if not isinstance(record, dict):
            continue
        usage = record.get("usage", {})
        if isinstance(usage, dict):
            for key in totals:
                value = usage.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[key] += value
        value = record.get("latency_seconds")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            latency += float(value)
    totals["latency_seconds"] = latency
    return totals


def summarize_episode_metrics(episodes: Iterable[dict]) -> dict[str, Any]:
    rows = [copy.deepcopy(row) for row in episodes]
    terminations = Counter(str(row.get("termination", "unknown")) for row in rows)
    steps = [row.get("steps") for row in rows if isinstance(row.get("steps"), int)]
    records: list[dict] = []
    for row in rows:
        values = row.get("request_records", [])
        if isinstance(values, list):
            records.extend(record for record in values if isinstance(record, dict))
    return {
        "episodes": len(rows),
        "successes": sum(bool(row.get("success")) for row in rows),
        "failures": sum(not bool(row.get("success")) for row in rows),
        "family_success_vector": {},
        "steps": {"count": len(steps), "min": min(steps) if steps else None, "max": max(steps) if steps else None, "mean": sum(steps) / len(steps) if steps else None},
        "terminations": dict(terminations),
        "invalid_outputs": sum(bool(row.get("invalid_output")) for row in rows),
        "max_step_terminations": sum(row.get("termination") == "max_steps" for row in rows),
        "loop_behaviors": sum(bool(row.get("loop_detected")) for row in rows),
        "tokens": _sum_usage(records),
    }


def family_success_vector(episodes: Iterable[dict]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(lambda: {"successes": 0, "episodes": 0})
    for row in episodes:
        family = str(row.get("family", "unknown"))
        result[family]["episodes"] += 1
        result[family]["successes"] += int(bool(row.get("success")))
    return dict(result)


def paired_rows(baseline: list[dict], candidate: list[dict]) -> list[dict]:
    return paired_outcomes(baseline, candidate)


def skill_render_metrics(skill: dict) -> dict[str, Any]:
    package = skill["skill_package"]
    rendered = render_skill(skill)
    words = len(rendered.split())
    return {
        "words": words,
        "characters": len(rendered),
        "components": {key: len(package.get(key, [])) for key in ("nodes", "edges", "constraints", "verifications", "fallbacks")},
    }


__all__ = [
    "PRICING_MODEL",
    "PRICING_RATES_USD_PER_MILLION",
    "PRICING_SOURCE",
    "estimate_api_cost",
    "evaluate_calibration_gate",
    "evaluate_stage0_gate",
    "family_success_vector",
    "paired_rows",
    "skill_render_metrics",
    "pricing_metadata",
    "summarize_episode_metrics",
]
