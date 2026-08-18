import hashlib
import json
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

import numpy as np


MAX_STEPS = 50
OUTPUT_DIR = Path("results")
ENV_FILE = Path(__file__).with_name(".env")


SYSTEM_PROMPT = """You are an agent solving an ALFWorld task.

At each step you will receive:
- the task and initial observation
- previous actions and observations
- the current observation
- a numbered list of admissible actions

Choose the single best next action.

Return ONLY the integer index of the chosen action.
Do not explain your answer.
"""


def load_env_file(path=ENV_FILE):
    """Load a small, standard subset of dotenv syntax without a dependency."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def first_value(info, key, default=None):
    """Get first item from ALFWorld batch info."""
    value = info.get(key, default)
    if isinstance(value, (list, tuple, np.ndarray)):
        if len(value) == 0:
            return default
        return value[0]
    return value


def extract_task(initial_obs):
    marker = "Your task is to:"
    if marker in initial_obs:
        return initial_obs.split(marker, 1)[1].strip()
    return initial_obs.strip()


def infer_task_type(gamefile):
    if not gamefile:
        return "unknown"

    mapping = {
        "pick_and_place_simple": "pick_and_place",
        "look_at_obj_in_light": "examine_in_light",
        "pick_clean_then_place_in_recep": "clean_and_place",
        "pick_heat_then_place_in_recep": "heat_and_place",
        "pick_cool_then_place_in_recep": "cool_and_place",
        "pick_two_obj_and_place": "pick_two_and_place",
    }
    for key, value in mapping.items():
        if key in gamefile:
            return value
    return "unknown"


def build_prompt(task, current_observation, admissible_actions, trajectory):
    history_lines = []
    for item in trajectory:
        history_lines.append(
            f"Step {item['step']}:\n"
            f"Action: {item['action']}\n"
            f"Observation: {item['next_observation']}"
        )

    history = "\n\n".join(history_lines)
    actions_text = "\n".join(
        f"{i}. {action}" for i, action in enumerate(admissible_actions)
    )
    return f"""Task:
{task}

Previous interaction:
{history if history else "(none)"}

Current observation:
{current_observation}

Admissible actions:
{actions_text}

Return only the integer action index.
"""


def parse_action_index(text, num_actions):
    if not isinstance(text, str):
        return None

    text = text.strip()
    fenced = re.fullmatch(r"```(?:text)?\s*(\d+)\s*```", text, re.IGNORECASE)
    match = fenced or re.fullmatch(r"(\d+)", text)
    if not match:
        return None

    index = int(match.group(1))
    return index if 0 <= index < num_actions else None


def _join_api_path(base_url, endpoint):
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base + endpoint
    return base + "/v1" + endpoint


def _required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


class ModelClient:
    def __init__(self, provider=None):
        configured_provider = provider or os.environ.get("MODEL_PROVIDER", "auto")
        configured_provider = configured_provider.strip().lower()
        if configured_provider == "auto":
            both_configured = all(
                os.environ.get(name)
                for name in (
                    "OPENAI_API_KEY",
                    "OPENAI_BASE_URL",
                    "MODEL_ID",
                    "ANTHROPIC_API_KEY",
                    "ANTHROPIC_BASE_URL",
                    "ANTHROPIC_MODEL",
                )
            )
            configured_provider = (
                "openai" if os.environ.get("OPENAI_API_KEY") else "anthropic"
            )
            if both_configured:
                print(
                    "Both model providers are configured; defaulting to openai. "
                    "Set MODEL_PROVIDER=anthropic to use the Anthropic config.",
                    file=sys.stderr,
                )
        if configured_provider not in {"openai", "anthropic"}:
            raise ValueError("MODEL_PROVIDER must be openai, anthropic, or auto")

        self.provider = configured_provider
        self.timeout = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "120"))
        self.max_retries = int(os.environ.get("MODEL_MAX_RETRIES", "3"))
        if self.provider == "openai":
            self.api_key = _required_env("OPENAI_API_KEY")
            self.base_url = _required_env("OPENAI_BASE_URL")
            self.model = _required_env("MODEL_ID")
        else:
            self.api_key = _required_env("ANTHROPIC_API_KEY")
            self.base_url = _required_env("ANTHROPIC_BASE_URL")
            self.model = _required_env("ANTHROPIC_MODEL")

    def complete(self, prompt):
        if self.provider == "openai":
            url = _join_api_path(self.base_url, "/chat/completions")
            headers = {"Authorization": f"Bearer {self.api_key}"}
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 16,
            }
        else:
            url = _join_api_path(self.base_url, "/messages")
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
            payload = {
                "model": self.model,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 16,
            }

        response = self._post_json(url, headers, payload)
        try:
            if self.provider == "openai":
                content = response["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict)
                    )
            else:
                content = "".join(
                    block.get("text", "")
                    for block in response["content"]
                    if block.get("type") == "text"
                )
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise ModelAPIError(
                f"Malformed {self.provider} API response"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise ModelAPIError(f"Empty {self.provider} API response")
        return content

    def _post_json(self, url, extra_headers, payload):
        headers = {"Content-Type": "application/json", **extra_headers}
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(self.max_retries + 1):
            try:
                api_request = request.Request(url, data=body, headers=headers, method="POST")
                with request.urlopen(api_request, timeout=self.timeout) as response:
                    try:
                        return json.loads(response.read().decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ModelAPIError("Model API returned invalid JSON") from exc
            except error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")[:1000]
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == self.max_retries:
                    raise ModelAPIError(
                        f"Model API returned HTTP {exc.code}: {details}"
                    ) from exc
            except (error.URLError, TimeoutError) as exc:
                if attempt == self.max_retries:
                    raise ModelAPIError(f"Model API request failed: {exc}") from exc
            time.sleep(min(2**attempt, 8))


class ModelAPIError(RuntimeError):
    """A model request failed after retrying and the benchmark should stop."""


_MODEL_CLIENT = None


def call_model(prompt):
    """Return the configured model's raw text response."""
    global _MODEL_CLIENT
    if _MODEL_CLIENT is None:
        load_env_file()
        _MODEL_CLIENT = ModelClient()
    return _MODEL_CLIENT.complete(prompt)


def run_episode(env, episode_index, model_name, max_steps=MAX_STEPS):
    obs, info = env.reset()
    current_obs = obs[0]
    initial_obs = current_obs
    task = extract_task(initial_obs)
    gamefile = first_value(info, "extra.gamefile", default=None)
    task_id = gamefile or hashlib.sha1(initial_obs.encode("utf-8")).hexdigest()[:16]
    trajectory = []
    success = False
    termination = "max_steps"
    start_time = time.time()

    for step in range(1, max_steps + 1):
        admissible_actions = list(info["admissible_commands"][0])
        if not admissible_actions:
            termination = "no_admissible_actions"
            break

        prompt = build_prompt(task, current_obs, admissible_actions, trajectory)
        raw_output = call_model(prompt)
        action_index = parse_action_index(raw_output, len(admissible_actions))
        if action_index is None:
            trajectory.append({
                "step": step,
                "observation": current_obs,
                "admissible_actions": admissible_actions,
                "model_output": raw_output,
                "action": None,
                "action_index": None,
                "next_observation": None,
                "reward": 0,
                "done": False,
                "format_error": True,
            })
            termination = "invalid_model_output"
            break

        action = admissible_actions[action_index]
        next_obs, rewards, dones, next_info = env.step([action])
        # AlfredTWEnv returns rewards, while AlfredThorEnv returns None here.
        reward = None if rewards is None else float(rewards[0])
        done = bool(dones[0])
        won = bool(first_value(next_info, "won", False))
        trajectory.append({
            "step": step,
            "observation": current_obs,
            "admissible_actions": admissible_actions,
            "model_output": raw_output,
            "action_index": action_index,
            "action": action,
            "next_observation": next_obs[0],
            "reward": reward,
            "done": done,
            "won": won,
            "format_error": False,
        })
        current_obs = next_obs[0]
        info = next_info

        if won:
            success = True
            termination = "success"
            break
        if done:
            termination = "environment_done"
            break

    return {
        "episode_index": episode_index,
        "task_id": task_id,
        "gamefile": gamefile,
        "task_type": infer_task_type(gamefile),
        "task": task,
        "model": model_name,
        "success": success,
        "steps": len(trajectory),
        "termination": termination,
        "duration_seconds": time.time() - start_time,
        "trajectory": trajectory,
    }


def _safe_filename(value):
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return filename or "model"


def _evaluation_split(value):
    aliases = {
        "seen": "eval_in_distribution",
        "id": "eval_in_distribution",
        "eval_in_distribution": "eval_in_distribution",
        "unseen": "eval_out_of_distribution",
        "ood": "eval_out_of_distribution",
        "eval_out_of_distribution": "eval_out_of_distribution",
    }
    try:
        return aliases[value.strip().lower()]
    except KeyError as exc:
        raise ValueError(
            "ALFWORLD_SPLIT must be seen/id or unseen/ood"
        ) from exc


def _write_results(output_path, results):
    temporary_path = output_path.with_name(
        f".{output_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main():
    load_env_file()

    # Importing alfworld.info establishes its default ALFWORLD_DATA path when the
    # user did not explicitly configure one.
    import alfworld.info  # noqa: F401
    from alfworld.agents.environment import get_environment
    import alfworld.agents.modules.generic as generic

    config = generic.load_config()
    try:
        config["dataset"]["num_eval_games"] = int(
            config["dataset"]["num_eval_games"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("dataset.num_eval_games must be an integer") from exc

    seed = int(config["general"]["random_seed"])
    random.seed(seed)
    np.random.seed(seed)

    global _MODEL_CLIENT
    _MODEL_CLIENT = ModelClient()
    model_name = _MODEL_CLIENT.model
    print(f"Model: {model_name} ({_MODEL_CLIENT.provider})")

    env_type = os.environ.get("ALFWORLD_ENV_TYPE", config["env"]["type"])
    if env_type not in {"AlfredTWEnv", "AlfredThorEnv"}:
        raise ValueError(
            "ALFWORLD_ENV_TYPE must be AlfredTWEnv or AlfredThorEnv for this evaluator"
        )
    eval_split = _evaluation_split(os.environ.get("ALFWORLD_SPLIT", "unseen"))
    print("Environment:", env_type)
    print("Split:", eval_split)
    env_factory = get_environment(env_type)(
        config,
        train_eval=eval_split,
    )
    num_games = env_factory.num_games
    if num_games == 0:
        raise RuntimeError(
            "No ALFWorld evaluation games were found. Run alfworld-download "
            "and/or set ALFWORLD_DATA to the downloaded dataset directory."
        )

    output_dir = Path(os.environ.get("OUTPUT_DIR", OUTPUT_DIR))
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = os.environ.get("RUN_ID") or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + "_"
        + uuid.uuid4().hex[:8]
    )
    split_label = "seen" if eval_split == "eval_in_distribution" else "unseen"
    output_name = _safe_filename(
        f"{_MODEL_CLIENT.provider}_{model_name}_{env_type}_{split_label}_{run_id}"
    )
    output_path = output_dir / f"{output_name}.json"
    if output_path.exists():
        raise FileExistsError(
            f"Result file already exists: {output_path}. Choose a different RUN_ID."
        )
    max_steps = int(os.environ.get("MAX_STEPS", MAX_STEPS))
    results = []

    env = env_factory.init_env(batch_size=1)
    try:
        for episode_index in range(num_games):
            print(f"\n===== Episode {episode_index + 1}/{num_games} =====")
            try:
                result = run_episode(env, episode_index, model_name, max_steps)
            except KeyboardInterrupt:
                raise
            except ModelAPIError:
                # Bad credentials/network should not trigger the same failing
                # request once for every remaining benchmark episode.
                raise
            except Exception as exc:
                result = {
                    "episode_index": episode_index,
                    "model": model_name,
                    "success": False,
                    "termination": "exception",
                    "error": repr(exc),
                }

            results.append(result)
            print("Task:", result.get("task"))
            print("Success:", result.get("success"))
            print("Steps:", result.get("steps"))
            if result.get("error"):
                print("Error:", result["error"], file=sys.stderr)

            _write_results(output_path, results)
    finally:
        close = getattr(env, "close", None)
        if close:
            close()

    successes = sum(int(item.get("success", False)) for item in results)
    print("\n==============================")
    print("RESULT")
    print("==============================")
    print(f"Success: {successes}/{num_games}")
    print(f"Success rate: {successes / num_games:.2%}")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
