from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

import gaia
from pi_tool_bridge import PythonTool, ToolRegistry


ROOT = Path(__file__).resolve().parents[1]


class PiRequestTests(unittest.TestCase):
    def test_image_task_never_receives_the_trench_skill(self):
        self.assertEqual(
            gaia.selected_skills(gaia.DEFAULT_TASK_ID, "both"),
            [],
        )
        self.assertEqual(
            [
                skill.name
                for skill in gaia.selected_skills(
                    gaia.TRENCH_TASK_ID,
                    "both",
                )
            ],
            [
                "solve-high-pressure-fluid-volume",
                "solve-gaia-r12-trench-volume",
            ],
        )

    def test_request_uses_environment_without_serializing_api_key(self):
        with patch.dict(
            os.environ,
            {
                "MODEL_ID": "deepseek-v4-flash",
                "OPENAI_BASE_URL": "https://api.deepseek.com",
                "OPENAI_API_KEY": "secret-value",
            },
            clear=True,
        ):
            request = gaia.build_pi_request(
                prompt="Question",
                cwd=ROOT,
                max_turns=14,
                use_image_tool=True,
                tool_timeout_seconds=90,
            )

        self.assertEqual(request["model"]["id"], "deepseek-v4-flash")
        self.assertEqual(
            request["model"]["baseUrl"],
            "https://api.deepseek.com",
        )
        self.assertNotIn("apiKey", request["model"])
        self.assertNotIn("secret-value", repr(request))
        self.assertEqual(
            request["enabledTools"],
            ["web_search", "extract_pdf_text", "python", "analyze_image"],
        )

    def test_request_can_disable_image_tool(self):
        with patch.dict(
            os.environ,
            {
                "MODEL_ID": "model",
                "OPENAI_BASE_URL": "https://example.test/v1",
                "OPENAI_API_KEY": "secret",
            },
            clear=True,
        ):
            request = gaia.build_pi_request(
                prompt="Question",
                cwd=ROOT,
                max_turns=8,
                use_image_tool=False,
                tool_timeout_seconds=10,
            )

        self.assertEqual(
            request["enabledTools"],
            ["web_search", "extract_pdf_text", "python"],
        )

    def test_safe_variant_rejects_empty_values(self):
        self.assertEqual(gaia.safe_variant("Pi / image on"), "Pi-image-on")
        with self.assertRaises(ValueError):
            gaia.safe_variant("///")


class ToolRegistryTests(unittest.TestCase):
    def test_python_tool_is_calculation_only(self):
        tool = PythonTool()
        self.assertEqual(tool.forward("print(6 * 7)"), "42")
        with self.assertRaisesRegex(RuntimeError, "not allowed"):
            tool.forward("print(open('../.env').read())")
        with self.assertRaisesRegex(RuntimeError, "not allowed"):
            tool.forward("import os\nprint(os.environ)")

    def test_dispatches_only_enabled_tools(self):
        calls: list[dict[str, str]] = []

        class FakeTool:
            def forward(self, **arguments):
                calls.append(arguments)
                return "tool result"

        registry = ToolRegistry(
            enabled_tools={"web_search"},
            factories={"web_search": FakeTool},
        )

        self.assertEqual(
            registry.call("web_search", {"query": "GAIA"}),
            "tool result",
        )
        self.assertEqual(calls, [{"query": "GAIA"}])
        with self.assertRaisesRegex(KeyError, "not enabled"):
            registry.call("analyze_image", {"source": "x", "question": "y"})

    def test_tool_instances_are_lazy_and_reused(self):
        created: list[object] = []

        class FakeTool:
            def __init__(self):
                created.append(self)

            def forward(self, **_arguments):
                return "ok"

        registry = ToolRegistry(
            enabled_tools={"web_search"},
            factories={"web_search": FakeTool},
        )
        registry.call("web_search", {"query": "one"})
        registry.call("web_search", {"query": "two"})

        self.assertEqual(len(created), 1)


if __name__ == "__main__":
    unittest.main()
