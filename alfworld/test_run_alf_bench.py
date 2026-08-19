import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_alf_bench as bench


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeEnvironment:
    def reset(self):
        return ["Your task is to: inspect the room"], {
            "admissible_commands": [["look"]],
            "extra.gamefile": ["look_at_obj_in_light/test"],
        }

    def step(self, _actions):
        return ["Done."], None, [True], {
            "admissible_commands": [[]],
            "won": [True],
            "extra.gamefile": ["look_at_obj_in_light/test"],
        }


class RunAlfBenchTests(unittest.TestCase):
    def setUp(self):
        bench._MODEL_CLIENT = None

    def test_parse_action_requires_exact_membership(self):
        actions = ["inventory", "take mug 3 from countertop 2"]
        self.assertEqual(bench.parse_action("FINAL_ACTION: inventory", actions), "inventory")
        self.assertEqual(bench.parse_action("FINAL_ACTION: **inventory**", actions), "inventory")
        self.assertIsNone(bench.parse_action("FINAL_ACTION: take mug 3", actions))
        self.assertIsNone(bench.parse_action("inventory", actions))

    def test_build_prompt_injects_skill_as_separate_section(self):
        prompt = bench.build_prompt("clean mug", "at sink", ["clean mug 1 with sinkbasin 1"], [], "Do prerequisites first.")
        self.assertIn("Reusable procedural guidance:", prompt)
        self.assertIn("Do prerequisites first.", prompt)
        self.assertIn("Currently admissible actions:", prompt)

    def test_load_env_file_preserves_existing_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env"
            path.write_text("A=from-file\nexport B='quoted'\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"A": "existing"}, clear=True):
                bench.load_env_file(path)
                self.assertEqual(os.environ["A"], "existing")
                self.assertEqual(os.environ["B"], "quoted")

    def test_openai_compatible_request(self):
        env = {"OPENAI_API_KEY": "secret", "OPENAI_BASE_URL": "https://example.test", "MODEL_ID": "test/model"}
        with mock.patch.dict(os.environ, env, clear=True):
            client = bench.ModelClient("openai")
            with mock.patch.object(bench.request, "urlopen", return_value=FakeResponse({"choices": [{"message": {"content": "ok"}}]})) as urlopen:
                self.assertEqual(client.complete("prompt"), "ok")
        api_request = urlopen.call_args.args[0]
        self.assertEqual(api_request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(api_request.get_header("Authorization"), "Bearer secret")

    def test_ollama_request_has_thinking_disabled_by_default(self):
        with mock.patch.dict(os.environ, {"OLLAMA_MODEL": "test-model"}, clear=True):
            client = bench.ModelClient("ollama")
            with mock.patch.object(bench.request, "urlopen", return_value=FakeResponse({"message": {"content": "FINAL_ACTION: look"}, "done": True})) as urlopen:
                self.assertEqual(client.complete("prompt"), "FINAL_ACTION: look")
        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertFalse(payload["think"])
        self.assertEqual(payload["options"]["num_ctx"], 16384)
        self.assertEqual(payload["options"]["num_predict"], 512)
        self.assertEqual(payload["options"]["temperature"], 0)

    def test_select_fixed_game_files_matches_cross_platform_suffix(self):
        selected = bench._select_fixed_game_files(
            [r"D:\data\trial_a\game.tw-pddl", r"D:\data\trial_b\game.tw-pddl"],
            self._write_task_file(["/home/user/trial_b/game.tw-pddl"]),
        )
        self.assertEqual(selected, [r"D:\data\trial_b\game.tw-pddl"])

    def _write_task_file(self, task_ids):
        temp_dir = tempfile.mkdtemp()
        path = Path(temp_dir) / "tasks.json"
        path.write_text(json.dumps({"task_ids": task_ids}), encoding="utf-8")
        return path

    def test_run_episode_uses_exact_string_control_path(self):
        bench._MODEL_CLIENT = mock.Mock(last_thinking="", last_usage={})
        with mock.patch.object(bench, "call_model", return_value="FINAL_ACTION: look"):
            result = bench.run_episode(FakeEnvironment(), 0, "test-model")
        self.assertTrue(result["success"])
        self.assertEqual(result["trajectory"][0]["action"], "look")
        self.assertIsNone(result["trajectory"][0]["reward"])


if __name__ == "__main__":
    unittest.main()
