import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE = Path(__file__).resolve().parents[1] / "family_skillgraph.py"
SPEC = importlib.util.spec_from_file_location("family_skillgraph", MODULE)
family = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = family
SPEC.loader.exec_module(family)


def test_family_manifest_selects_and_freezes_the_25_hr_tasks():
    manifest = family.build_family_manifest()

    assert manifest["family_id"] == "hr-policy-governed-spreadsheet-batch-v1"
    assert manifest["counts"] == {"train": 12, "validation": 5, "test": 8, "total": 25}
    assert manifest["split_rule"] == {
        "algorithm": "sha256-lexicographic",
        "salt": "skillgraph-family-v1:",
        "sizes": {"train": 12, "validation": 5, "test": 8},
    }
    assert manifest["splits"]["train"][0]["task_id"] == "hr.referral_bonus_processing"
    assert (
        manifest["splits"]["validation"][0]["task_id"]
        == "hr.visa_expiration_monitoring"
    )
    assert manifest["splits"]["test"][0]["task_id"] == "hr.data_migration_validation"
    assert all(
        "assertions" not in json.dumps(task)
        for split in manifest["splits"].values()
        for task in split
    )


def test_task_card_keeps_structure_but_removes_instance_values_and_assertions():
    task = {
        "task_id": "hr.example",
        "task_request": "Process the tracker.",
        "available_tools": ["gmail_send_email"],
        "initial_state": {
            "google_sheets": {
                "spreadsheets": [
                    {
                        "id": "SECRET-SHEET-ID",
                        "worksheets": [
                            {
                                "rows": [
                                    {
                                        "cells": {
                                            "Employee": "SECRET-NAME",
                                            "Amount": 12345,
                                        }
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        },
        "assertions": [{"type": "SECRET-ASSERTION", "value": "SECRET-EXPECTED"}],
    }

    card = family.build_task_card(task)
    serialized = json.dumps(card, sort_keys=True)

    assert card["task_id"] == "hr.example"
    assert card["task_request"] == "Process the tracker."
    assert "gmail_send_email" in serialized
    assert "spreadsheets" in serialized
    assert "worksheets" in serialized
    assert "Employee" in serialized
    assert "Amount" in serialized
    assert "SECRET" not in serialized
    assert "12345" not in serialized
    assert "assertions" not in serialized


def test_graph_runtime_only_takes_legal_outcomes_and_tracks_blackboard():
    graph = family.minimal_graph()
    runtime = family.GraphRuntime(graph)
    runtime.register_tool_calls(["call-1"])

    assert runtime.current_node()["id"] == "inspect"
    inspect_outputs = {
        "records": ["r1"],
        "policy": "observed",
        "supported operations": ["update"],
    }
    result = runtime.complete("inspected", inspect_outputs, ["call-1"])
    assert result["current_node"]["id"] == "act"
    assert result["blackboard"] == inspect_outputs
    assert result["visited_nodes"] == ["inspect", "act"]

    with pytest.raises(ValueError, match="illegal outcome"):
        runtime.complete("made_up", {}, [])


def test_graph_runtime_enforces_bounded_retry():
    graph = family.minimal_graph()
    graph["edges"] = [
        {"source": "inspect", "target": "act", "outcome": "inspected"},
        {"source": "act", "target": "verify", "outcome": "acted"},
        {"source": "verify", "target": "finish", "outcome": "verified"},
        {
            "source": "verify",
            "target": "act",
            "outcome": "retry",
            "retry_id": "repair",
            "max": 1,
        },
    ]
    runtime = family.GraphRuntime(graph)
    runtime.register_tool_calls(["call-1", "call-2", "call-3", "call-4"])
    runtime.complete(
        "inspected",
        {"records": [], "policy": "observed", "supported operations": []},
        ["call-1"],
    )
    act_outputs = {"mutation receipts": [], "notification receipts": []}
    runtime.complete("acted", act_outputs, ["call-2"])
    runtime.complete("retry", {"verification result": "repair needed"}, ["call-3"])
    runtime.complete("acted", act_outputs, ["call-4"])

    with pytest.raises(ValueError, match="retry limit"):
        runtime.complete("retry", {}, [])


def test_atomic_edit_never_mutates_the_accepted_graph_and_records_lineage():
    current = family.minimal_graph()
    candidate, record = family.apply_atomic_edit(
        current,
        {
            "operator": "UPDATE_NODE",
            "target": "act",
            "patch": {"instruction": "Perform only policy-authorized updates."},
        },
    )

    assert current["version"] == 0
    assert current["nodes"][1]["instruction"] != candidate["nodes"][1]["instruction"]
    assert candidate["version"] == 1
    assert record["operator"] == "UPDATE_NODE"
    assert record["lineage"] == {"act": ["act"]}

    with pytest.raises(ValueError, match="entry node"):
        family.apply_atomic_edit(
            current,
            {"operator": "DELETE_NODE", "target": "inspect"},
        )
    assert current == family.minimal_graph()


def test_optimizer_view_exposes_scalar_trace_and_mutation_diff_but_no_assertions():
    initial = {"google_sheets": {"rows": [{"id": "r1", "status": "Pending"}]}}
    evaluation = {
        "name": "hr.example",
        "score": 0.5,
        "messages": [{"role": "assistant", "content": "worked"}],
        "end_state": {"google_sheets": {"rows": [{"id": "r1", "status": "Approved"}]}},
        "assertions_total": 2,
        "assertion_results": [{"type": "SECRET", "params": {"value": "EXPECTED"}}],
        "skillgraph_trace": {"visited_nodes": ["inspect", "act"]},
    }

    view = family.build_optimizer_view(evaluation, initial_state=initial)
    serialized = json.dumps(view)

    assert view["task_id"] == "hr.example"
    assert view["score"] == 0.5
    assert view["trajectory"] == evaluation["messages"]
    assert view["mutation_diff"][0]["path"].endswith("status")
    assert "Approved" in serialized
    assert "assert" not in serialized.lower()
    assert "EXPECTED" not in serialized


def test_validation_gate_uses_the_fixed_composite_rule():
    current = {f"task-{i}": [0.50, 0.50, 0.50] for i in range(5)}
    candidate = {
        "task-0": [0.60, 0.60, 0.60],
        "task-1": [0.60, 0.60, 0.60],
        "task-2": [0.60, 0.60, 0.60],
        "task-3": [0.50, 0.50, 0.50],
        "task-4": [0.45, 0.45, 0.45],
    }

    accepted = family.validation_gate(current, candidate, artifact_valid=True)
    assert accepted["decision"] == "ACCEPT"
    assert accepted["mean_delta"] == pytest.approx(0.05)

    candidate["task-4"] = [0.30, 0.30, 0.30]
    rejected = family.validation_gate(current, candidate, artifact_valid=True)
    assert rejected["decision"] == "REJECT"
    assert "large_task_regression" in rejected["reasons"]


def test_sealed_test_cannot_open_before_freeze_or_open_twice(tmp_path):
    state_path = tmp_path / "experiment-state.json"
    state = family.ExperimentState.create(state_path)

    with pytest.raises(RuntimeError, match="artifacts are frozen"):
        state.open_test()

    state.freeze_artifacts({"incremental-graph": "sha256:abc"})
    state.open_test()
    with pytest.raises(RuntimeError, match="already opened"):
        state.open_test()


def test_primary_report_aggregates_by_task_before_bootstrapping():
    graph = {f"task-{i}": [0.8, 0.9, 1.0, 0.9, 0.8] for i in range(8)}
    markdown = {f"task-{i}": [0.4, 0.5, 0.6, 0.5, 0.4] for i in range(8)}

    report = family.primary_comparison(graph, markdown, samples=2000, seed=7)

    assert report["tasks"] == 8
    assert report["mean_delta"] == pytest.approx(0.4)
    assert report["ci95"][0] > 0
    assert report["conclusion"] == "incremental_graph_wins"


@pytest.mark.parametrize(
    ("edit", "expected_node"),
    [
        (
            {
                "operator": "INSERT_NODE",
                "target": "act",
                "node": {
                    "id": "receipt",
                    "type": "verification",
                    "instruction": "Check receipts.",
                },
            },
            "receipt",
        ),
        (
            {
                "operator": "SPLIT_NODE",
                "target": "act",
                "nodes": [
                    {"id": "decide", "type": "action", "instruction": "Decide."},
                    {"id": "mutate", "type": "action", "instruction": "Mutate."},
                ],
            },
            "mutate",
        ),
        (
            {
                "operator": "INTRODUCE_BRANCH",
                "target": "act",
                "branches": [
                    {
                        "outcome": "update",
                        "node": {
                            "id": "update",
                            "type": "action",
                            "instruction": "Update.",
                        },
                    },
                    {
                        "outcome": "notify",
                        "node": {
                            "id": "notify",
                            "type": "action",
                            "instruction": "Notify.",
                        },
                    },
                ],
            },
            "notify",
        ),
        (
            {
                "operator": "ADD_FALLBACK",
                "target": "act",
                "outcome": "unsupported",
                "node": {
                    "id": "fallback",
                    "type": "recover",
                    "instruction": "Report blocker.",
                },
                "join": "verify",
            },
            "fallback",
        ),
    ],
)
def test_structural_atomic_edits_keep_the_graph_valid(edit, expected_node):
    candidate, _ = family.apply_atomic_edit(family.minimal_graph(), edit)

    assert family.validate_graph(candidate)
    assert expected_node in {node["id"] for node in candidate["nodes"]}


def test_arbitrary_unbounded_cycles_are_rejected():
    graph = family.minimal_graph()
    graph["edges"].append({"source": "verify", "target": "act", "outcome": "again"})

    with pytest.raises(ValueError, match="unbounded cycle"):
        family.validate_graph(graph)


def test_runtime_snapshot_tracks_remaining_student_steps():
    runtime = family.GraphRuntime(family.minimal_graph(), max_steps=20)
    runtime.set_remaining_steps(13)

    assert runtime.snapshot()["remaining_steps"] == 13


def test_graph_runtime_requires_contract_outputs_and_reaches_a_terminal_state():
    runtime = family.GraphRuntime(family.minimal_graph())
    runtime.register_tool_calls(["call-1", "call-2", "call-3"])
    with pytest.raises(ValueError, match="node outputs are missing"):
        runtime.complete("inspected", {"records": []}, ["call-1"])

    runtime.complete(
        "inspected",
        {"records": [], "policy": "observed", "supported operations": []},
        ["call-1"],
    )
    runtime.complete(
        "acted",
        {"mutation receipts": [], "notification receipts": []},
        ["call-2"],
    )
    terminal = runtime.complete(
        "verified", {"verification result": "passed"}, ["call-3"]
    )

    assert terminal["terminal_status"] == "finish"
    with pytest.raises(ValueError, match="already terminal"):
        runtime.blocked("too late")


class _EditAuthor:
    def generate(self, prompt):
        if "Analyze the supplied" in prompt:
            return json.dumps({"decision": "EDIT", "diagnosis": "missing policy guard"})
        if "SkillGraph edit" in prompt:
            return json.dumps(
                {
                    "operator": "UPDATE_NODE",
                    "target": "act",
                    "patch": {
                        "instruction": "Perform better policy-authorized actions."
                    },
                }
            )
        raise AssertionError(prompt[:120])


class _ScoringEvaluator:
    def evaluate(self, task_ids, artifact, *, graph, repetitions, label):
        if graph and artifact:
            serialized = json.dumps(artifact)
            score = 0.6 if "better policy-authorized" in serialized else 0.5
        else:
            score = 0.5
        return {
            task_id: [
                {
                    "name": task_id,
                    "score": score,
                    "passed": score == 1.0,
                    "messages": [],
                    "end_state": {},
                }
                for _ in range(repetitions)
            ]
            for task_id in task_ids
        }


def test_incremental_optimizer_accepts_once_then_rejects_non_improving_edits(tmp_path):
    graph, history, views = family.optimize_artifact(
        kind="graph",
        initial=family.minimal_graph(),
        manifest=family.build_family_manifest(),
        author=_EditAuthor(),
        evaluator=_ScoringEvaluator(),
        records_dir=tmp_path,
    )

    assert graph["version"] == 1
    assert history[0]["gate"]["decision"] == "ACCEPT"
    assert all(item["gate"]["decision"] == "REJECT" for item in history[1:])
    assert len(views) == 36
    assert len(list(tmp_path.glob("graph-round-*.json"))) == 5


class _BaselineAuthor:
    def generate(self, prompt):
        assert "Do not infer assertions" in prompt
        return "# Task skill\n\nInspect, act, and verify."


def test_sealed_test_randomizes_all_arms_and_runs_five_resets(tmp_path):
    paths = family.FamilyPaths(tmp_path)
    family.write_family_manifest(paths.manifest)
    state = family.ExperimentState.create(paths.state)
    experiment = family.FamilyExperiment(paths, _BaselineAuthor(), _ScoringEvaluator())
    family_artifacts = {
        "family-static-markdown": family.MINIMAL_MARKDOWN,
        "family-incremental-markdown": family.MINIMAL_MARKDOWN,
        "one-shot-family-skillgraph": family.minimal_graph(),
        "batch-refine-skillgraph": family.minimal_graph(),
        "incremental-skillgraph": family.minimal_graph(),
    }
    for name, artifact in family_artifacts.items():
        experiment._write_artifact(name, artifact)
    experiment._bind_or_verify_configuration(state)
    state.freeze_artifacts(experiment._family_artifacts())

    results = experiment.run_sealed_test()

    assert set(results) == set(family.ARMS)
    assert all(
        len(observations) == 5
        for tasks in results.values()
        for observations in tasks.values()
    )
    assert family.ExperimentState.load(paths.state).payload["phase"] == "complete"
    with pytest.raises(RuntimeError, match="already opened"):
        experiment.run_sealed_test()


def test_live_evaluator_retries_error_results_and_preserves_each_attempt(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    calls = 0

    def fake_run(command, cwd):
        nonlocal calls
        calls += 1
        output = Path(command[command.index("--export-json") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        task = {
            "name": "hr.example",
            "score": 0.0 if calls == 1 else 1.0,
            "passed": calls != 1,
            "messages": [],
            "end_state": {},
        }
        if calls == 1:
            task["errors"] = ["transient runner error"]
        output.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(family.subprocess, "run", fake_run)
    evaluator = family.AutomationBenchEvaluator(tmp_path, student_model="fixed-student")

    result = evaluator.evaluate(
        ["hr.example"], None, graph=False, repetitions=1, label="retry-test"
    )

    assert calls == 2
    assert result["hr.example"][0]["score"] == 1.0
    attempts = sorted((tmp_path / "attempts").glob("*.json"))
    assert len(attempts) == 2
    assert "transient runner error" in attempts[0].read_text(encoding="utf-8")


def test_incomplete_sealed_test_suppresses_the_primary_claim(tmp_path):
    class MissingEvaluator(_ScoringEvaluator):
        def evaluate(self, task_ids, artifact, *, graph, repetitions, label):
            return {task_id: [] for task_id in task_ids}

    paths = family.FamilyPaths(tmp_path)
    family.write_family_manifest(paths.manifest)
    state = family.ExperimentState.create(paths.state)
    experiment = family.FamilyExperiment(paths, _BaselineAuthor(), MissingEvaluator())
    for name, artifact in {
        "family-static-markdown": family.MINIMAL_MARKDOWN,
        "family-incremental-markdown": family.MINIMAL_MARKDOWN,
        "one-shot-family-skillgraph": family.minimal_graph(),
        "batch-refine-skillgraph": family.minimal_graph(),
        "incremental-skillgraph": family.minimal_graph(),
    }.items():
        experiment._write_artifact(name, artifact)
    experiment._bind_or_verify_configuration(state)
    state.freeze_artifacts(experiment._family_artifacts())

    experiment.run_sealed_test()
    report = experiment.build_report()

    assert (
        family.ExperimentState.load(paths.state).payload["phase"] == "test_incomplete"
    )
    assert report["primary"]["conclusion"] == "missing_observations_no_claim"
    assert report["secondary_exploratory"] == {}
