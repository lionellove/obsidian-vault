import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gaia_image import AnalyzeImageTool
from external_tools import ExternalToolBundle, _read_config
from load_skill import discover_skills, render_skills
from run_gaia_sample import TARGET_TASK_ID, build_prompt


ROOT = Path(__file__).resolve().parents[1]


class ImageToolTests(unittest.TestCase):
    def test_tool_schema_is_valid(self):
        tool = AnalyzeImageTool()
        self.assertEqual(tool.name, "analyze_image")
        self.assertEqual(set(tool.inputs), {"source", "question"})

    def test_siliconflow_client_is_created_lazily_and_reused(self):
        response = Mock()
        response.choices = [Mock(message=Mock(content="a horse-headed jade figure"))]
        client = Mock()
        client.chat.completions.create.return_value = response
        with (
            patch.dict(os.environ, {"SILICON_TOKEN": "test-token"}, clear=True),
            patch("gaia_image.OpenAI", return_value=client) as openai,
        ):
            tool = AnalyzeImageTool()
            openai.assert_not_called()

            first = tool.forward("https://example.test/figure.jpg", "What is it?")
            second = tool.forward(
                "https://example.test/figure-2.jpg",
                "Are hands visible?",
            )

        self.assertEqual(first, "a horse-headed jade figure")
        self.assertEqual(second, "a horse-headed jade figure")
        openai.assert_called_once_with(
            api_key="test-token",
            base_url="https://api.siliconflow.cn/v1",
            timeout=120.0,
            max_retries=1,
        )
        self.assertEqual(
            client.chat.completions.create.call_args_list,
            [
                unittest.mock.call(
                    model="Qwen/Qwen3-VL-32B-Instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": "https://example.test/figure.jpg",
                                        "detail": "high",
                                    },
                                },
                                {"type": "text", "text": "What is it?"},
                            ],
                        }
                    ],
                    max_tokens=1024,
                    temperature=0.1,
                ),
                unittest.mock.call(
                    model="Qwen/Qwen3-VL-32B-Instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": "https://example.test/figure-2.jpg",
                                        "detail": "high",
                                    },
                                },
                                {"type": "text", "text": "Are hands visible?"},
                            ],
                        }
                    ],
                    max_tokens=1024,
                    temperature=0.1,
                ),
            ],
        )

    def test_local_image_is_sent_as_a_data_url(self):
        response = Mock()
        response.choices = [Mock(message=Mock(content="answer"))]
        client = Mock()
        client.chat.completions.create.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "figure.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nimage-bytes")
            with (
                patch.dict(
                    os.environ,
                    {"SILICON_TOKEN": "test-token"},
                    clear=True,
                ),
                patch("gaia_image.OpenAI", return_value=client),
            ):
                AnalyzeImageTool().forward(str(image), "What is it?")

        image_url = (
            client.chat.completions.create.call_args.kwargs["messages"][0]
            ["content"][0]["image_url"]["url"]
        )
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertNotIn(str(image), image_url)

    def test_extensionless_image_uses_content_type_detection(self):
        response = Mock()
        response.choices = [Mock(message=Mock(content="answer"))]
        client = Mock()
        client.chat.completions.create.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "figure"
            image.write_bytes(
                bytes.fromhex(
                    "89504e470d0a1a0a0000000d494844520000000100000001"
                    "0802000000907753de0000000c49444154789c6360f8cf0000"
                    "03010100c9fe92ef0000000049454e44ae426082"
                )
            )
            with (
                patch.dict(
                    os.environ,
                    {"SILICON_TOKEN": "test-token"},
                    clear=True,
                ),
                patch("gaia_image.OpenAI", return_value=client),
            ):
                AnalyzeImageTool().forward(str(image), "What is it?")

        image_url = (
            client.chat.completions.create.call_args.kwargs["messages"][0]
            ["content"][0]["image_url"]["url"]
        )
        self.assertTrue(image_url.startswith("data:image/png;base64,"))

    def test_oversized_local_image_is_rejected_before_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "figure.png"
            image.write_bytes(b"12345")
            with patch.dict(
                os.environ,
                {
                    "SILICON_TOKEN": "test-token",
                    "SILICON_VISION_MAX_IMAGE_BYTES": "4",
                },
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "exceeds"):
                    AnalyzeImageTool().forward(str(image), "What is it?")

    def test_siliconflow_configuration_can_be_overridden(self):
        environment = {
            "SILICON_TOKEN": "silicon-token",
            "SILICON_BASE_URL": "https://silicon.example/v1",
            "SILICON_VISION_MODEL": "owner/custom-vlm",
            "SILICON_VISION_DETAIL": "low",
            "SILICON_VISION_MAX_TOKENS": "321",
            "SILICON_VISION_TIMEOUT_SECONDS": "9",
        }
        response = Mock()
        response.choices = [Mock(message=Mock(content="answer"))]
        client = Mock()
        client.chat.completions.create.return_value = response
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("gaia_image.OpenAI", return_value=client) as openai,
        ):
            AnalyzeImageTool().forward(
                "https://example.test/figure.jpg",
                "What is it?",
            )

        openai.assert_called_once_with(
            api_key="silicon-token",
            base_url="https://silicon.example/v1",
            timeout=9.0,
            max_retries=1,
        )
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "owner/custom-vlm")
        self.assertEqual(request["max_tokens"], 321)
        self.assertEqual(
            request["messages"][0]["content"][0]["image_url"]["detail"],
            "low",
        )

    def test_missing_siliconflow_token_has_an_actionable_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "SILICON_TOKEN",
            ):
                AnalyzeImageTool().forward(
                    "https://example.test/figure.jpg",
                    "What is it?",
                )

    def test_siliconflow_failure_has_an_actionable_error(self):
        client = Mock()
        client.chat.completions.create.side_effect = TimeoutError("timed out")
        with (
            patch.dict(os.environ, {"SILICON_TOKEN": "test-token"}, clear=True),
            patch("gaia_image.OpenAI", return_value=client),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "SiliconFlow visual question answering failed",
            ):
                AnalyzeImageTool().forward(
                    "https://example.test/figure.jpg",
                    "What is it?",
                )


class SkillTests(unittest.TestCase):
    def test_repository_skills_load(self):
        skills = discover_skills(ROOT / "Skill")
        self.assertEqual(
            set(skills),
            {
                "solve-gaia-r12-trench-volume",
                "solve-high-pressure-fluid-volume",
            },
        )
        rendered = render_skills(list(skills.values()))
        self.assertIn("procedural prior knowledge", rendered)
        self.assertIn("<skill name=", rendered)

    def test_target_skill_does_not_embed_reference_answer(self):
        skills = discover_skills(ROOT / "Skill")
        target = skills["solve-gaia-r12-trench-volume"]
        self.assertNotIn("reference answer is", target.body.lower())

    def test_invalid_skill_frontmatter_is_rejected(self):
        from load_skill import read_skill

        with tempfile.TemporaryDirectory() as directory:
            skill_file = Path(directory) / "SKILL.md"
            skill_file.write_text("---\nname: broken\n---\nbody", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_skill(skill_file)

    def test_target_prompt_injects_both_skills_without_reference_answer(self):
        row = {
            "task_id": TARGET_TASK_ID,
            "Question": "Synthetic question text",
            "Level": 3,
            "Final answer": "SECRET_REFERENCE",
            "file_name": "",
            "file_path": "",
        }
        prompt, skill_names, attachment = build_prompt(row, ROOT, "both")

        self.assertEqual(
            skill_names,
            [
                "solve-high-pressure-fluid-volume",
                "solve-gaia-r12-trench-volume",
            ],
        )
        self.assertIsNone(attachment)
        self.assertIn("Synthetic question text", prompt)
        self.assertNotIn("SECRET_REFERENCE", prompt)


class ExternalToolConfigTests(unittest.TestCase):
    def test_config_parser_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text('{"unexpected": true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                _read_config(config_file)

    def test_docker_mcp_profile_loads_as_one_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                """
                {
                  "docker_mcp": {
                    "profile": "gaia",
                    "connect_timeout_seconds": 180
                  },
                  "max_tools": 40
                }
                """,
                encoding="utf-8",
            )

            with patch("external_tools.MCPClient") as client_type:
                loaded_tool = type("LoadedTool", (), {"name": "fetch"})()
                client_type.return_value.get_tools.return_value = [loaded_tool]
                with ExternalToolBundle(config_file) as bundle:
                    self.assertEqual(bundle.tools, [loaded_tool])

            parameters = client_type.call_args.args[0]
            self.assertEqual(len(parameters), 1)
            self.assertEqual(parameters[0].command, "docker")
            self.assertEqual(
                parameters[0].args,
                [
                    "mcp",
                    "gateway",
                    "run",
                    "--profile",
                    "gaia",
                    "--static",
                ],
            )
            client_type.assert_called_once_with(
                parameters,
                adapter_kwargs={"connect_timeout": 180},
                structured_output=True,
            )
            client_type.return_value.disconnect.assert_called_once_with()

    def test_docker_mcp_profile_rejects_an_empty_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                '{"docker_mcp": {"profile": "gaia"}}',
                encoding="utf-8",
            )

            with patch("external_tools.MCPClient") as client_type:
                client_type.return_value.get_tools.return_value = []
                with self.assertRaisesRegex(ValueError, "loaded no tools"):
                    with ExternalToolBundle(config_file):
                        pass

            client_type.return_value.disconnect.assert_called_once_with()

    def test_docker_mcp_cannot_be_combined_with_direct_mcp_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                """
                {
                  "docker_mcp": {"profile": "gaia"},
                  "mcp_servers": [
                    {"transport": "streamable-http", "url": "https://example.test"}
                  ]
                }
                """,
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "cannot be combined"):
                _read_config(config_file)

    def test_allowlist_rejects_missing_tool_names(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                """
                {
                  "docker_mcp": {"profile": "gaia"},
                  "tool_allowlist": ["fetch", "misspelled_tool"]
                }
                """,
                encoding="utf-8",
            )

            with patch("external_tools.MCPClient") as client_type:
                client_type.return_value.get_tools.return_value = [
                    type("LoadedTool", (), {"name": "fetch"})()
                ]
                with self.assertRaisesRegex(ValueError, "misspelled_tool"):
                    with ExternalToolBundle(config_file):
                        pass

            client_type.return_value.disconnect.assert_called_once_with()

    def test_config_parser_rejects_collection_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                '{"mcp_servers": "not-a-list"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "mcp_servers must be a list"):
                _read_config(config_file)

    def test_initialization_error_survives_disconnect_error(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                '{"docker_mcp": {"profile": "gaia"}}',
                encoding="utf-8",
            )

            with patch("external_tools.MCPClient") as client_type:
                client_type.return_value.get_tools.return_value = []
                client_type.return_value.disconnect.side_effect = RuntimeError(
                    "cleanup failed"
                )
                with self.assertRaisesRegex(ValueError, "loaded no tools") as caught:
                    with ExternalToolBundle(config_file):
                        pass

            self.assertTrue(
                any("cleanup failed" in note for note in caught.exception.__notes__)
            )

    def test_mcp_child_only_receives_system_and_explicit_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                """
                {
                  "docker_mcp": {
                    "profile": "gaia",
                    "env_passthrough": ["DOCKER_HOST"]
                  }
                }
                """,
                encoding="utf-8",
            )
            environment = {
                "PATH": "C:/tools",
                "PROGRAMDATA": "C:/ProgramData",
                "PROGRAMFILES": "C:/Program Files",
                "USERPROFILE": "C:/Users/test",
                "DOCKER_HOST": "npipe:////./pipe/docker_engine",
                "DEEPSEEK_API_KEY": "must-not-leak",
                "VISION_API_KEY": "must-not-leak",
            }

            with (
                patch.dict(os.environ, environment, clear=True),
                patch("external_tools.MCPClient") as client_type,
            ):
                client_type.return_value.get_tools.return_value = [
                    type("LoadedTool", (), {"name": "fetch"})()
                ]
                with ExternalToolBundle(config_file):
                    pass

            child_env = client_type.call_args.args[0][0].env
            self.assertEqual(child_env["PATH"], "C:/tools")
            self.assertEqual(child_env["PROGRAMDATA"], "C:/ProgramData")
            self.assertEqual(child_env["PROGRAMFILES"], "C:/Program Files")
            self.assertEqual(child_env["USERPROFILE"], "C:/Users/test")
            self.assertEqual(
                child_env["DOCKER_HOST"],
                "npipe:////./pipe/docker_engine",
            )
            self.assertNotIn("DEEPSEEK_API_KEY", child_env)
            self.assertNotIn("VISION_API_KEY", child_env)

    def test_docker_mcp_profile_rejects_unknown_options(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                """
                {
                  "docker_mcp": {
                    "profile": "gaia",
                    "profiel": "misspelled"
                  }
                }
                """,
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Unsupported docker_mcp keys"):
                with ExternalToolBundle(config_file):
                    pass

    def test_gateway_disconnects_when_profile_exceeds_tool_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "tools.json"
            config_file.write_text(
                """
                {
                  "docker_mcp": {"profile": "gaia"},
                  "max_tools": 1
                }
                """,
                encoding="utf-8",
            )
            loaded_tools = [
                type("LoadedTool", (), {"name": "first"})(),
                type("LoadedTool", (), {"name": "second"})(),
            ]

            with patch("external_tools.MCPClient") as client_type:
                client_type.return_value.get_tools.return_value = loaded_tools
                with self.assertRaisesRegex(ValueError, "exceeding max_tools=1"):
                    with ExternalToolBundle(config_file):
                        pass

            client_type.return_value.disconnect.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
