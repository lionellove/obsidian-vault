"""Public calibration, paired, and Stage 0 go/no-go metrics."""

from __future__ import annotations

from stage0_metrics import evaluate_calibration_gate, evaluate_stage0_gate, summarize_episode_metrics


def test_calibration_gate_has_floor_middle_and_ceiling_outcomes():
    assert evaluate_calibration_gate(0, total=18)["status"] == "floor_stop"
    assert evaluate_calibration_gate(3, total=18)["status"] == "floor_stop"
    assert evaluate_calibration_gate(4, total=18)["status"] == "proceed"
    assert evaluate_calibration_gate(14, total=18)["status"] == "proceed"
    assert evaluate_calibration_gate(15, total=18)["status"] == "ceiling_stop"
    assert evaluate_calibration_gate(18, total=18)["status"] == "ceiling_stop"


def test_stage0_gate_requires_all_conditions_and_does_not_count_missing_rewrite_as_win():
    good = evaluate_stage0_gate(
        calibration_successes=8,
        calibration_total=18,
        root_cause={"root_cause_id": "rc"},
        structured_candidate={"status": "VALID", "structural_result": {"valid": True}},
        paired_summary={"NetGain": 2, "regressions": 1},
        s0_words=100,
        structured_words=140,
        structured_successes=8,
        rewrite_successes=8,
        rewrite_candidate_valid=True,
    )
    assert good["go"] is True
    missing_rewrite = evaluate_stage0_gate(
        calibration_successes=8,
        calibration_total=18,
        root_cause={"root_cause_id": "rc"},
        structured_candidate={"status": "VALID", "structural_result": {"valid": True}},
        paired_summary={"NetGain": 2, "regressions": 1},
        s0_words=100,
        structured_words=140,
        structured_successes=8,
        rewrite_successes=None,
        rewrite_candidate_valid=False,
    )
    assert missing_rewrite["go"] is False
    assert missing_rewrite["conditions"]["rewrite_comparison"] is False


def test_episode_summary_reports_steps_termination_invalid_and_tokens():
    summary = summarize_episode_metrics([
        {"success": True, "steps": 2, "termination": "won", "invalid_output": False, "request_records": [{"usage": {"prompt_tokens": 3, "output_tokens": 4}}]},
        {"success": False, "steps": 50, "termination": "max_steps", "invalid_output": True, "request_records": []},
    ])
    assert summary["episodes"] == 2
    assert summary["successes"] == 1
    assert summary["invalid_outputs"] == 1
    assert summary["max_step_terminations"] == 1
    assert summary["tokens"]["prompt_tokens"] == 3

