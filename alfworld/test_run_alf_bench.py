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


class FakeThorEnvironment:
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

    def test_load_env_file_preserves_existing_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("A=from-file\nexport B='quoted'\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"A": "existing"}, clear=True):
                bench.load_env_file(env_path)
                self.assertEqual(os.environ["A"], "existing")
                self.assertEqual(os.environ["B"], "quoted")

    def test_parse_action_index_is_strict_but_accepts_code_fence(self):
        self.assertEqual(bench.parse_action_index("2", 3), 2)
        self.assertEqual(bench.parse_action_index("```\n1\n```", 3), 1)
        self.assertIsNone(bench.parse_action_index("Action: 1", 3))
        self.assertIsNone(bench.parse_action_index("3", 3))

    def test_openai_compatible_request(self):
        env = {
            "OPENAI_API_KEY": "secret",
            "OPENAI_BASE_URL": "https://example.test",
            "MODEL_ID": "test/model",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            client = bench.ModelClient("openai")
            payload = {"choices": [{"message": {"content": "1"}}]}
            with mock.patch.object(
                bench.request, "urlopen", return_value=FakeResponse(payload)
            ) as urlopen:
                self.assertEqual(client.complete("prompt"), "1")

        api_request = urlopen.call_args.args[0]
        self.assertEqual(api_request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(api_request.get_header("Authorization"), "Bearer secret")

    def test_anthropic_request(self):
        env = {
            "ANTHROPIC_API_KEY": "secret",
            "ANTHROPIC_BASE_URL": "https://example.test/v1",
            "ANTHROPIC_MODEL": "claude-test",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            client = bench.ModelClient("anthropic")
            payload = {"content": [{"type": "text", "text": "0"}]}
            with mock.patch.object(
                bench.request, "urlopen", return_value=FakeResponse(payload)
            ) as urlopen:
                self.assertEqual(client.complete("prompt"), "0")

        api_request = urlopen.call_args.args[0]
        self.assertEqual(api_request.full_url, "https://example.test/v1/messages")
        self.assertEqual(api_request.get_header("X-api-key"), "secret")

    def test_malformed_api_response_is_fatal(self):
        env = {
            "OPENAI_API_KEY": "secret",
            "OPENAI_BASE_URL": "https://example.test",
            "MODEL_ID": "test-model",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            client = bench.ModelClient("openai")
            with mock.patch.object(
                bench.request, "urlopen", return_value=FakeResponse({"error": {}})
            ):
                with self.assertRaises(bench.ModelAPIError):
                    client.complete("prompt")

    def test_malformed_anthropic_response_is_fatal(self):
        env = {
            "ANTHROPIC_API_KEY": "secret",
            "ANTHROPIC_BASE_URL": "https://example.test",
            "ANTHROPIC_MODEL": "claude-test",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            client = bench.ModelClient("anthropic")
            with mock.patch.object(
                bench.request, "urlopen", return_value=FakeResponse({"content": None})
            ):
                with self.assertRaises(bench.ModelAPIError):
                    client.complete("prompt")

    def test_model_name_becomes_safe_result_filename(self):
        self.assertEqual(bench._safe_filename("org/model:latest"), "org_model_latest")

    def test_evaluation_split_accepts_aliases_and_rejects_unknown_value(self):
        self.assertEqual(bench._evaluation_split("seen"), "eval_in_distribution")
        self.assertEqual(bench._evaluation_split("ood"), "eval_out_of_distribution")
        with self.assertRaises(ValueError):
            bench._evaluation_split("train")

    def test_results_are_written_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.json"
            bench._write_results(output_path, [{"success": True}])
            self.assertEqual(json.loads(output_path.read_text()), [{"success": True}])
            self.assertFalse(Path(str(output_path) + ".tmp").exists())

    def test_run_episode_accepts_thor_environment_without_rewards(self):
        with mock.patch.object(bench, "call_model", return_value="0"):
            result = bench.run_episode(FakeThorEnvironment(), 0, "test-model")

        self.assertTrue(result["success"])
        self.assertEqual(result["termination"], "success")
        self.assertIsNone(result["trajectory"][0]["reward"])


if __name__ == "__main__":
    unittest.main()
