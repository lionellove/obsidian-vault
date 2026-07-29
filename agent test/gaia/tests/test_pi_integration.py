from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import gaia


ROOT = Path(__file__).resolve().parents[1]


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    mode = "tool_loop"

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.__class__.requests.append(request)
        has_tool_result = any(
            message.get("role") == "tool"
            for message in request.get("messages", [])
        )

        if self.__class__.mode == "no_marker":
            chunks = [
                {
                    "id": "completion-no-marker",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fake-gaia",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": "42",
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "completion-no-marker",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fake-gaia",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                },
            ]
        elif has_tool_result:
            chunks = [
                {
                    "id": "completion-2",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fake-gaia",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": "<final_answer>42</final_answer>",
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "completion-2",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fake-gaia",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 4,
                        "total_tokens": 24,
                    },
                },
            ]
        else:
            chunks = [
                {
                    "id": "completion-1",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fake-gaia",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-python-1",
                                        "type": "function",
                                        "function": {
                                            "name": "python",
                                            "arguments": (
                                                '{"code":"print(6 * 7)"}'
                                            ),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "completion-1",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fake-gaia",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 3,
                        "total_tokens": 13,
                    },
                },
            ]

        body = "".join(
            f"data: {json.dumps(chunk)}\n\n" for chunk in chunks
        )
        body += "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args):
        return


class PiEndToEndTests(unittest.TestCase):
    def test_pi_native_tool_loop_reaches_python_bridge(self):
        _FakeOpenAIHandler.requests = []
        _FakeOpenAIHandler.mode = "tool_loop"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}/v1"

        try:
            with patch.dict(
                os.environ,
                {
                    "MODEL_ID": "fake-gaia",
                    "OPENAI_BASE_URL": base_url,
                    "OPENAI_API_KEY": "offline-test-key",
                },
                clear=False,
            ):
                request = gaia.build_pi_request(
                    prompt="Use Python to calculate 6 * 7.",
                    cwd=ROOT,
                    max_turns=2,
                    use_image_tool=False,
                    tool_timeout_seconds=20,
                )
                response, stderr = gaia.invoke_pi(
                    request,
                    timeout_seconds=90,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertIsNone(response["error"], stderr)
        self.assertEqual(response["prediction"], "42")
        self.assertEqual(response["turns"], 2)
        self.assertIsNone(response["errorType"])
        self.assertEqual(response["toolErrorCount"], 0)
        self.assertEqual(len(_FakeOpenAIHandler.requests), 2)
        second_messages = _FakeOpenAIHandler.requests[1]["messages"]
        tool_messages = [
            message for message in second_messages if message["role"] == "tool"
        ]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("42", tool_messages[0]["content"])
        self.assertTrue(
            any(
                log.get("type") == "tool_execution_end"
                and log.get("toolName") == "python"
                and not log.get("isError")
                for log in response["logs"]
            )
        )

    def test_answer_format_error_is_not_reported_as_model_error(self):
        _FakeOpenAIHandler.requests = []
        _FakeOpenAIHandler.mode = "no_marker"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}/v1"

        try:
            with patch.dict(
                os.environ,
                {
                    "MODEL_ID": "fake-gaia",
                    "OPENAI_BASE_URL": base_url,
                    "OPENAI_API_KEY": "offline-test-key",
                },
                clear=False,
            ):
                request = gaia.build_pi_request(
                    prompt="Return 42 without the required marker.",
                    cwd=ROOT,
                    max_turns=2,
                    use_image_tool=False,
                    tool_timeout_seconds=20,
                )
                response, stderr = gaia.invoke_pi(
                    request,
                    timeout_seconds=90,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(response["errorType"], "answer_format_error", stderr)
        self.assertEqual(response["terminatedBy"], "answer_format_error")
        self.assertIsNone(response["prediction"])


if __name__ == "__main__":
    unittest.main()
