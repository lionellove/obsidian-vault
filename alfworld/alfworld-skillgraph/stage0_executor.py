"""Strict Executor action seam for Stage 0."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class ExecutorOutputError(ValueError):
    """The model output or admissible-action set is not safely executable."""

    def __init__(
        self,
        message: str,
        *,
        raw_response: str | None = None,
        request_record: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.request_record = dict(request_record or {})


class ExecutorRequestError(ExecutorOutputError):
    """The model request failed before a response could be parsed."""


def _unwrap_markdown(value: str) -> str:
    value = value.strip()
    wrappers = ("**", "__", "`", "*")
    changed = True
    while changed:
        changed = False
        for wrapper in wrappers:
            if len(value) >= 2 * len(wrapper) and value.startswith(wrapper) and value.endswith(wrapper):
                value = value[len(wrapper) : -len(wrapper)].strip()
                changed = True
                break
    return value


def _clean_protocol_line(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line for line in normalized.split("\n") if line.strip()]
    # Fences are presentation-only; all other non-empty lines must be absent.
    lines = [line for line in lines if not re.fullmatch(r"\s*```(?:[A-Za-z0-9_-]+)?\s*", line)]
    if len(lines) != 1:
        raise ExecutorOutputError("executor output must contain exactly one non-empty protocol line")
    return _unwrap_markdown(lines[0])


def _validate_admissible_actions(admissible_actions: Sequence[str]) -> list[str]:
    if not isinstance(admissible_actions, Sequence) or isinstance(admissible_actions, (str, bytes)):
        raise ExecutorOutputError("admissible actions must be a sequence")
    actions = list(admissible_actions)
    if not actions or any(not isinstance(action, str) or not action for action in actions):
        raise ExecutorOutputError("admissible actions must be non-empty strings")
    if len(set(actions)) != len(actions):
        raise ExecutorOutputError("admissible actions must be unique")
    return actions


def parse_executor_action(text: str, admissible_actions: Sequence[str]) -> str:
    """Parse exactly one ``FINAL_ACTION:`` and return the original listed string.

    Only code-fence lines, markdown emphasis around the complete line/action,
    and outer whitespace are presentation noise.  No case folding, synonym,
    index, substring, or bare-action matching is performed.
    """

    actions = _validate_admissible_actions(admissible_actions)
    if not isinstance(text, str):
        raise ExecutorOutputError("executor response must be text", raw_response=text)
    marker_count = len(re.findall(r"FINAL_ACTION\s*:", text))
    if marker_count != 1:
        raise ExecutorOutputError(
            "executor response must contain exactly one FINAL_ACTION marker",
            raw_response=text,
        )
    try:
        line = _clean_protocol_line(text)
    except ExecutorOutputError as exc:
        exc.raw_response = text
        raise
    if not line.startswith("FINAL_ACTION:"):
        raise ExecutorOutputError("protocol line must start with FINAL_ACTION:", raw_response=text)
    action_text = _unwrap_markdown(line[len("FINAL_ACTION:") :].strip())
    if not action_text:
        raise ExecutorOutputError("FINAL_ACTION must contain an action", raw_response=text)
    matches = [action for action in actions if action == action_text]
    if len(matches) != 1:
        raise ExecutorOutputError(
            "FINAL_ACTION must exactly equal one unique admissible action",
            raw_response=text,
        )
    return matches[0]


def build_executor_prompt(
    task_goal: str,
    observation: str,
    admissible_actions: Sequence[str],
    trajectory: Sequence[Mapping[str, Any]],
    skill_text: str,
) -> str:
    actions = _validate_admissible_actions(admissible_actions)
    if not isinstance(task_goal, str) or not isinstance(observation, str):
        raise ValueError("task_goal and observation must be strings")
    history: list[str] = []
    for item in trajectory:
        if not isinstance(item, Mapping):
            continue
        history.append(
            f"Step {item.get('step')}:\n"
            f"Action: {item.get('executed_action', item.get('action', ''))}\n"
            f"Observation: {item.get('next_observation', '')}"
        )
    return (
        "You are the frozen Stage 0 Executor.\n"
        "Return exactly one physical line: FINAL_ACTION: <one exact listed action>.\n"
        "Do not output analysis, an index, a synonym, or an invented action.\n\n"
        "Reusable skill package:\n"
        f"{skill_text}\n\n"
        f"Task goal:\n{task_goal}\n\n"
        f"Previous trajectory:\n{chr(10).join(history) if history else '(none)'}\n\n"
        f"Current observation:\n{observation}\n\n"
        "Currently admissible actions:\n"
        + "\n".join(f"- {action}" for action in actions)
        + "\n\nFINAL_ACTION:"
    )


@dataclass(frozen=True)
class ExecutorDecision:
    action: str
    raw_response: str
    prompt: str
    request_record: dict[str, Any]


class Executor:
    """One-step Executor using an injected DeepSeek-compatible client."""

    def __init__(self, *, client: Any, skill_text: str, skill_hash: str | None = None, token_budget: int = 128) -> None:
        if not isinstance(skill_text, str):
            raise ValueError("skill_text must be a string")
        if not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget <= 0:
            raise ValueError("token_budget must be a positive integer")
        self.client = client
        self.skill_text = skill_text
        self.skill_hash = skill_hash
        self.token_budget = token_budget

    def decide(
        self,
        task_goal: str,
        observation: str,
        admissible_actions: Sequence[str],
        trajectory: Sequence[Mapping[str, Any]],
    ) -> ExecutorDecision:
        prompt = build_executor_prompt(
            task_goal,
            observation,
            admissible_actions,
            trajectory,
            self.skill_text,
        )
        try:
            result = self.client.complete(
                role="executor",
                messages=[{"role": "user", "content": prompt}],
                token_budget=self.token_budget,
            )
        except Exception as exc:
            records = getattr(self.client, "request_records", [])
            record = records[-1] if isinstance(records, list) and records else {}
            raise ExecutorRequestError(
                f"executor request failed: {exc}",
                request_record=record,
            ) from exc
        raw_response = getattr(result, "content", None)
        request_record = getattr(result, "record", {})
        if not isinstance(raw_response, str):
            raise ExecutorOutputError(
                "client returned no text content",
                request_record=request_record,
            )
        try:
            action = parse_executor_action(raw_response, admissible_actions)
        except ExecutorOutputError as exc:
            exc.raw_response = raw_response
            exc.request_record = dict(request_record or {})
            raise
        return ExecutorDecision(
            action=action,
            raw_response=raw_response,
            prompt=prompt,
            request_record=dict(request_record or {}),
        )
