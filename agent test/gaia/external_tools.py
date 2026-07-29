"""Load third-party tools through standard adapters instead of reimplementing them."""

from __future__ import annotations

from contextlib import AbstractContextManager
import json
import os
from pathlib import Path
from typing import Any

from smolagents import MCPClient, Tool, load_tool


_MCP_SYSTEM_ENVIRONMENT = {
    "APPDATA",
    "COMSPEC",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
}


class ExternalToolBundle(AbstractContextManager["ExternalToolBundle"]):
    """Own the lifecycle of configured MCP and Hugging Face Hub tools."""

    def __init__(self, config_path: str | Path | None):
        self.config_path = Path(config_path).resolve() if config_path else None
        self.tools: list[Tool] = []
        self._mcp_client: MCPClient | None = None

    def __enter__(self) -> "ExternalToolBundle":
        if self.config_path is None:
            return self

        config = _read_config(self.config_path)
        configured_servers = list(config.get("mcp_servers", []))
        adapter_kwargs: dict[str, Any] = {}
        connect_timeout = config.get("connect_timeout_seconds")
        if "docker_mcp" in config:
            docker_mcp = config["docker_mcp"]
            configured_servers.append(_docker_mcp_server(docker_mcp))
            connect_timeout = connect_timeout or docker_mcp.get(
                "connect_timeout_seconds"
            )
        if connect_timeout is not None:
            adapter_kwargs["connect_timeout"] = connect_timeout
        mcp_parameters = [
            _mcp_parameters(item) for item in configured_servers
        ]
        try:
            if mcp_parameters:
                self._mcp_client = MCPClient(
                    mcp_parameters,
                    adapter_kwargs=adapter_kwargs,
                    structured_output=True,
                )
                loaded_mcp_tools = self._mcp_client.get_tools()
                if "docker_mcp" in config and not loaded_mcp_tools:
                    profile = config["docker_mcp"]["profile"]
                    raise ValueError(
                        f"Docker MCP profile {profile!r} loaded no tools; "
                        "inspect Gateway image-pull and server-start logs"
                    )
                self.tools.extend(loaded_mcp_tools)

            for entry in config.get("hub_tools", []):
                if not entry.get("trust_remote_code", False):
                    raise ValueError(
                        "Hub tools execute repository code; each entry must set "
                        "trust_remote_code=true after its source/revision is audited"
                    )
                kwargs: dict[str, Any] = {
                    "trust_remote_code": True,
                    "token": os.getenv(entry.get("token_env", "HF_TOKEN")),
                }
                if entry.get("revision"):
                    kwargs["revision"] = entry["revision"]
                self.tools.append(load_tool(entry["repo_id"], **kwargs))

            allowlist = set(config.get("tool_allowlist", []))
            if allowlist:
                missing = allowlist - {tool.name for tool in self.tools}
                if missing:
                    raise ValueError(
                        f"tool_allowlist names were not loaded: {sorted(missing)}"
                    )
                self.tools = [tool for tool in self.tools if tool.name in allowlist]

            max_tools = config.get("max_tools", 12)
            if len(self.tools) > max_tools:
                raise ValueError(
                    f"External config loaded {len(self.tools)} tools, exceeding "
                    f"max_tools={max_tools}; use tool_allowlist"
                )
            _reject_duplicate_names(self.tools)
            return self
        except BaseException as error:
            try:
                self._disconnect_mcp()
            except BaseException as cleanup_error:
                error.add_note(f"MCP cleanup also failed: {cleanup_error}")
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            self._disconnect_mcp()
        except BaseException as cleanup_error:
            if exc_value is None:
                raise
            exc_value.add_note(f"MCP cleanup also failed: {cleanup_error}")

    def _disconnect_mcp(self) -> None:
        client = self._mcp_client
        self._mcp_client = None
        if client is not None:
            client.disconnect()


def _read_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("External tool config must be a JSON object")
    supported = {
        "docker_mcp",
        "mcp_servers",
        "hub_tools",
        "tool_allowlist",
        "max_tools",
        "pi_builtin_tools",
        "connect_timeout_seconds",
    }
    unexpected = set(data) - supported
    if unexpected:
        raise ValueError(f"Unsupported external tool config keys: {unexpected}")
    for field in ("mcp_servers", "hub_tools"):
        value = data.get(field, [])
        if not isinstance(value, list):
            raise ValueError(f"{field} must be a list")
        if not all(isinstance(item, dict) for item in value):
            raise ValueError(f"Every {field} entry must be a JSON object")
    allowlist = data.get("tool_allowlist", [])
    if not isinstance(allowlist, list) or not all(
        isinstance(name, str) and name for name in allowlist
    ):
        raise ValueError("tool_allowlist must be a list of non-empty strings")
    pi_builtin_tools = data.get("pi_builtin_tools", [])
    allowed_pi_builtin_tools = {"read", "bash", "grep", "find", "ls"}
    if not isinstance(pi_builtin_tools, list) or not all(
        isinstance(name, str) and name in allowed_pi_builtin_tools
        for name in pi_builtin_tools
    ):
        raise ValueError(
            "pi_builtin_tools may only contain read, bash, grep, find, and ls"
        )
    if len(set(pi_builtin_tools)) != len(pi_builtin_tools):
        raise ValueError("pi_builtin_tools must not contain duplicates")
    max_tools = data.get("max_tools", 12)
    if (
        isinstance(max_tools, bool)
        or not isinstance(max_tools, int)
        or max_tools < 1
    ):
        raise ValueError("max_tools must be a positive integer")
    connect_timeout = data.get("connect_timeout_seconds")
    if connect_timeout is not None and (
        isinstance(connect_timeout, bool)
        or not isinstance(connect_timeout, int)
        or connect_timeout < 1
    ):
        raise ValueError("connect_timeout_seconds must be a positive integer")
    if "docker_mcp" in data and data.get("mcp_servers"):
        raise ValueError(
            "docker_mcp cannot be combined with mcp_servers; "
            "add those servers to the Docker profile instead"
        )
    return data


def read_external_tool_config(path: str | Path) -> dict[str, Any]:
    """Read and validate the shared external-tool configuration."""

    return _read_config(Path(path).resolve())


def docker_mcp_server(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert a Docker MCP profile entry to a stdio server definition."""

    return _docker_mcp_server(entry)


def _docker_mcp_server(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError("docker_mcp must be a JSON object")
    supported = {
        "profile",
        "command",
        "connect_timeout_seconds",
        "env_passthrough",
    }
    unexpected = set(entry) - supported
    if unexpected:
        raise ValueError(f"Unsupported docker_mcp keys: {unexpected}")
    profile = entry.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("docker_mcp.profile must be a non-empty string")
    connect_timeout = entry.get("connect_timeout_seconds")
    if connect_timeout is not None and (
        isinstance(connect_timeout, bool)
        or not isinstance(connect_timeout, int)
        or connect_timeout < 1
    ):
        raise ValueError(
            "docker_mcp.connect_timeout_seconds must be a positive integer"
        )
    command = entry.get("command", "docker")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("docker_mcp.command must be a non-empty string")
    env_passthrough = entry.get("env_passthrough", [])
    if not isinstance(env_passthrough, list) or not all(
        isinstance(name, str) and name for name in env_passthrough
    ):
        raise ValueError(
            "docker_mcp.env_passthrough must be a list of non-empty strings"
        )
    return {
        "transport": "stdio",
        "command": command,
        "args": [
            "mcp",
            "gateway",
            "run",
            "--profile",
            profile,
            "--static",
        ],
        "env_passthrough": env_passthrough,
    }


def _mcp_parameters(entry: dict[str, Any]):
    transport = entry.get("transport", "streamable-http")
    if transport in {"streamable-http", "sse"}:
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("HTTP MCP server url must be a non-empty string")
        return {"url": url, "transport": transport}
    if transport != "stdio":
        raise ValueError(f"Unsupported MCP transport: {transport}")

    from mcp import StdioServerParameters

    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("stdio MCP command must be a non-empty string")
    args = entry.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("stdio MCP args must be a list of strings")
    env_passthrough = entry.get("env_passthrough", [])
    if not isinstance(env_passthrough, list) or not all(
        isinstance(name, str) and name for name in env_passthrough
    ):
        raise ValueError(
            "stdio MCP env_passthrough must be a list of non-empty strings"
        )
    env = {
        name: os.environ[name]
        for name in _MCP_SYSTEM_ENVIRONMENT
        if name in os.environ
    }
    for name in env_passthrough:
        if name not in os.environ:
            raise ValueError(f"Required MCP environment variable is missing: {name}")
        env[name] = os.environ[name]
    return StdioServerParameters(
        command=command,
        args=args,
        env=env,
    )


def _reject_duplicate_names(tools: list[Tool]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for tool in tools:
        if tool.name in seen:
            duplicates.add(tool.name)
        seen.add(tool.name)
    if duplicates:
        raise ValueError(f"Duplicate external tool names: {sorted(duplicates)}")
