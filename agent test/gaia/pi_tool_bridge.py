"""JSON-lines bridge from Pi SDK tools to the existing Python GAIA tools."""

from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable


class PythonTool:
    """Run restricted calculation snippets in an isolated temp folder."""

    def forward(self, code: str) -> str:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")

        with tempfile.TemporaryDirectory(prefix="gaia-python-") as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "--python-sandbox",
                ],
                cwd=directory,
                input=code,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                env=_minimal_python_env(),
            )

        output = "\n".join(
            part
            for part in (
                result.stdout.strip(),
                result.stderr.strip(),
            )
            if part
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Python exited with code {result.returncode}:\n{output[:20000]}"
            )
        return output[:20000] or "(Python completed without output.)"


def _minimal_python_env() -> dict[str, str]:
    """Keep package discovery working without forwarding benchmark API keys."""

    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "PYTHONIOENCODING",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _validate_calculation_code(code: str) -> ast.AST:
    tree = ast.parse(code, mode="exec")
    forbidden_nodes = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)
    forbidden_calls = {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "dir",
        "eval",
        "exec",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "memoryview",
        "open",
        "setattr",
        "vars",
    }
    for node in ast.walk(tree):
        if isinstance(node, forbidden_nodes):
            raise ValueError(
                f"{type(node).__name__} is not allowed in calculation code"
            )
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("dunder names are not allowed in calculation code")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError(
                "private attributes are not allowed in calculation code"
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in forbidden_calls
        ):
            raise ValueError(
                f"{node.func.id}() is not allowed in calculation code"
            )
    return tree


def _run_python_sandbox() -> None:
    import math
    import statistics

    code = sys.stdin.read()
    tree = _validate_calculation_code(code)
    safe_builtins = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "pow": pow,
        "print": print,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
    namespace = {
        "__builtins__": safe_builtins,
        "math": math,
        "statistics": statistics,
    }
    exec(compile(tree, "<gaia-calculation>", "exec"), namespace, namespace)


def default_factories() -> dict[str, Callable[[], Any]]:
    """Load optional tool dependencies only when the bridge is actually used."""

    from smolagents import WebSearchTool

    from gaia_image import AnalyzeImageTool
    from gaia_pdf import ExtractPdfTextTool

    return {
        "web_search": WebSearchTool,
        "extract_pdf_text": ExtractPdfTextTool,
        "analyze_image": AnalyzeImageTool,
        "python": PythonTool,
    }


class ToolRegistry:
    """Own the whitelist and lazy instances for one Pi tool bridge."""

    def __init__(
        self,
        *,
        enabled_tools: set[str],
        factories: dict[str, Callable[[], Any]] | None = None,
    ) -> None:
        self._factories = factories or default_factories()
        unknown = enabled_tools - self._factories.keys()
        if unknown:
            raise KeyError(f"Unknown tools: {sorted(unknown)}")
        self._enabled_tools = enabled_tools
        self._instances: dict[str, Any] = {}

    def call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name not in self._enabled_tools:
            raise KeyError(f"Tool {tool_name!r} is not enabled")
        if not isinstance(arguments, dict):
            raise TypeError("tool arguments must be a JSON object")

        if tool_name not in self._instances:
            self._instances[tool_name] = self._factories[tool_name]()
        result = self._instances[tool_name].forward(**arguments)
        return str(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tools",
        required=True,
        help="Comma-separated whitelist of tool names",
    )
    return parser.parse_args()


def _write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve(registry: ToolRegistry) -> None:
    for raw_line in sys.stdin:
        request_id: Any = None
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise TypeError("request must be a JSON object")
            request_id = request.get("id")
            tool_name = request.get("tool")
            arguments = request.get("arguments")
            if not isinstance(request_id, str) or not request_id:
                raise ValueError("request id must be a non-empty string")
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError("tool must be a non-empty string")

            chatter = io.StringIO()
            with redirect_stdout(chatter):
                result = registry.call(tool_name, arguments)
            if chatter.getvalue():
                sys.stderr.write(chatter.getvalue())
                sys.stderr.flush()
            _write_message({"id": request_id, "ok": True, "result": result})
        except Exception as exc:
            _write_message(
                {
                    "id": request_id,
                    "ok": False,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
            )


def main() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:] == ["--python-sandbox"]:
        _run_python_sandbox()
        return
    args = parse_args()
    enabled = {name.strip() for name in args.tools.split(",") if name.strip()}
    serve(ToolRegistry(enabled_tools=enabled))


if __name__ == "__main__":
    main()
