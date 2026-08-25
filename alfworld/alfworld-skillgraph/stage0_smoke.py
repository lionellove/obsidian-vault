"""Offline end-to-end smoke CLI for the Stage 0 Executor seam."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from stage0_core import render_skill, sha256
from stage0_episode import EpisodeRunner
from stage0_executor import Executor
from stage0_llm import DeepSeekClient, TransportResponse
from stage0_run import baseline_skill


class _SmokeTransport:
    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> TransportResponse:
        return TransportResponse(
            status_code=200,
            headers={"X-Request-ID": "smoke-1"},
            body={
                "id": "smoke-response",
                "model": "deepseek-v4-flash-fake",
                "system_fingerprint": "offline",
                "choices": [{"message": {"content": "FINAL_ACTION: look"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 10,
                    "reasoning_tokens": 0,
                    "completion_tokens": 2,
                },
            },
        )


class _SmokeEnvironment:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def reset(self) -> tuple[str, dict[str, Any]]:
        return "Your task is to: inspect the room", {
            "admissible_commands": [["look"]],
            "extra.gamefile": ["pick_and_place_simple-Vase-None-Safe-1/trial_T/game.tw-pddl"],
        }

    def step(self, action: str) -> tuple[str, float, bool, dict[str, Any]]:
        self.executed.append(action)
        if action != "look":
            raise AssertionError("offline smoke received an unexpected action")
        return "The room is inspected.", 1.0, True, {"won": [True], "admissible_commands": [[]]}


def run_offline_smoke(output: str | Path | None = None) -> dict[str, Any]:
    skill = baseline_skill()
    skill_text = render_skill(skill)
    client = DeepSeekClient(transport=_SmokeTransport())
    executor = Executor(
        client=client,
        skill_text=skill_text,
        skill_hash=sha256(skill_text),
        token_budget=128,
    )
    env = _SmokeEnvironment()
    episode = EpisodeRunner(env, executor, max_steps=50).run(
        task_id="pick_and_place_simple-Vase-None-Safe-1/trial_T/game.tw-pddl"
    )
    payload = {
        "offline_smoke": True,
        "status": "scaffold_smoke",
        "network_called": False,
        "episode": episode,
    }
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an offline Stage 0 fake transport/environment smoke")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = run_offline_smoke(args.output)
    print(json.dumps({"status": payload["status"], "output": str(args.output) if args.output else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
