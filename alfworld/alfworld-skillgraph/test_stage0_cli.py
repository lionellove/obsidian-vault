"""CLI public behavior; offline smoke never needs an API key."""

from __future__ import annotations

import tempfile
from pathlib import Path

from stage0_cli import main


def test_offline_smoke_cli_writes_marked_artifact():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "offline"
        assert main(["offline-smoke", "--run-dir", str(output)]) == 0
        assert (output / "state.json").exists()
        assert (output / "report" / "stage0_report.md").exists()
        assert "offline" in (output / "state.json").read_text(encoding="utf-8")


def test_live_cli_requires_explicit_confirmation_and_credentials():
    with tempfile.TemporaryDirectory() as directory:
        code = main(["run", "--run-dir", str(Path(directory) / "missing")])
        assert code != 0

