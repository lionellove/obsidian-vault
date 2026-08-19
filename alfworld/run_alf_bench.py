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


ALFWORLD_SOURCE = Path(__file__).with_name("alfworld")
if str(ALFWORLD_SOURCE) not in sys.path:
    sys.path.insert(0, str(ALFWORLD_SOURCE))


MAX_STEPS = 50
OUTPUT_DIR = Path("results")
ENV_FILE = Path(__file__).with_name(".env")


SYSTEM_PROMPT = """You are an agent acting in an interactive household environment.

Your goal is to complete the given task by interacting with the environment one action at a time.

At each step, you will receive:
- the task goal,
- previous actions and observations,
- the current observation,
- a list of currently admissible actions.

Decision procedure:
1. Identify the final task goal.
2. Identify the immediate subgoal that should be achieved next.
3. Recall relevant facts already established by previous observations and actions.
4. Determine what information or state change is still required.
5. Consider only the currently admissible actions.
6. Select the action that most directly advances the immediate subgoal, or obtains necessary information when the correct next action cannot yet be determined.
7. Commit to one action.

Environment rules:
- The environment is sequential and partially observable.
- The currently admissible actions are the only actions that may be executed at this step.
- The admissible-action set may change after navigation or interaction.
- An action unavailable now may become available after the environment state changes.
- Do not invent actions that are not currently admissible.
- Do not conclude that the task is impossible merely because a future action is currently unavailable.
- Do not speculate about hidden environment implementation details, benchmark mechanics, or dataset behavior.
- Do not repeatedly reconsider the same alternatives without new evidence.
- Do not repeatedly visit or inspect locations already shown to be irrelevant unless the environment state has changed.
- Do not assume an object's location or state without observational evidence.

Exploration:
- When the location of a required object is unknown, search systematically.
- Remember which locations have already been inspected and what was observed there.
- Prefer unexplored plausible locations over revisiting locations already shown not to contain the required object.
- Do not rely only on household stereotypes; treat environment observations as authoritative.

Object manipulation:
- Reason in terms of prerequisites and state transitions.
- A task may require locating, acquiring, preparing, transporting, and placing objects.
- Do not assume every task requires every operation.
- If the task explicitly requires an object to be clean, heated, cooled, or otherwise transformed, do not assume the requirement is satisfied merely because the object appears normal or empty.
- Ensure the required state change has actually occurred before final placement.

Action selection:
- Choose exactly ONE action from the current admissible-action list.
- Copy the selected action EXACTLY as it appears in that list.
- Do not translate, paraphrase, shorten, renumber, or invent an action.
    - Do not output an action index.
    - You may provide a short analysis before the final action.

Final-action validation:
- The final action must be copied character-for-character from the current admissible-action list.
- Never create a plausible action that is absent from that list.
- If your preferred action is absent, choose a useful action that is present.

At the end of the response, output exactly one line in this format:

FINAL_ACTION: <exact admissible action>

Do not use Markdown formatting around the final action.
Do not write anything after the FINAL_ACTION line.
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


def _load_skill():
    skill_file = os.environ.get("SKILL_FILE", "").strip()
    if not skill_file:
        return ""
    path = Path(skill_file)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    if not path.exists():
        raise FileNotFoundError(f"SKILL_FILE does not exist: {path}")
    return path.read_text(encoding="utf-8").strip()


def build_prompt(task, current_observation, admissible_actions, trajectory,
                 skill=""):
    history_lines = []
    for item in trajectory:
        if not item.get("action"):
            continue
        history_lines.append(
            f"Step {item['step']}:\n"
            f"Action: {item['action']}\n"
            f"Observation: {item['next_observation']}"
        )

    history = "\n\n".join(history_lines)

    # Do not number actions: small models can choose the right semantic action
    # but map it to the wrong integer index.
    actions_text = "\n".join(f"- {action}" for action in admissible_actions)

    skill_section = ""
    if skill.strip():
        skill_section = f"""Reusable procedural guidance:

{skill.strip()}

Use this guidance when relevant. Do not treat it as task-specific ground truth.
Current observations and admissible actions remain authoritative.

"""

    return f"""{skill_section}Task:
{task}

Previous interaction:
{history if history else "(none)"}

Current observation:
{current_observation}

Currently admissible actions:
{actions_text}

Choose exactly one action from the list above and copy it exactly.
Validity check: the text after FINAL_ACTION: must equal one complete line from
the admissible-action list above. Do not output an action number or an action
that is not listed.
End your response with:
FINAL_ACTION: <exact admissible action>
"""


def build_repair_prompt(task, current_observation, admissible_actions):
    actions_text = "\n".join(f"- {action}" for action in admissible_actions)
    return f"""Your previous response did not contain a valid current action.
Return only one final line, copied character-for-character from this list.
Never output an action number and never invent an action.

Task: {task}
Current observation: {current_observation}
Currently admissible actions:
{actions_text}

FINAL_ACTION: <copy exactly one listed action>"""


def parse_action(text, admissible_actions):
    """Return an exact currently-admissible action string, or None."""
    if not isinstance(text, str):
        return None

    match = re.search(
        r"FINAL_ACTION:\s*(.+?)\s*$",
        text.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None

    action = match.group(1).strip()

    # Tolerate accidental Markdown wrappers, but still require exact
    # membership in the current action set.
    if len(action) >= 4 and action.startswith("**") and action.endswith("**"):
        action = action[2:-2].strip()
    if len(action) >= 2 and action.startswith("`") and action.endswith("`"):
        action = action[1:-1].strip()

    return action if action in admissible_actions else None


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
        configured_provider = (
            provider or os.environ.get("MODEL_PROVIDER", "auto")
        ).strip().lower()

        if configured_provider == "auto":
            if os.environ.get("OLLAMA_MODEL"):
                configured_provider = "ollama"
            elif os.environ.get("OPENAI_API_KEY"):
                configured_provider = "openai"
            else:
                raise ValueError(
                    "Could not infer provider. Set MODEL_PROVIDER=openai "
                    "or MODEL_PROVIDER=ollama."
                )

        if configured_provider not in {"openai", "ollama"}:
            raise ValueError("MODEL_PROVIDER must be openai, ollama, or auto")

        self.provider = configured_provider
        self.timeout = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "120"))
        self.max_retries = int(os.environ.get("MODEL_MAX_RETRIES", "3"))
        self.last_thinking = ""
        self.last_usage = {}

        if self.provider == "openai":
            self.api_key = _required_env("OPENAI_API_KEY")
            self.base_url = _required_env("OPENAI_BASE_URL")
            self.model = _required_env("MODEL_ID")
        else:
            self.api_key = None
            self.base_url = os.environ.get(
                "OLLAMA_BASE_URL", "http://localhost:11434"
            ).rstrip("/")
            self.model = os.environ.get(
                "OLLAMA_MODEL", "ministral-3:3b"
            ).strip()
            if not self.model:
                raise ValueError("OLLAMA_MODEL must not be empty")

            self.ollama_keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
            self.ollama_num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))
            self.ollama_num_predict = int(
                os.environ.get("OLLAMA_NUM_PREDICT", "512")
            )
            self.ollama_temperature = float(
                os.environ.get("OLLAMA_TEMPERATURE", "0")
            )
            self.ollama_think = os.environ.get("OLLAMA_THINK", "false").lower() in {
                "1", "true", "yes", "on"
            }

    def complete(self, prompt, system_prompt=None):
        self.last_thinking = ""
        self.last_usage = {}

        if self.provider == "openai":
            return self._complete_openai(prompt, system_prompt or SYSTEM_PROMPT)
        return self._complete_ollama(prompt, system_prompt or SYSTEM_PROMPT)

    def _complete_openai(self, prompt, system_prompt):
        url = _join_api_path(self.base_url, "/chat/completions")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        response = self._post_json(url, headers, payload)

        try:
            message = response["choices"][0]["message"]
            content = message["content"]

            if isinstance(content, list):
                content = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                )

            usage = response.get("usage", {})
            if isinstance(usage, dict):
                self.last_usage = {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                }

        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise ModelAPIError(
                "Malformed OpenAI-compatible API response"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise ModelAPIError("Empty OpenAI-compatible API response")

        return content.strip()

    def _complete_ollama(self, prompt, system_prompt):
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "keep_alive": self.ollama_keep_alive,
            "options": {
                "num_ctx": self.ollama_num_ctx,
                "num_predict": self.ollama_num_predict,
                "temperature": self.ollama_temperature,
            },
            "think": self.ollama_think,
        }

        response = self._post_json(url, {}, payload)

        try:
            message = response["message"]
            content = message.get("content", "")
            thinking = message.get("thinking", "")
            self.last_thinking = thinking if isinstance(thinking, str) else ""

            self.last_usage = {
                "done": response.get("done"),
                "done_reason": response.get("done_reason"),
                "prompt_eval_count": response.get("prompt_eval_count"),
                "eval_count": response.get("eval_count"),
                "prompt_eval_duration_ns": response.get("prompt_eval_duration"),
                "eval_duration_ns": response.get("eval_duration"),
                "load_duration_ns": response.get("load_duration"),
                "total_duration_ns": response.get("total_duration"),
            }

        except (AttributeError, KeyError, TypeError) as exc:
            raise ModelAPIError("Malformed Ollama API response") from exc

        if not isinstance(content, str) or not content.strip():
            raise ModelAPIError(
                "Ollama returned empty final content. "
                f"done_reason={response.get('done_reason')!r}, "
                f"eval_count={response.get('eval_count')!r}, "
                f"thinking_chars={len(self.last_thinking)}"
            )

        return content.strip()

    def _post_json(self, url, extra_headers, payload):
        headers = {"Content-Type": "application/json", **extra_headers}
        body = json.dumps(payload).encode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                api_request = request.Request(
                    url, data=body, headers=headers, method="POST"
                )
                with request.urlopen(api_request, timeout=self.timeout) as response:
                    try:
                        return json.loads(response.read().decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ModelAPIError(
                            "Model API returned invalid JSON"
                        ) from exc

            except error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")[:1000]
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == self.max_retries:
                    raise ModelAPIError(
                        f"Model API returned HTTP {exc.code}: {details}"
                    ) from exc

            except (error.URLError, TimeoutError) as exc:
                if attempt == self.max_retries:
                    raise ModelAPIError(
                        f"Model API request failed: {exc}"
                    ) from exc

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
    task_id = gamefile or hashlib.sha1(
        initial_obs.encode("utf-8")
    ).hexdigest()[:16]

    trajectory = []
    skill = _load_skill()
    success = False
    termination = "max_steps"
    start_time = time.time()

    for step in range(1, max_steps + 1):
        admissible_actions = list(info["admissible_commands"][0])
        if not admissible_actions:
            termination = "no_admissible_actions"
            break

        prompt = build_prompt(
            task, current_obs, admissible_actions, trajectory, skill
        )

        model_call_start = time.time()
        raw_output = call_model(prompt)
        model_call_seconds = time.time() - model_call_start

        thinking = _MODEL_CLIENT.last_thinking
        usage = dict(_MODEL_CLIENT.last_usage)

        # Execute the semantic action selected by the model.
        # Do not use an integer -> action mapping for control.
        action = parse_action(raw_output, admissible_actions)
        format_repair = False
        repair_output = None
        repair_usage = None

        if action is None:
            repair_started = time.time()
            repair_output = call_model(
                build_repair_prompt(task, current_obs, admissible_actions)
            )
            model_call_seconds += time.time() - repair_started
            repair_usage = dict(_MODEL_CLIENT.last_usage)
            action = parse_action(repair_output, admissible_actions)
            format_repair = action is not None

        if action is None:
            trajectory.append({
                "step": step,
                "observation": current_obs,
                "admissible_actions": admissible_actions,
                "thinking": thinking,
                "model_output": raw_output,
                "repair_output": repair_output,
                "action": None,
                "action_index": None,
                "next_observation": None,
                "reward": 0,
                "done": False,
                "format_error": True,
                "model_call_seconds": model_call_seconds,
                "model_usage": usage,
                "repair_usage": repair_usage,
            })
            termination = "invalid_model_output"
            break

        # Keep index only as metadata for analysis.
        action_index = admissible_actions.index(action)

        next_obs, rewards, dones, next_info = env.step([action])
        reward = None if rewards is None else float(rewards[0])
        done = bool(dones[0])
        won = bool(first_value(next_info, "won", False))

        trajectory.append({
            "step": step,
            "observation": current_obs,
            "admissible_actions": admissible_actions,
            "thinking": thinking,
            "model_output": raw_output,
            "repair_output": repair_output,
            "action_index": action_index,
            "action": action,
            "next_observation": next_obs[0],
            "reward": reward,
            "done": done,
            "won": won,
            "format_error": False,
            "format_repair": format_repair,
            "model_call_seconds": model_call_seconds,
            "model_usage": usage,
            "repair_usage": repair_usage,
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
        "condition": os.environ.get("CONDITION", "student_baseline"),
        "skill_file": os.environ.get("SKILL_FILE", "") or None,
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


def _task_match_key(value):
    """Normalize task paths so results from another machine can be reused."""
    value = str(value or "").replace("\\", "/").rstrip("/")
    return value.lower()


def _select_fixed_game_files(game_files, task_ids_path):
    if not task_ids_path:
        return list(game_files)

    path = Path(task_ids_path)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    task_ids = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(task_ids, dict):
        task_ids = task_ids.get("task_ids", [])
    if not isinstance(task_ids, list) or not task_ids:
        raise ValueError(f"Task ID file must contain a non-empty list: {path}")

    available = {_task_match_key(item): item for item in game_files}
    selected = []
    missing = []
    for task_id in task_ids:
        wanted = _task_match_key(task_id)
        exact = available.get(wanted)
        if exact:
            selected.append(exact)
            continue
        wanted_parts = wanted.split("/")
        suffix_matches = [
            item for key, item in available.items()
            if key.endswith(wanted)
            or wanted.endswith(key)
            or (len(wanted_parts) >= 2 and key.split("/")[-2:] == wanted_parts[-2:])
        ]
        if len(suffix_matches) != 1:
            missing.append(task_id)
        else:
            selected.append(suffix_matches[0])
    if missing:
        raise RuntimeError(
            f"Could not uniquely match {len(missing)} fixed task IDs from {path}: {missing[:3]}"
        )
    if len(set(selected)) != len(selected):
        raise RuntimeError(f"Fixed task ID file contains duplicate or ambiguous tasks: {path}")
    return selected


def main():
    load_env_file()

    configured_data = os.environ.get("ALFWORLD_DATA", "").strip()
    if not configured_data:
        bundled_data = Path(__file__).parent / "alfworld" / "alfworld" / "data"
        if not (bundled_data / "json_2.1.1").exists():
            raise RuntimeError(
                "ALFWORLD_DATA is not configured and no downloaded ALFWorld dataset "
                "was found. Set ALFWORLD_DATA to the directory containing "
                "json_2.1.1, logic, and (for TextWorld) generated game files."
            )

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
    fixed_task_file = os.environ.get("TASK_IDS_FILE", "").strip()
    if fixed_task_file:
        env_factory.game_files = _select_fixed_game_files(
            env_factory.game_files, fixed_task_file
        )
        env_factory.num_games = len(env_factory.game_files)
        print(f"Fixed task set: {env_factory.num_games} games")
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
            print("Termination:", result.get("termination"))
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
