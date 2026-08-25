"""Artifact writer public behavior tests."""

from __future__ import annotations

from types import SimpleNamespace
import tempfile
from pathlib import Path

from stage0_artifacts import ArtifactWriter


def test_artifact_writer_emits_json_jsonl_and_sha256_sidecars():
    result = SimpleNamespace(
        failures=[{"failure_id": "f-1"}],
        preservations=[{"preservation_id": "p-1"}],
        root_cause={"root_cause_id": "rc-1"},
        structured_candidate=SimpleNamespace(to_dict=lambda: {"status": "NO_PATCH", "raw_response": "{}"}),
        rewrite_candidate=SimpleNamespace(to_dict=lambda: {"status": "NO_PATCH", "raw_response": "{}"}),
        structured_verifier=None,
        rewrite_verifier=None,
    )
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        paths = ArtifactWriter(tmp_path).write(result)
        assert (tmp_path / "ir" / "failures.jsonl").exists()
        assert (tmp_path / "ir" / "failures.jsonl.sha256").exists()
        assert (tmp_path / "candidates" / "structured_patch" / "candidate.json").exists()
        assert (tmp_path / "candidates" / "full_rewrite" / "candidate.json").exists()
        assert all(path.exists() for path in paths.values())
