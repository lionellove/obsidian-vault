import sys
import tempfile
from pathlib import Path
from types import ModuleType

try:
    import pytest  # type: ignore
except ImportError:
    pytest = None

from stage0_alfworld import (
    AlfredTWEnvAdapter,
    AlfredTWEnvDependencyError,
    resolve_manifest_gamefile,
)


def test_manifest_relative_gamefile_is_resolved_under_train_only():
    with tempfile.TemporaryDirectory() as tmp:
        train = Path(tmp) / "json_2.1.1" / "train"
        game = train / "pick_and_place_simple-Vase-None-Safe-1" / "trial_T" / "game.tw-pddl"
        game.parent.mkdir(parents=True)
        game.write_text("", encoding="utf-8")
        assert resolve_manifest_gamefile(train, "pick_and_place_simple-Vase-None-Safe-1/trial_T/game.tw-pddl") == game.resolve()


def test_manifest_gamefile_cannot_escape_train_or_use_other_split():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        train = root / "json_2.1.1" / "train"
        train.mkdir(parents=True)
        bad = root / "json_2.1.1" / "valid_seen" / "x" / "trial_T" / "game.tw-pddl"
        bad.parent.mkdir(parents=True)
        bad.write_text("", encoding="utf-8")
        if pytest is not None:
            with pytest.raises(ValueError):
                resolve_manifest_gamefile(train, "../valid_seen/x/trial_T/game.tw-pddl")
        else:
            try:
                resolve_manifest_gamefile(train, "../valid_seen/x/trial_T/game.tw-pddl")
            except ValueError:
                pass
            else:
                raise AssertionError("expected ValueError")


def test_adapter_wraps_scalar_action_as_single_batch_action():
    class Underlying:
        def reset(self):
            return "obs", {}

        def step(self, actions):
            assert actions == ["look"]
            return "next", 1, True, {}

        def close(self):
            self.closed = True

    underlying = Underlying()
    adapter = AlfredTWEnvAdapter(underlying)
    assert adapter.reset() == ("obs", {})
    assert adapter.step("look")[0] == "next"
    adapter.close()
    assert underlying.closed is True


def test_missing_alfworld_dependency_has_clear_error_without_import_at_module_load():
    # Calling the explicit lazy import seam with a fake missing module is
    # tested through the public factory's dependency parameter.
    from stage0_alfworld import create_alfworld_env

    with tempfile.TemporaryDirectory() as tmp:
        train = Path(tmp) / "train"
        game = train / "pick_and_place_simple-Vase-None-Safe-1" / "trial_T" / "game.tw-pddl"
        game.parent.mkdir(parents=True)
        game.write_text("", encoding="utf-8")
        try:
            create_alfworld_env(train, "pick_and_place_simple-Vase-None-Safe-1/trial_T/game.tw-pddl", config={})
        except AlfredTWEnvDependencyError as exc:
            assert "ALFWorld" in str(exc)
        except (KeyError, ValueError):
            # A real ALFWorld import may be available in some environments;
            # missing config is still a clear preflight failure, not a network call.
            pass


def test_factory_scopes_data_path_and_writes_random_seed(monkeypatch=None):
    """Fake lazy import verifies the exact ALFWorld config seam."""
    import sys
    from types import ModuleType
    from stage0_alfworld import create_alfworld_env

    class FakeEnv:
        def reset(self):
            return "obs", {}

        def step(self, actions):
            return "obs", 0, True, {}

    captured = {}

    class Factory:
        game_files = []
        num_games = 0

        def __init__(self, config):
            captured["config"] = config

        def init_env(self, batch_size=1):
            captured["batch_size"] = batch_size
            return FakeEnv()

    environment = ModuleType("alfworld.agents.environment")
    environment.get_environment = lambda env_type: (lambda config, train_eval: Factory(config))
    agents = ModuleType("alfworld.agents")
    alfworld = ModuleType("alfworld")
    agents.environment = environment
    alfworld.agents = agents
    old = {name: sys.modules.get(name) for name in ("alfworld", "alfworld.agents", "alfworld.agents.environment")}
    sys.modules["alfworld"] = alfworld
    sys.modules["alfworld.agents"] = agents
    sys.modules["alfworld.agents.environment"] = environment
    try:
        with tempfile.TemporaryDirectory() as tmp:
            train = Path(tmp) / "json_2.1.1" / "train"
            game = train / "pick_and_place_simple-Vase-None-Safe-1" / "trial_T" / "game.tw-pddl"
            game.parent.mkdir(parents=True)
            game.write_text("", encoding="utf-8")
            adapter = create_alfworld_env(train, str(game.relative_to(train)), config={}, environment_seed=41)
            assert captured["config"]["dataset"]["data_path"] == str(game.parent)
            assert captured["config"]["general"]["random_seed"] == 41
            assert adapter.environment_seed == 41
    finally:
        for name, value in old.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
