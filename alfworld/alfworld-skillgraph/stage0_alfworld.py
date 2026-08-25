"""Lazy, train-only AlfredTWEnv adapter.

Importing this module does not import ALFWorld or any optional dependency.
The actual factory is called only when a dynamic run explicitly supplies a
train task and configuration.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

from stage0_core import canonical_task_id
from stage0_run import resolve_train_root


class AlfredTWEnvDependencyError(RuntimeError):
    """ALFWorld or one of its optional environment dependencies is unavailable."""


def resolve_manifest_gamefile(train_root: str | Path, task_id: str | Path) -> Path:
    train = resolve_train_root(train_root)
    raw_parts = [part.casefold() for part in str(task_id).replace("\\", "/").split("/")]
    if ".." in raw_parts or any(part in {"valid_train", "valid_seen", "valid_unseen"} for part in raw_parts):
        raise ValueError("manifest task ID must be relative to train and cannot name another split")
    relative = canonical_task_id(task_id, train_root=train)
    candidate = (train / relative).resolve(strict=False)
    try:
        candidate.relative_to(train)
    except ValueError as exc:
        raise ValueError("manifest task ID escapes the train root") from exc
    if candidate.name.casefold() != "game.tw-pddl":
        raise ValueError("manifest task ID must name game.tw-pddl")
    if not candidate.is_file():
        raise FileNotFoundError(f"manifest game file does not exist: {candidate}")
    return candidate


class AlfredTWEnvAdapter:
    """Convert a scalar-action EpisodeEnvironment call into ALFWorld batching."""

    def __init__(self, env: Any, *, environment_seed: int | None = None) -> None:
        self._env = env
        self.environment_seed = environment_seed

    def reset(self) -> Any:
        return self._env.reset()

    def step(self, action: str) -> Any:
        if not isinstance(action, str) or not action:
            raise ValueError("ALFWorld action must be a non-empty string")
        return self._env.step([action])

    def close(self) -> None:
        close = getattr(self._env, "close", None)
        if callable(close):
            close()


def _load_yaml_config(config_file: str | Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise AlfredTWEnvDependencyError(
            "ALFWorld config loading requires PyYAML; install ALFWorld dependencies"
        ) from exc
    path = Path(config_file)
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read ALFWorld config: {path}") from exc
    if not isinstance(config, dict):
        raise ValueError("ALFWorld config must be a mapping")
    return config


def create_alfworld_env(
    train_root: str | Path,
    task_id: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
    config_file: str | Path | None = None,
    env_type: str = "AlfredTWEnv",
    environment_seed: int | None = None,
    seed: int | None = None,
) -> AlfredTWEnvAdapter:
    """Create one lazy-imported TextWorld environment for one train task."""

    if env_type != "AlfredTWEnv":
        raise ValueError("Stage 0 currently supports only env_type=AlfredTWEnv")
    if environment_seed is not None and seed is not None and int(environment_seed) != int(seed):
        raise ValueError("environment_seed and seed disagree")
    if environment_seed is None:
        environment_seed = seed
    if environment_seed is not None and (
        isinstance(environment_seed, bool) or not isinstance(environment_seed, int)
    ):
        raise ValueError("environment_seed must be an integer")
    train = resolve_train_root(train_root)
    gamefile = resolve_manifest_gamefile(train, task_id)
    if config is not None and config_file is not None:
        raise ValueError("provide config or config_file, not both")
    if config is None:
        if config_file is None:
            config_file = Path(__file__).resolve().parents[1] / "alfworld" / "configs" / "base_config.yaml"
        config_dict = _load_yaml_config(config_file)
    else:
        config_dict = copy.deepcopy(dict(config))
    data_home = (train.parent.parent).resolve()
    logic_dir = data_home / "logic"
    logic_domain = (logic_dir / "alfred.pddl").resolve()
    logic_grammar = (logic_dir / "alfred.twl2").resolve()
    missing_logic = [path for path in (logic_domain, logic_grammar) if not path.is_file()]
    if missing_logic:
        missing = ", ".join(str(path) for path in missing_logic)
        raise AlfredTWEnvDependencyError(
            "ALFWorld logic assets are missing under the data home derived from train root "
            f"({data_home}): {missing}"
        )
    try:
        dataset = config_dict.setdefault("dataset", {})
        env_config = config_dict.setdefault("env", {})
        general = config_dict.setdefault("general", {})
        logic = config_dict.setdefault("logic", {})
        if not isinstance(logic, dict):
            raise ValueError("ALFWorld config logic section must be a mapping")
        # AlfredTWEnv recursively scans data_path during construction.  The
        # manifest already resolved an exact game file, so scope the config
        # to that trial directory and avoid rescanning the full 3.5k-task
        # train tree for every paired episode.
        dataset["data_path"] = str(gamefile.parent)
        dataset["num_train_games"] = 1
        env_config["domain_randomization"] = False
        if environment_seed is not None:
            # Keep the seed in the config passed to ALFWorld as well as on
            # the adapter, so a resumed paired episode is reproducible.
            env_config["seed"] = environment_seed
            general["random_seed"] = environment_seed
        logic["domain"] = str(logic_domain)
        logic["grammar"] = str(logic_grammar)
        # The train split normally enables expert-plan wrappers for dagger;
        # Stage 0 must never expose expert trajectories to the Executor.
        general["training_method"] = "dqn"
    except AttributeError as exc:
        raise ValueError("ALFWorld config sections must be mappings") from exc

    try:
        # These imports are deliberately inside the factory: structural and
        # fake-environment tests remain runnable without ALFWorld installed.
        from alfworld.agents.environment import get_environment  # type: ignore
    except ImportError as exc:
        raise AlfredTWEnvDependencyError(
            "ALFWorld dependencies are unavailable; install the ALFWorld text environment"
        ) from exc

    try:
        factory = get_environment(env_type)(config_dict, train_eval="train")
        factory.game_files = [str(gamefile)]
        factory.num_games = 1
        env = factory.init_env(batch_size=1)
    except Exception as exc:
        raise AlfredTWEnvDependencyError(
            f"could not initialize AlfredTWEnv for {gamefile}: {exc}"
        ) from exc
    return AlfredTWEnvAdapter(env, environment_seed=environment_seed)
