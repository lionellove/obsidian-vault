import json
import tempfile
from pathlib import Path

from stage0_smoke import run_offline_smoke


def test_offline_smoke_produces_trajectory_json_without_network():
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "trajectory.json"
        payload = run_offline_smoke(output)
        assert payload["offline_smoke"] is True
        assert payload["episode"]["success"] is True
        assert payload["episode"]["termination"] == "success"
        assert output.is_file()
        saved = json.loads(output.read_text(encoding="utf-8"))
        assert saved["episode"]["trajectory"][0]["executed_action"] == "look"
        assert saved["episode"]["trajectory"][0]["request_record"]["request_id"] == "smoke-1"
