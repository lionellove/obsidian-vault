import json
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

try:
    import pytest  # type: ignore
except ImportError:
    pytest = None

from stage0_core import classify_task_family, sha256_file, task_group_key, task_id_key
from stage0_run import (
    balanced_validation_conditions,
    existing_task_keys,
    main,
    resolve_train_root,
    sample,
)


@contextmanager
def _raises(exc_type):
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def raises(exc_type):
    return pytest.raises(exc_type) if pytest is not None else _raises(exc_type)


def make_train(root: Path) -> Path:
    train = root / "json_2.1.1" / "train"
    prefixes = {
        "pick_and_place": "pick_and_place_simple-",
        "examine_in_light": "look_at_obj_in_light-",
        "clean_and_place": "pick_clean_then_place_in_recep-",
        "heat_and_place": "pick_heat_then_place_in_recep-",
        "cool_and_place": "pick_cool_then_place_in_recep-",
        "pick_two_and_place": "pick_two_obj_and_place-",
    }
    for family, prefix in prefixes.items():
        for index in range(9):
            task_dir = train / f"{prefix}Apple-None-Box-{index}"
            trial = task_dir / f"trial_T{family}_{index:02d}"
            trial.mkdir(parents=True)
            (trial / "game.tw-pddl").write_text("", encoding="utf-8")
    return train


def test_family_classification_and_correct_examine_prefix():
    assert classify_task_family("x/look_at_obj_in_light-Apple-None-Table-1/trial_T1/game.tw-pddl") == "examine_in_light"
    assert classify_task_family("x/pick_and_place_simple-Apple-None-Table-1/trial_T1/game.tw-pddl") == "pick_and_place"


def test_train_only_resolution_rejects_other_splits_and_valid_train():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        train = make_train(root)
        assert resolve_train_root(train) == train.resolve()
        assert resolve_train_root(train.parent) == train.resolve()
        for bad in (root / "json_2.1.1" / "valid_seen", root / "json_2.1.1" / "valid_unseen", root / "json_2.1.1" / "valid_train"):
            bad.mkdir(parents=True, exist_ok=True)
            with raises(ValueError):
                resolve_train_root(bad)


def test_recursive_denylist_is_exact_and_machine_stable():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "configs" / "nested").mkdir(parents=True)
        payload = {"outer": {"task_ids": [
            "/machine-a/json_2.1.1/train/pick_and_place_simple-Vase-None-Safe-1/trial_TX/game.tw-pddl",
            "not-a-task",
        ], "inner": [{"task_id": "C:\\machine\\json_2.1.1\\train\\look_at_obj_in_light-Apple-None-Table-2\\trial_TY\\game.tw-pddl"}]},
                   "gamefile": "/machine-a/json_2.1.1/train/pick_clean_then_place_in_recep-Mug-None-CoffeeMachine-3/trial_TZ/game.tw-pddl"}
        (repo / "configs" / "nested" / "x.json").write_text(json.dumps(payload), encoding="utf-8")
        (repo / "results" / "sanity" / "batches").mkdir(parents=True)
        (repo / "results" / "sanity" / "batches" / "c.json").write_text(json.dumps([
            "/machine-a/json_2.1.1/train/pick_heat_then_place_in_recep-Pan-None-CounterTop-4/trial_TW/game.tw-pddl",
            "noise",
        ]), encoding="utf-8")
        keys = existing_task_keys(repo)
        assert "pick_and_place_simple-vase-none-safe-1/trial_tx/game.tw-pddl" in keys
        assert "look_at_obj_in_light-apple-none-table-2/trial_ty/game.tw-pddl" in keys
        assert "pick_clean_then_place_in_recep-mug-none-coffeemachine-3/trial_tz/game.tw-pddl" in keys
        assert "pick_heat_then_place_in_recep-pan-none-countertop-4/trial_tw/game.tw-pddl" in keys
        assert "not-a-task" not in keys
        assert "noise" not in keys


def test_known_split_markers_share_the_same_relative_task_id():
    suffix = "pick_and_place_simple-Vase-None-Safe-1/trial_TX/game.tw-pddl"
    train_id = f"D:/machine-a/json_2.1.1/train/{suffix}"
    valid_train_id = f"/machine-b/json_2.1.1/valid_train/{suffix}"
    valid_seen_id = f"/machine-c/json_2.1.1/valid_seen/{suffix}"
    assert task_id_key(train_id) == task_id_key(valid_train_id)
    assert task_id_key(train_id) == task_id_key(valid_seen_id)


def test_same_template_trials_group_and_splits_are_disjoint():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        train = make_train(root)
        first = next(train.rglob("pick_and_place_simple-Apple-None-Box-0/trial_*/game.tw-pddl"))
        second = first.parent.parent / "trial_OTHER" / "game.tw-pddl"
        second.parent.mkdir()
        second.write_text("", encoding="utf-8")
        assert task_group_key(first) == task_group_key(second)
        assert "trial_" not in task_group_key(first)
        manifests = sample(train, set())
        all_ids = [task_id_key(value) for values in manifests.values() for value in values]
        assert len(all_ids) == len(set(all_ids)) == 54
        groups = [task_group_key(value) for values in manifests.values() for value in values]
        assert len(groups) == len(set(groups)) == 54
        for family in ("pick_and_place", "examine_in_light"):
            assert any(family in task_id for task_id in manifests["calibration"] + manifests["evolution"] + manifests["patch_validation"])


def test_balanced_validation_schedule_has_six_orders_three_times():
    tasks = [f"task_{index}" for index in range(18)]
    schedule = balanced_validation_conditions(tasks)
    counts = Counter(tuple(row["condition_order"]) for row in schedule)
    assert len(schedule) == 18
    assert set(counts.values()) == {3}
    assert len(counts) == 6


def test_dry_run_is_placeholder_and_non_dry_run_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        missing_data = root / "json_2.1.1"
        assert main(["--repo-root", str(root), "--data-root", str(missing_data), "--run-id", "dry", "--dry-run"]) == 0
        dry = json.loads((root / "results" / "skillgraph_stage0" / "dry" / "preregistration.json").read_text(encoding="utf-8"))
        assert dry["status"] == "scaffold_placeholder"
        assert dry["not_experiment_artifact"] is True
        assert dry["environment_seed"] == 20260825
        assert dry["rendered_hash_is_utf8_file_sha256"] is True
        dry_json = root / "results" / "skillgraph_stage0" / "dry" / "preregistration.json"
        dry_sidecar = root / "results" / "skillgraph_stage0" / "dry" / "preregistration.sha256"
        assert dry_sidecar.read_text(encoding="ascii").strip() == sha256_file(dry_json)
        assert "preregistration_hash" not in dry
        assert main(["--repo-root", str(root), "--data-root", str(missing_data), "--run-id", "live"]) == 2
        live = json.loads((root / "results" / "skillgraph_stage0" / "live" / "preregistration.json").read_text(encoding="utf-8"))
        assert live["status"] == "blocked_non_dry_run_unimplemented"
        assert "not implemented" in live["error"]
        live_json = root / "results" / "skillgraph_stage0" / "live" / "preregistration.json"
        live_sidecar = root / "results" / "skillgraph_stage0" / "live" / "preregistration.sha256"
        assert live_sidecar.read_text(encoding="ascii").strip() == sha256_file(live_json)
        assert "preregistration_hash" not in live
