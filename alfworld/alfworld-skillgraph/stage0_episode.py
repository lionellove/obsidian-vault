"""Small environment/episode seam for offline and ALFWorld adapters."""
from __future__ import annotations

import hashlib
import time
from typing import Any, Mapping, Protocol, Sequence

from stage0_executor import ExecutorOutputError, ExecutorRequestError


class EpisodeEnvironment(Protocol):
    def reset(self) -> Any:
        ...

    def step(self, action: str) -> Any:
        ...


def _first(value: Any, default: Any = None) -> Any:
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value


def _unwrap_observation(value: Any) -> str:
    value = _first(value, "")
    return value if isinstance(value, str) else str(value)


def _unwrap_info(value: Any) -> Mapping[str, Any]:
    value = _first(value, {})
    return value if isinstance(value, Mapping) else {}


def _admissible(info: Mapping[str, Any]) -> list[str]:
    values = info.get("admissible_commands", info.get("admissible_actions", []))
    if isinstance(values, (list, tuple)) and len(values) == 1 and isinstance(values[0], (list, tuple)):
        values = values[0]
    if not isinstance(values, (list, tuple)):
        return []
    return [value for value in values if isinstance(value, str)]


def _flag(info: Mapping[str, Any], key: str) -> bool:
    value = info.get(key, False)
    value = _first(value, False)
    return bool(value)


def _goal(observation: str, info: Mapping[str, Any]) -> str:
    explicit = info.get("task_goal", info.get("goal"))
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    marker = "Your task is to:"
    if marker in observation:
        return observation.split(marker, 1)[1].strip()
    return observation.strip()


def _reward(value: Any) -> Any:
    value = _first(value, None)
    if value is None or isinstance(value, (int, float, bool, str)):
        return value
    return repr(value)


def _step_output(value: Any) -> tuple[Any, Any, bool, Mapping[str, Any]]:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise RuntimeError("environment step must return (observation, reward, done, info)")
    observation, reward, done, info = value
    return observation, reward, bool(_first(done, False)), _unwrap_info(info)


class EpisodeRunner:
    """Run one task with fail-closed action execution and auditable rows."""

    def __init__(self, env: EpisodeEnvironment, executor: Any, *, max_steps: int = 50) -> None:
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or not 1 <= max_steps <= 50:
            raise ValueError("max_steps must be an integer in [1, 50]")
        self.env = env
        self.executor = executor
        self.max_steps = max_steps

    def run(self, *, task_id: str | None = None) -> dict[str, Any]:
        reset_value = self.env.reset()
        if not isinstance(reset_value, (tuple, list)) or len(reset_value) != 2:
            raise RuntimeError("environment reset must return (observation, info)")
        observation = _unwrap_observation(reset_value[0])
        info = _unwrap_info(reset_value[1])
        task_goal = _goal(observation, info)
        resolved_task_id = task_id or _first(info.get("extra.gamefile"), None)
        if resolved_task_id is None:
            resolved_task_id = _first(info.get("gamefile"), None)
        skill_text = str(getattr(self.executor, "skill_text", ""))
        skill_hash = getattr(self.executor, "skill_hash", None)
        if not isinstance(skill_hash, str) or not skill_hash:
            skill_hash = hashlib.sha256(skill_text.encode("utf-8")).hexdigest()
        trajectory: list[dict[str, Any]] = []
        success = False
        termination = "max_steps"
        started = time.perf_counter()

        for step in range(1, self.max_steps + 1):
            admissible_actions = _admissible(info)
            if not admissible_actions:
                termination = "no_admissible_actions"
                break

            try:
                decision = self.executor.decide(
                    task_goal,
                    observation,
                    admissible_actions,
                    trajectory,
                )
            except ExecutorRequestError as exc:
                record = {
                    "step": step,
                    "observation": observation,
                    "admissible_actions": admissible_actions,
                    "raw_model_response": exc.raw_response,
                    "executed_action": None,
                    "reward": 0,
                    "done": False,
                    "won": False,
                    "skill_text": skill_text,
                    "skill_hash": skill_hash,
                    "request_record": exc.request_record,
                    "tokens": dict(exc.request_record.get("usage", {})) if isinstance(exc.request_record, Mapping) else {},
                    "error": str(exc),
                }
                trajectory.append(record)
                termination = "model_error"
                break
            except ExecutorOutputError as exc:
                record = {
                    "step": step,
                    "observation": observation,
                    "admissible_actions": admissible_actions,
                    "raw_model_response": exc.raw_response,
                    "executed_action": None,
                    "reward": 0,
                    "done": False,
                    "won": False,
                    "skill_text": skill_text,
                    "skill_hash": skill_hash,
                    "request_record": exc.request_record,
                    "tokens": dict(exc.request_record.get("usage", {})) if isinstance(exc.request_record, Mapping) else {},
                    "error": str(exc),
                }
                trajectory.append(record)
                termination = "invalid_model_output"
                break
            except Exception as exc:
                trajectory.append(
                    {
                        "step": step,
                        "observation": observation,
                        "admissible_actions": admissible_actions,
                        "raw_model_response": None,
                        "executed_action": None,
                        "reward": 0,
                        "done": False,
                        "won": False,
                        "skill_text": skill_text,
                        "skill_hash": skill_hash,
                        "request_record": {},
                        "tokens": {},
                        "error": repr(exc),
                    }
                )
                termination = "model_error"
                break

            if not isinstance(decision.action, str) or decision.action not in admissible_actions:
                trajectory.append(
                    {
                        "step": step,
                        "observation": observation,
                        "admissible_actions": admissible_actions,
                        "raw_model_response": decision.raw_response,
                        "executed_action": None,
                        "reward": 0,
                        "done": False,
                        "won": False,
                        "skill_text": skill_text,
                        "skill_hash": skill_hash,
                        "request_record": decision.request_record,
                        "tokens": dict(decision.request_record.get("usage", {})),
                        "error": "executor returned an action outside the admissible set",
                    }
                )
                termination = "invalid_model_output"
                break

            try:
                next_observation_raw, reward_raw, done, next_info = _step_output(
                    self.env.step(decision.action)
                )
            except Exception as exc:
                trajectory.append(
                    {
                        "step": step,
                        "observation": observation,
                        "admissible_actions": admissible_actions,
                        "raw_model_response": decision.raw_response,
                        "executed_action": decision.action,
                        "reward": 0,
                        "done": False,
                        "won": False,
                        "skill_text": skill_text,
                        "skill_hash": skill_hash,
                        "request_record": decision.request_record,
                        "tokens": dict(decision.request_record.get("usage", {})),
                        "error": repr(exc),
                    }
                )
                termination = "environment_error"
                break

            next_observation = _unwrap_observation(next_observation_raw)
            won = _flag(next_info, "won") or _flag(next_info, "success")
            row = {
                "step": step,
                "observation": observation,
                "admissible_actions": admissible_actions,
                "raw_model_response": decision.raw_response,
                "executed_action": decision.action,
                "reward": _reward(reward_raw),
                "done": done,
                "won": won,
                "next_observation": next_observation,
                "skill_text": skill_text,
                "skill_hash": skill_hash,
                "request_record": decision.request_record,
                "tokens": dict(decision.request_record.get("usage", {})),
            }
            trajectory.append(row)
            observation, info = next_observation, next_info
            if won:
                success = True
                termination = "success"
                break
            if done:
                termination = "environment_done"
                break

        return {
            "task_id": resolved_task_id,
            "task_goal": task_goal,
            "success": success,
            "termination": termination,
            "steps": len(trajectory),
            "duration_seconds": time.perf_counter() - started,
            "max_steps": self.max_steps,
            "skill_text": skill_text,
            "skill_hash": skill_hash,
            "request_records": [row.get("request_record", {}) for row in trajectory],
            "trajectory": trajectory,
        }
