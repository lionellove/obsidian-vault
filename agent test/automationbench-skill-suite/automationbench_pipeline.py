"""Generate, compile, and evaluate evaluator-informed skills on AutomationBench.

One Pi SDK call creates each source SKILL.md. The linear arm injects that source; the
graph arm injects the deterministic compiler output. Two control arms hold the source
fixed and vary authorship and format: skillgraph-schema asks the model to author the
graph as YAML, and skillgraph-schema-md renders that same YAML to Markdown with no
extra model call, so format is isolated from graph content. The active Task-to-Skill
prompt deliberately receives available tools and initial state but excludes evaluator
assertions. Results from this profile are still state-informed and must not be reported
as leakage-free task-conditioned benchmark results.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
AUTOMATIONBENCH_ROOT = REPO_ROOT / "AutomationBench"
GAIA_ROOT = REPO_ROOT / "gaia"
COMPILER = REPO_ROOT / "skillgraph-compiler" / "scripts" / "skillgraph.py"
PROMPT_FILE = ROOT / "prompts" / "generate_anthropic_skill.md"
SCHEMA_PROMPT_FILE = ROOT / "prompts" / "compile_skillgraph_schema.md"
TASK_SCHEMA_PROMPT_FILE = ROOT / "prompts" / "generate_task_skillgraph_schema.md"
DEFAULT_RUN_DIR = ROOT / "runs" / "automationbench-30-v1"
DOMAINS = ("sales", "marketing", "operations", "support", "finance", "hr")
ARMS = (
    "baseline",
    "skill",
    "agent-authored-skill",
    "skillgraph",
    "skillgraph-schema",
    "skillgraph-schema-md",
    "skillgraph-markdown",
    "task-skill-schema",
)
# The clean-room arm is supplied out of band for a fixed manifest. Fresh end-to-end
# runs cannot generate it, so callers must opt into it explicitly.
DEFAULT_ARMS = tuple(arm for arm in ARMS if arm != "agent-authored-skill")
NODE_LINE = re.compile(
    r"^(?P<prefix>\s*\d+\.\s*)\[(?P<type>[a-z]+)\](?P<rest>.*\{#(?P<id>[A-Za-z][A-Za-z0-9_-]*)\}\s*)$"
)
LOOP_SUFFIX = re.compile(r"\s*\{loop=(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s+max=(?P<max>\d+)\}\s*$")

sys.path.insert(0, str(AUTOMATIONBENCH_ROOT))
sys.path.insert(0, str(GAIA_ROOT))

from automationbench.domains import get_domain_dataset  # noqa: E402
from skillgraph_pipeline import (  # noqa: E402
    build_pi_generation_request,
    invoke_pi_generator,
    validate_skill_markdown as validate_legacy_skill_markdown,
)


@dataclass(frozen=True)
class Paths:
    run_dir: Path
    label: str = ""

    @property
    def manifest(self) -> Path:
        return self.run_dir / "manifest.json"

    def source_skill(self, task: dict[str, Any]) -> Path:
        return self.run_dir / "skills" / "source" / task["skill_name"] / "SKILL.md"

    def agent_authored_skill(self, task: dict[str, Any]) -> Path:
        """Clean-room agent-authored Markdown skill used as an authorship control."""
        return self.run_dir / "skills" / "agent-authored" / task["skill_name"] / "SKILL.md"

    def graph_skill(self, task: dict[str, Any]) -> Path:
        return self.run_dir / "skills" / "graph" / task["skill_name"] / "SKILL.md"

    def schema_skill(self, task: dict[str, Any]) -> Path:
        """Model-authored SkillGraph YAML for the skillgraph-schema control arm."""
        return self.run_dir / "skills" / "schema" / task["skill_name"] / "skillgraph.yaml"

    def schema_markdown(self, task: dict[str, Any]) -> Path:
        """Markdown rendering of the same YAML, isolating format from graph content."""
        return self.run_dir / "skills" / "schema" / task["skill_name"] / "skillgraph.md"

    def task_schema_skill(self, task: dict[str, Any]) -> Path:
        """Task-to-SkillGraph YAML for the task-skill-schema arm."""
        return self.run_dir / "skills" / "task-schema" / task["skill_name"] / "skillgraph.yaml"

    def model_markdown_skill(self, task: dict[str, Any]) -> Path:
        """Model-authored Markdown SkillGraph for the skillgraph-markdown arm."""
        return self.run_dir / "skills" / "model-markdown" / task["skill_name"] / "skillgraph.md"

    def normalized_skill(self, task: dict[str, Any]) -> Path:
        return self.run_dir / "skills" / "normalized" / task["skill_name"] / "SKILL.md"

    def generation_record(self, task: dict[str, Any]) -> Path:
        return self.run_dir / "generation" / f"{task['skill_name']}.json"

    def schema_record(self, task: dict[str, Any]) -> Path:
        return self.run_dir / "generation" / "schema" / f"{task['skill_name']}.json"

    def task_schema_record(self, task: dict[str, Any]) -> Path:
        return self.run_dir / "generation" / "task-schema" / f"{task['skill_name']}.json"

    def model_markdown_record(self, task: dict[str, Any]) -> Path:
        return self.run_dir / "generation" / "model-markdown" / f"{task['skill_name']}.json"

    def _scoped(self, *parts: str) -> Path:
        """Namespace derived artifacts by label so subset runs never clobber a full run."""
        base = self.run_dir / self.label if self.label else self.run_dir
        return base.joinpath(*parts)

    def instruction_map(self, arm: str) -> Path:
        return self._scoped("instructions", f"{arm}.json")

    def evaluation(self, arm: str) -> Path:
        return self._scoped("evaluation", f"{arm}.json")

    def evaluation_shard(self, arm: str, index: int) -> Path:
        return self._scoped("evaluation", "shards", arm, f"{index:03d}.json")

    def scores(self) -> Path:
        return self._scoped("scores.json")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_skill_markdown(
    markdown: str,
    *,
    expected_name: str,
    canonical: bool = False,
) -> dict[str, str]:
    """Validate canonical/legacy skills plus the Task-to-Skill source contract."""
    if canonical or "## Inputs and Authoritative Sources" not in markdown:
        return validate_legacy_skill_markdown(
            markdown,
            expected_name=expected_name,
            canonical=canonical,
        )

    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", markdown, re.S)
    if not match:
        raise ValueError("SKILL.md must start with YAML frontmatter")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict) or set(metadata) != {"name", "description"}:
        raise ValueError("SKILL.md frontmatter must contain exactly name and description")
    name = metadata.get("name")
    description = metadata.get("description")
    if name != expected_name:
        raise ValueError(f"SKILL.md name must be {expected_name!r}, got {name!r}")
    if not isinstance(name, str) or len(name) > 64 or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", name
    ):
        raise ValueError("SKILL.md name violates the Agent Skills naming rules")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("SKILL.md description must be non-empty")
    if len(description) > 1024:
        raise ValueError("SKILL.md description exceeds 1024 characters")
    body = markdown[match.end() :]
    if not re.search(r"^#\s+\S", body, re.M):
        raise ValueError("SKILL.md must contain a non-empty H1 title")

    section_matches = list(re.finditer(r"^##\s+(.+?)\s*$", markdown, re.M))
    section_names = [section.group(1) for section in section_matches]
    completion_heading = (
        "Completion Criteria" if "Completion Criteria" in section_names else "Completion Check"
    )
    required = [
        "Overview",
        "When to Use",
        "Do Not Use When",
        "Inputs and Authoritative Sources",
        "Required Tools",
        "Tool Limitations",
        "Core Rules",
        "Procedure",
        "Mutation Ordering",
        "Verification",
        "Failure Handling",
        completion_heading,
        "Output Requirements",
    ]
    positions = []
    for heading in required:
        if heading not in section_names:
            raise ValueError(f"SKILL.md is missing ## {heading}")
        index = section_names.index(heading)
        positions.append(index)
        content_start = section_matches[index].end()
        content_end = (
            section_matches[index + 1].start()
            if index + 1 < len(section_matches)
            else len(markdown)
        )
        if not markdown[content_start:content_end].strip():
            raise ValueError(f"SKILL.md section ## {heading} must not be empty")
    if positions != sorted(positions):
        raise ValueError("SKILL.md required sections are out of order")
    return {"name": name, "description": description.strip()}


def _parse_messages(value: Any) -> list[dict[str, str]]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise TypeError("Task prompt must be a message list")
    messages = []
    for message in value:
        if not isinstance(message, dict):
            raise TypeError("Task prompt messages must be objects")
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role in {"system", "user"} and content:
            messages.append({"role": role, "content": content})
    return messages


def _task_request(row: dict[str, Any]) -> str:
    user_parts = [m["content"] for m in _parse_messages(row["prompt"]) if m["role"] == "user"]
    if not user_parts:
        raise ValueError(f"Task {row['task']} has no public user request")
    return "\n\n".join(user_parts)


def _task_info(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("info", {})
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise TypeError("Task info must be a mapping or serialized mapping")
    return value


def _available_tools(info: dict[str, Any]) -> dict[str, Any]:
    """Describe the actual API-tool runtime plus benchmark operation hints."""
    return {
        "callable_runtime_tools": [
            {
                "name": "api_search",
                "purpose": (
                    "Search the API schema catalog for supported operations; "
                    "this does not search business records."
                ),
            },
            {
                "name": "api_fetch",
                "purpose": "Invoke a discovered API operation using its documented request schema.",
            },
            {
                "name": "base64_encode",
                "purpose": "Encode content only when a discovered API schema requires Base64.",
            },
        ],
        "discoverable_operation_hints": list(info.get("zapier_tools") or []),
    }


def make_skill_name(task_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task_name.lower()).strip("-")
    digest = hashlib.sha256(task_name.encode("utf-8")).hexdigest()[:8]
    return f"ab-{slug[:48].rstrip('-')}-{digest}"


def evenly_spaced_indices(length: int, count: int) -> list[int]:
    if count < 1 or count > length:
        raise ValueError(f"Cannot select {count} rows from {length}")
    if count == 1:
        return [0]
    return [round(i * (length - 1) / (count - 1)) for i in range(count)]


def select_tasks(
    paths: Paths,
    *,
    per_domain: int = 5,
    domains: Sequence[str] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    chosen_domains = tuple(domains) if domains else DOMAINS
    unknown = sorted(set(chosen_domains) - set(DOMAINS))
    if unknown:
        raise ValueError(f"Unknown domains: {', '.join(unknown)}")
    if paths.manifest.is_file() and not force:
        return filter_by_domain(read_manifest(paths), chosen_domains)

    selected: list[dict[str, Any]] = []
    for domain in chosen_domains:
        dataset = get_domain_dataset(domain)
        for index in evenly_spaced_indices(len(dataset), per_domain):
            row = dataset[index]
            info = _task_info(row)
            task_name = str(row["task"])
            selected.append(
                {
                    "task_id": task_name,
                    "domain": domain,
                    "domain_index": index,
                    "skill_name": make_skill_name(task_name),
                    "task_request": _task_request(row),
                    "available_tools": _available_tools(info),
                    "initial_state": info.get("initial_state", {}),
                    "assertions": info.get("assertions", []),
                }
            )

    payload = {
        "schema_version": 1,
        "benchmark": "AutomationBench-public",
        "selection": {
            "strategy": "evenly-spaced-within-each-domain",
            "domains": list(chosen_domains),
            "per_domain": per_domain,
            "total": len(selected),
        },
        "generation_visibility": [
            "domain",
            "task_id",
            "public user request",
            "available tools",
            "initial state",
            "optional existing skill",
        ],
        "generation_excludes": ["assertions", "answer", "end_state", "previous run traces"],
        "tasks": selected,
    }
    atomic_write(paths.manifest, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"Selected {len(selected)} tasks -> {paths.manifest}")
    return selected


def filter_by_domain(
    tasks: Sequence[dict[str, Any]], domains: Sequence[str] | None
) -> list[dict[str, Any]]:
    """Restrict manifest tasks to the requested domains, preserving manifest order.

    An empty result is an error: a silently empty task set would otherwise run the
    benchmark against nothing and report a meaningless pass rate.
    """
    if not domains:
        return list(tasks)
    unknown = sorted(set(domains) - set(DOMAINS))
    if unknown:
        raise ValueError(f"Unknown domains: {', '.join(unknown)}")
    wanted = set(domains)
    filtered = [task for task in tasks if str(task.get("domain")) in wanted]
    if not filtered:
        raise ValueError(
            f"No manifest tasks match domains: {', '.join(sorted(wanted))}"
        )
    return filtered


def filter_by_task_id(
    tasks: Sequence[dict[str, Any]], task_ids: Sequence[str] | None
) -> list[dict[str, Any]]:
    """Select manifest tasks by exact ID, preserving the caller's requested order."""
    if not task_ids:
        return list(tasks)
    requested = list(task_ids)
    duplicates = sorted({task_id for task_id in requested if requested.count(task_id) > 1})
    if duplicates:
        raise ValueError(f"Task IDs must be unique: {', '.join(duplicates)}")
    by_id = {str(task["task_id"]): task for task in tasks}
    missing = [task_id for task_id in requested if task_id not in by_id]
    if missing:
        raise ValueError(
            "Requested task IDs are not in the manifest: " + ", ".join(missing)
        )
    return [by_id[task_id] for task_id in requested]


def read_manifest(paths: Paths) -> list[dict[str, Any]]:
    if not paths.manifest.is_file():
        raise FileNotFoundError(f"Manifest missing; run select first: {paths.manifest}")
    payload = json.loads(paths.manifest.read_text(encoding="utf-8"))
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Manifest tasks must be a list")
    return tasks


def _generation_context(task: dict[str, Any]) -> dict[str, Any]:
    required = ("available_tools", "initial_state", "assertions")
    if all(key in task for key in required):
        return {key: task[key] for key in required}

    dataset = get_domain_dataset(str(task["domain"]))
    index = int(task["domain_index"])
    row = dataset[index]
    if str(row["task"]) != str(task["task_id"]):
        raise ValueError(
            f"Manifest task {task['task_id']!r} no longer matches "
            f"{task['domain']} dataset index {index}"
        )
    info = _task_info(row)
    return {
        "available_tools": _available_tools(info),
        "initial_state": info.get("initial_state", {}),
        "assertions": info.get("assertions", []),
    }


def _prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _generation_record_is_cacheable(
    record: dict[str, Any], *, generation_input_sha256: str, model_id: str
) -> bool:
    return (
        record.get("status") == "generated"
        and record.get("generation_input_sha256") == generation_input_sha256
        and record.get("model_id") == model_id
    )


def build_generation_prompt(
    task: dict[str, Any], *, existing_skill: str = ""
) -> str:
    template = PROMPT_FILE.read_text(encoding="utf-8")
    context = _generation_context(task)
    replacements = {
        "task_name": task["skill_name"],
        "task_prompt": task["task_request"],
        "available_tools": context["available_tools"],
        "initial_state": context["initial_state"],
        "existing_skill_or_empty": existing_skill or "(none)",
    }
    for key, value in replacements.items():
        template = template.replace("{{" + key + "}}", _prompt_value(value))
    if re.search(r"{{[A-Za-z_]+}}", template):
        raise RuntimeError("Generation prompt contains an unresolved placeholder")
    return template


def _parse_edge_line(line: str) -> tuple[str | None, str, str | None, int | None] | None:
    stripped = line.lstrip()
    if not stripped.startswith("-") or "->" not in stripped:
        return None
    body = stripped[1:].strip()
    loop_name = None
    loop_max = None
    loop_match = LOOP_SUFFIX.search(body)
    if loop_match:
        loop_name = loop_match.group("name")
        loop_max = int(loop_match.group("max"))
        body = body[: loop_match.start()].strip()
    while body.startswith("->"):
        body = body[2:].strip()
    if not body:
        return None
    if "->" in body:
        outcome, target = (part.strip() for part in body.rsplit("->", 1))
        outcome = outcome or None
    else:
        outcome, target = None, body
    target = target.strip(" `")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", target):
        return None
    return outcome, target, loop_name, loop_max


def normalize_workflow_markdown(markdown: str) -> str:
    """Repair common model-emitted graph syntax without adding task knowledge."""
    lines = markdown.splitlines()
    workflow_headings = {"## Workflow", "## Procedure", "## Steps", "## Process"}
    workflow_start = next(
        (index for index, line in enumerate(lines) if line.strip() in workflow_headings), None
    )
    if workflow_start is None:
        raise ValueError("SKILL.md is missing a Workflow or Procedure section")
    workflow_end = next(
        (
            index
            for index in range(workflow_start + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )

    nodes = []
    for index in range(workflow_start + 1, workflow_end):
        match = NODE_LINE.match(lines[index])
        if match:
            nodes.append(
                {
                    "line": index,
                    "id": match.group("id"),
                    "type": match.group("type"),
                    "match": match,
                }
            )
    if not nodes:
        raise ValueError("Workflow contains no parseable nodes")

    id_to_order = {node["id"]: order for order, node in enumerate(nodes)}
    id_to_type = {node["id"]: node["type"] for node in nodes}
    fail_id = next((node["id"] for node in nodes if node["type"] == "fail"), "fail")
    finish_id = next((node["id"] for node in nodes if node["type"] == "finish"), "finish")

    remove_lines: set[int] = set()
    replacement_lines: dict[int, str] = {}
    edge_counts: dict[str, int] = {}
    for node_order, node in enumerate(nodes):
        block_end = nodes[node_order + 1]["line"] if node_order + 1 < len(nodes) else workflow_end
        for line_index in range(node["line"] + 1, block_end):
            parsed = _parse_edge_line(lines[line_index])
            if parsed is None:
                continue
            if node["type"] in {"finish", "fail"}:
                remove_lines.add(line_index)
                continue
            outcome, target, loop_name, loop_max = parsed
            if target not in id_to_order:
                if target == "fail":
                    target = fail_id
                elif target == "finish":
                    target = finish_id
                elif node_order + 1 < len(nodes):
                    target = nodes[node_order + 1]["id"]
                else:
                    target = finish_id
            is_back_edge = (
                target in id_to_order
                and id_to_order[target] <= node_order
                and id_to_type.get(target) not in {"finish", "fail"}
            )
            if is_back_edge and (not loop_name or not loop_max):
                loop_name = f"retry_{node['id']}"
                loop_max = 1
            elif not is_back_edge:
                loop_name = None
                loop_max = None
            indent = lines[line_index][: len(lines[line_index]) - len(lines[line_index].lstrip())]
            label = f"{outcome} " if outcome else ""
            loop = f" {{loop={loop_name} max={loop_max}}}" if loop_name else ""
            replacement_lines[line_index] = f"{indent}- {label}-> {target}{loop}"
            edge_counts[node["id"]] = edge_counts.get(node["id"], 0) + 1

    for node in nodes:
        if node["type"] == "action" and edge_counts.get(node["id"], 0) > 1:
            match = node["match"]
            replacement_lines[node["line"]] = (
                f"{match.group('prefix')}[decision]{match.group('rest')}"
            )

    normalized = [
        "## Completion Check"
        if line.strip() == "## Completion Criteria"
        else replacement_lines.get(index, line)
        for index, line in enumerate(lines)
        if index not in remove_lines
    ]
    return "\n".join(normalized).rstrip() + "\n"


def _load_compiler_module():
    module_name = "automationbench_skillgraph_compiler"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, COMPILER)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Skill Graph compiler: {COMPILER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def repair_graph(graph, compiler):
    """Deterministically make a parsed generated graph strict-valid."""

    def unique_id(preferred: str) -> str:
        ids = {node.id for node in graph.nodes}
        if preferred not in ids:
            return preferred
        index = 2
        while f"{preferred}_{index}" in ids:
            index += 1
        return f"{preferred}_{index}"

    if not any(node.type == "finish" for node in graph.nodes):
        graph.nodes.append(
            compiler.Node(unique_id("finish"), "finish", "Finish", "Return success.")
        )
    if not any(node.type == "fail" for node in graph.nodes):
        graph.nodes.append(
            compiler.Node(unique_id("fail"), "fail", "Stop safely", "Return the blocker.")
        )
    for order, node in enumerate(graph.nodes):
        node.order = order
    ids = {node.id for node in graph.nodes}
    order = {node.id: node.order for node in graph.nodes}
    node_by_id = {node.id: node for node in graph.nodes}
    finish_id = next(node.id for node in graph.nodes if node.type == "finish")
    fail_id = next(node.id for node in graph.nodes if node.type == "fail")

    def fallback_target(source: str, target: str) -> str:
        lowered = target.lower()
        if "finish" in lowered or "success" in lowered:
            return finish_id
        if "fail" in lowered or "stop" in lowered:
            return fail_id
        source_order = order.get(source, -1)
        if "recover" in lowered or "retry" in lowered:
            recovery = next(
                (
                    node.id
                    for node in graph.nodes
                    if node.type == "recover" and node.order > source_order
                ),
                None,
            )
            if recovery:
                return recovery
        following = next(
            (
                node.id
                for node in graph.nodes
                if node.order > source_order and node.type not in compiler.TERMINAL_TYPES
            ),
            None,
        )
        return following or fail_id

    repaired_edges = []
    seen_edges = set()
    for edge in graph.edges:
        if edge.source not in ids or node_by_id[edge.source].type in compiler.TERMINAL_TYPES:
            continue
        target = edge.target if edge.target in ids else fallback_target(edge.source, edge.target)
        key = (edge.source, target, edge.outcome)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        repaired_edges.append(compiler.Edge(edge.source, target, edge.outcome, edge.loop, edge.max))
    graph.edges = repaired_edges

    def outgoing() -> dict[str, list[Any]]:
        result = {node.id: [] for node in graph.nodes}
        for edge in graph.edges:
            result.setdefault(edge.source, []).append(edge)
        return result

    def reachable() -> set[str]:
        adjacency = outgoing()
        seen = set()
        pending = [graph.entry]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(edge.target for edge in adjacency.get(current, []))
        return seen

    # Give every non-terminal an exit before connecting orphaned nodes.
    current_outgoing = outgoing()
    for index, node in enumerate(graph.nodes):
        if node.type in compiler.TERMINAL_TYPES or current_outgoing[node.id]:
            continue
        target = next(
            (
                candidate.id
                for candidate in graph.nodes[index + 1 :]
                if candidate.type not in compiler.TERMINAL_TYPES
            ),
            finish_id,
        )
        graph.edges.append(compiler.Edge(node.id, target))

    # Connect every authored orphan from the closest preceding reachable node.
    while True:
        reached = reachable()
        orphan = next((node for node in graph.nodes if node.id not in reached), None)
        if orphan is None:
            break
        candidates = [
            node
            for node in graph.nodes
            if node.id in reached
            and node.type not in compiler.TERMINAL_TYPES
            and node.order < orphan.order
        ]
        source = (candidates[-1] if candidates else node_by_id[graph.entry]).id
        graph.edges.append(compiler.Edge(source, orphan.id, f"route_{orphan.id}"))

    # Ensure all nodes can terminate and that at least one reachable route succeeds.
    reverse: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        reverse[edge.target].append(edge.source)
    can_terminate = set()
    pending = [node.id for node in graph.nodes if node.type in compiler.TERMINAL_TYPES]
    while pending:
        current = pending.pop()
        if current in can_terminate:
            continue
        can_terminate.add(current)
        pending.extend(reverse.get(current, []))
    for node in graph.nodes:
        if node.type not in compiler.TERMINAL_TYPES and node.id not in can_terminate:
            graph.edges.append(compiler.Edge(node.id, fail_id, "blocked"))
    if finish_id not in reachable():
        source = next(
            node.id
            for node in reversed(graph.nodes)
            if node.id in reachable() and node.type not in compiler.TERMINAL_TYPES
        )
        graph.edges.append(compiler.Edge(source, finish_id, "complete"))

    # Canonicalize branch labels, node types, and loop metadata after repairs.
    grouped = outgoing()
    for node in graph.nodes:
        edges = grouped[node.id]
        if node.type in compiler.TERMINAL_TYPES:
            continue
        if len(edges) > 1:
            node.type = "decision"
            used = set()
            for index, edge in enumerate(edges, start=1):
                label = re.sub(r"[^a-z0-9_]+", "_", (edge.outcome or "").lower()).strip("_")
                if not label or label in used:
                    label = f"path_{index}"
                    while label in used:
                        index += 1
                        label = f"path_{index}"
                edge.outcome = label
                used.add(label)
        elif len(edges) == 1:
            if node.type == "decision":
                node.type = "action"
            edges[0].outcome = None

    order = {node.id: node.order for node in graph.nodes}
    for edge in graph.edges:
        backward = order[edge.target] <= order[edge.source] and edge.target not in {
            "finish",
            "fail",
        }
        if backward:
            edge.loop = edge.loop or f"retry_{edge.source}"
            edge.max = edge.max if edge.max and edge.max > 0 else 1
        else:
            edge.loop = None
            edge.max = None
    return graph


def generate_one(task: dict[str, Any], paths: Paths, *, force: bool, timeout_seconds: int) -> dict[str, Any]:
    source = paths.source_skill(task)
    record_path = paths.generation_record(task)
    base_prompt = build_generation_prompt(task)
    generation_input_sha256 = sha256_text(base_prompt)
    existing_skill = source.read_text(encoding="utf-8") if source.is_file() and force else ""
    prompt = build_generation_prompt(task, existing_skill=existing_skill)
    prompt_sha256 = sha256_text(prompt)
    model_id = os.getenv("MODEL_ID")
    if not model_id:
        raise RuntimeError("MODEL_ID is missing")

    if source.is_file() and record_path.is_file() and not force:
        previous = json.loads(record_path.read_text(encoding="utf-8"))
        validate_skill_markdown(source.read_text(encoding="utf-8"), expected_name=task["skill_name"])
        if _generation_record_is_cacheable(
            previous,
            generation_input_sha256=generation_input_sha256,
            model_id=model_id,
        ):
            return {"task_id": task["task_id"], "status": "skipped", "path": str(source)}

    request = build_pi_generation_request(prompt)
    started = time.perf_counter()
    response, stderr = invoke_pi_generator(request, timeout_seconds=timeout_seconds)
    duration = round(time.perf_counter() - started, 3)
    status = "failed"
    validation_error = None
    try:
        if response.get("error"):
            raise RuntimeError(str(response["error"]))
        markdown = response.get("skillMd")
        if not isinstance(markdown, str):
            raise ValueError("Pi generator did not return a complete skillMd block")
        validate_skill_markdown(markdown, expected_name=task["skill_name"])
        atomic_write(source, markdown)
        status = "generated"
    except Exception as exc:
        validation_error = f"{type(exc).__name__}: {exc}"

    record = {
        "schema_version": 1,
        "task_id": task["task_id"],
        "skill_name": task["skill_name"],
        "status": status,
        "duration_seconds": duration,
        "model_id": request["model"]["id"],
        "prompt_sha256": prompt_sha256,
        "generation_input_sha256": generation_input_sha256,
        "uses_initial_state": True,
        "uses_assertions": False,
        "token_counts": response.get("tokenCounts"),
        "attempts": response.get("attempts"),
        "error": response.get("error"),
        "validation_error": validation_error,
        "runner_stderr": stderr[-12000:],
        "raw_text": response.get("text"),
    }
    atomic_write(record_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    if status == "failed":
        raise RuntimeError(f"{task['task_id']}: {validation_error}")
    return {"task_id": task["task_id"], "status": status, "path": str(source)}


def generate_all(tasks: Sequence[dict[str, Any]], paths: Paths, *, workers: int, force: bool, timeout_seconds: int) -> None:
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(generate_one, task, paths, force=force, timeout_seconds=timeout_seconds): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                print(f"[{result['status']}] {task['task_id']}")
            except Exception as exc:
                failures.append(str(exc))
                print(f"[failed] {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(f"{len(failures)} skill generations failed; re-run to resume")


SCHEMA_TRANSPORT_FOOTER = """

---

# Transport

Wrap the complete YAML in `<skill_md>` and `</skill_md>` markers and emit no text outside
them. The markers are transport delimiters only; they are stripped before the file is saved
and are not part of the SkillGraph.
"""

MARKDOWN_TRANSPORT_FOOTER = """

---

# Transport

Wrap the complete Markdown SkillGraph in `<skill_md>` and `</skill_md>` markers and emit
no text outside them. The markers are transport delimiters only; they are stripped before
the file is saved and are not part of the SkillGraph.
"""


def build_schema_prompt(source_markdown: str) -> str:
    """Render the model-as-compiler prompt for the skillgraph-schema control arm."""
    template = SCHEMA_PROMPT_FILE.read_text(encoding="utf-8")
    if "{{SKILL_CONTENT}}" not in template:
        raise RuntimeError("Schema prompt is missing the {{SKILL_CONTENT}} placeholder")
    prompt = template.replace("{{SKILL_CONTENT}}", source_markdown) + SCHEMA_TRANSPORT_FOOTER
    if re.search(r"{{[A-Za-z_]+}}", prompt):
        raise RuntimeError("Schema prompt contains an unresolved placeholder")
    return prompt


def build_markdown_prompt(source_markdown: str) -> str:
    """Render the model-authored Markdown SkillGraph prompt from a source skill."""
    template = SCHEMA_PROMPT_FILE.read_text(encoding="utf-8")
    if "{{SKILL_CONTENT}}" not in template:
        raise RuntimeError("Markdown prompt is missing the {{SKILL_CONTENT}} placeholder")
    prompt = template.replace("{{SKILL_CONTENT}}", source_markdown) + MARKDOWN_TRANSPORT_FOOTER
    if re.search(r"{{[A-Za-z_]+}}", prompt):
        raise RuntimeError("Markdown prompt contains an unresolved placeholder")
    return prompt


def build_task_schema_prompt(task: dict[str, Any]) -> str:
    """Render the task-to-SkillGraph prompt without an intermediate SKILL.md."""
    template = TASK_SCHEMA_PROMPT_FILE.read_text(encoding="utf-8")
    if "{{TASK_DESCRIPTION}}" not in template:
        raise RuntimeError("Task schema prompt is missing the {{TASK_DESCRIPTION}} placeholder")
    # Keep the supplied task-to-schema prompt intact, but add the same strict
    # transport contract used by the legacy SKILL.md-to-schema arm.  This makes
    # the Pi response boundary unambiguous without changing the task prompt's
    # generation instructions.
    prompt = template.replace("{{TASK_DESCRIPTION}}", str(task["task_request"])) + SCHEMA_TRANSPORT_FOOTER
    if re.search(r"{{[A-Za-z_]+}}", prompt):
        raise RuntimeError("Task schema prompt contains an unresolved placeholder")
    return prompt


def validate_schema_yaml(text: str) -> dict[str, Any]:
    """Validate the model-authored SkillGraph against the schema's structural contract.

    This arm has no deterministic compiler, so the graph is checked but never repaired.
    A violation is a real result about unaided authoring and must surface, not be patched.
    """
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"SkillGraph YAML is not parseable: {exc}") from exc
    if not isinstance(payload, dict) or "skillgraph" not in payload:
        raise ValueError("SkillGraph YAML must contain a top-level skillgraph mapping")
    graph = payload["skillgraph"]
    if not isinstance(graph, dict):
        raise ValueError("skillgraph must be a mapping")

    nodes = graph.get("nodes")
    edges = graph.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("skillgraph.nodes must be a non-empty list")
    if not isinstance(edges, list):
        raise ValueError("skillgraph.edges must be a list")

    ids: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("every node must be a mapping")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("every node needs a non-empty id")
        if node.get("tag") not in {"start", "operation", "verification", "end"}:
            raise ValueError(f"node {node_id!r} has an invalid tag {node.get('tag')!r}")
        ids.append(node_id)
    duplicates = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate node ids: {', '.join(duplicates)}")

    known = set(ids)
    entry = graph.get("entry")
    if entry not in known:
        raise ValueError(f"entry {entry!r} is not a declared node")
    terminals = {node["id"] for node in nodes if node.get("tag") == "end"}
    if not terminals:
        raise ValueError("skillgraph needs at least one end node")

    outgoing: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("every edge must be a mapping")
        source, target = edge.get("source"), edge.get("target")
        if source not in known:
            raise ValueError(f"edge source {source!r} is not a declared node")
        if target not in known:
            raise ValueError(f"edge target {target!r} is not a declared node")
        if edge.get("tag") not in {"sequence", "conditional", "retry", "fallback"}:
            raise ValueError(f"edge {source}->{target} has an invalid tag {edge.get('tag')!r}")
        maximum = edge.get("max_retry")
        if maximum is not None and (not isinstance(maximum, int) or maximum < 1):
            raise ValueError(f"edge {source}->{target} has a non-positive max_retry")
        outgoing.add(str(source))
    leaking = sorted(terminals & outgoing)
    if leaking:
        raise ValueError(f"end nodes must have no outgoing edges: {', '.join(leaking)}")

    reachable = {entry}
    frontier = [entry]
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge["source"]), []).append(str(edge["target"]))
    while frontier:
        for target in adjacency.get(frontier.pop(), []):
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    if not terminals & reachable:
        raise ValueError("no end node is reachable from entry")
    unreachable = sorted(known - reachable)
    if unreachable:
        raise ValueError(f"unreachable nodes: {', '.join(unreachable)}")
    return {"nodes": len(nodes), "edges": len(edges), "entry": str(entry)}


def validate_skillgraph_markdown(text: str) -> dict[str, Any]:
    """Validate the fixed Markdown SkillGraph format emitted by the model prompt."""
    compiler = _load_compiler_module()
    normalized = re.sub(
        r"(?m)^(\*\*Type:\*\*\s+)(operation|verification|end)\s*$",
        lambda match: match.group(1)
        + {"operation": "action", "verification": "verify", "end": "finish"}[match.group(2)],
        text,
    )
    try:
        graph = compiler.parse_markdown(normalized)
    except Exception as exc:
        raise ValueError(f"SkillGraph Markdown is not parseable: {exc}") from exc
    issues = [issue for issue in compiler.validate(graph) if issue.level == "error"]
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise ValueError(f"SkillGraph Markdown is invalid: {details}")
    return {"nodes": len(graph.nodes), "edges": len(graph.edges), "entry": graph.entry}


def _generate_model_artifact_one(
    task: dict[str, Any],
    *,
    arm: str,
    prompt: str,
    output: Path,
    record_path: Path,
    source_sha256: str | None,
    validator: Any | None,
    force: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Generate, optionally validate, and cache one model-authored graph artifact."""
    prompt_sha256 = sha256_text(prompt)
    model_id = os.getenv("MODEL_ID")
    if not model_id:
        raise RuntimeError("MODEL_ID is missing")

    if output.is_file() and record_path.is_file() and not force:
        previous = json.loads(record_path.read_text(encoding="utf-8"))
        if (
            previous.get("status") == "compiled"
            and previous.get("prompt_sha256") == prompt_sha256
            and previous.get("model_id") == model_id
        ):
            if validator is not None:
                validator(output.read_text(encoding="utf-8"))
            return {"task_id": task["task_id"], "status": "skipped", "path": str(output)}

    request = build_pi_generation_request(prompt)
    started = time.perf_counter()
    response, stderr = invoke_pi_generator(request, timeout_seconds=timeout_seconds)
    duration = round(time.perf_counter() - started, 3)
    status = "failed"
    validation_error = None
    stats: dict[str, Any] | None = None
    try:
        if response.get("error"):
            raise RuntimeError(str(response["error"]))
        text = response.get("skillMd")
        # The shared generator rejects an otherwise complete YAML response when
        # a model omits only the closing transport marker. Schema validation can
        # still make the final accept/reject decision on the raw response.
        if not isinstance(text, str):
            text = response.get("text")
        if not isinstance(text, str):
            raise ValueError("Pi generator did not return a complete skillMd block")
        artifact = _strip_yaml_fence(text)
        if validator is not None:
            stats = validator(artifact)
        atomic_write(output, artifact)
        status = "compiled"
    except Exception as exc:
        validation_error = f"{type(exc).__name__}: {exc}"

    record = {
        "schema_version": 1,
        "task_id": task["task_id"],
        "skill_name": task["skill_name"],
        "arm": arm,
        "status": status,
        "duration_seconds": duration,
        "model_id": request["model"]["id"],
        "prompt_sha256": prompt_sha256,
        "source_sha256": source_sha256,
        "graph_stats": stats,
        "token_counts": response.get("tokenCounts"),
        "attempts": response.get("attempts"),
        "error": response.get("error"),
        "validation_error": validation_error,
        "runner_stderr": stderr[-12000:],
        "raw_text": response.get("text"),
    }
    atomic_write(record_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    if status == "failed":
        raise RuntimeError(f"{task['task_id']}: {validation_error}")
    return {"task_id": task["task_id"], "status": status, "path": str(output)}


def compile_schema_one(
    task: dict[str, Any], paths: Paths, *, force: bool, timeout_seconds: int
) -> dict[str, Any]:
    """Ask the model to author a SkillGraph from the generated source skill."""
    source = paths.source_skill(task)
    if not source.is_file():
        raise FileNotFoundError(source)
    source_markdown = source.read_text(encoding="utf-8")
    return _generate_model_artifact_one(
        task,
        arm="skillgraph-schema",
        prompt=build_schema_prompt(source_markdown),
        output=paths.schema_skill(task),
        record_path=paths.schema_record(task),
        source_sha256=sha256_text(source_markdown),
        validator=validate_schema_yaml,
        force=force,
        timeout_seconds=timeout_seconds,
    )


def generate_task_schema_one(
    task: dict[str, Any], paths: Paths, *, force: bool, timeout_seconds: int
) -> dict[str, Any]:
    """Author a SkillGraph directly from the public task description."""
    return _generate_model_artifact_one(
        task,
        arm="task-skill-schema",
        prompt=build_task_schema_prompt(task),
        output=paths.task_schema_skill(task),
        record_path=paths.task_schema_record(task),
        source_sha256=None,
        validator=validate_schema_yaml,
        force=force,
        timeout_seconds=timeout_seconds,
    )


def generate_markdown_one(
    task: dict[str, Any], paths: Paths, *, force: bool, timeout_seconds: int
) -> dict[str, Any]:
    """Author a Markdown SkillGraph directly from a source SKILL.md.

    Markdown graph verification intentionally happens in a separate future stage;
    this generation arm preserves the model artifact without parser validation.
    """
    source = paths.source_skill(task)
    if not source.is_file():
        raise FileNotFoundError(source)
    source_markdown = source.read_text(encoding="utf-8")
    return _generate_model_artifact_one(
        task,
        arm="skillgraph-markdown",
        prompt=build_markdown_prompt(source_markdown),
        output=paths.model_markdown_skill(task),
        record_path=paths.model_markdown_record(task),
        source_sha256=sha256_text(source_markdown),
        validator=None,
        force=force,
        timeout_seconds=timeout_seconds,
    )


def _strip_yaml_fence(text: str) -> str:
    """Extract YAML from the generator's optional transport wrapper/fence."""
    stripped = text.strip()
    transport = re.match(r"\A<skill_md>\s*(.*?)\s*</skill_md>\s*\Z", stripped, re.S)
    if transport:
        stripped = transport.group(1).strip()
    else:
        # The model can produce complete YAML while omitting one transport
        # marker. Treat the marker as formatting and let YAML validation decide
        # whether the remaining payload is a valid SkillGraph.
        stripped = re.sub(r"\A<skill_md>\s*", "", stripped)
        stripped = re.sub(r"\s*</skill_md>\s*\Z", "", stripped)
    fence = re.match(r"\A```[A-Za-z]*\s*\n(.*?)\n```\s*\Z", stripped, re.S)
    if fence:
        stripped = fence.group(1)
    else:
        # Some model responses open a Markdown fence but omit its closing line.
        # The transport wrapper has already isolated the payload, so the opening
        # fence is formatting only and must not be passed to the YAML parser.
        stripped = re.sub(r"\A```[A-Za-z]*\s*\n", "", stripped)
    return stripped.strip() + "\n"


def compile_schema_all(
    tasks: Sequence[dict[str, Any]], paths: Paths, *, workers: int, force: bool, timeout_seconds: int
) -> None:
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                compile_schema_one, task, paths, force=force, timeout_seconds=timeout_seconds
            ): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                print(f"[schema {result['status']}] {task['task_id']}")
            except Exception as exc:
                failures.append(str(exc))
                print(f"[schema failed] {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(f"{len(failures)} schema compilations failed; re-run to resume")


def generate_task_schema_all(
    tasks: Sequence[dict[str, Any]], paths: Paths, *, workers: int, force: bool, timeout_seconds: int
) -> None:
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                generate_task_schema_one, task, paths, force=force, timeout_seconds=timeout_seconds
            ): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                print(f"[task schema {result['status']}] {task['task_id']}")
            except Exception as exc:
                failures.append(str(exc))
                print(f"[task schema failed] {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(f"{len(failures)} task schema generations failed; re-run to resume")


def generate_markdown_all(
    tasks: Sequence[dict[str, Any]], paths: Paths, *, workers: int, force: bool, timeout_seconds: int
) -> None:
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(generate_markdown_one, task, paths, force=force, timeout_seconds=timeout_seconds): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                print(f"[markdown {result['status']}] {task['task_id']}")
            except Exception as exc:
                failures.append(str(exc))
                print(f"[markdown failed] {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(f"{len(failures)} Markdown SkillGraph generations failed; re-run to resume")


def _load_renderer():
    """Load the schema-to-Markdown renderer so both arms share one conversion."""
    path = ROOT / "scripts" / "render_schema_markdown.py"
    spec = importlib.util.spec_from_file_location("render_schema_markdown", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load the schema renderer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_schema_markdown_all(
    tasks: Sequence[dict[str, Any]], paths: Paths, *, force: bool
) -> None:
    """Render each schema YAML to Markdown for the skillgraph-schema-md arm.

    Deterministic and model-free: the Markdown is a pure function of the YAML, so this
    arm differs from skillgraph-schema only in serialization format.
    """
    renderer = _load_renderer()
    failures = []
    for task in tasks:
        source = paths.schema_skill(task)
        output = paths.schema_markdown(task)
        try:
            if not source.is_file():
                raise FileNotFoundError(source)
            markdown = renderer.render_markdown(renderer.load_graph(source))
            if force or not output.is_file() or output.read_text(encoding="utf-8") != markdown:
                atomic_write(output, markdown)
            print(f"[rendered] {task['task_id']}")
        except Exception as exc:
            failures.append(f"{task['task_id']}: {exc}")
            print(f"[render failed] {task['task_id']}: {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(f"{len(failures)} schema renderings failed")


def compile_all(tasks: Sequence[dict[str, Any]], paths: Paths, *, force: bool) -> None:
    failures = []
    compiler = _load_compiler_module()
    for task in tasks:
        source = paths.source_skill(task)
        normalized_path = paths.normalized_skill(task)
        output = paths.graph_skill(task)
        try:
            if not source.is_file():
                raise FileNotFoundError(source)
            normalized = normalize_workflow_markdown(source.read_text(encoding="utf-8"))
            validate_skill_markdown(normalized, expected_name=task["skill_name"])
            if not normalized_path.is_file() or normalized_path.read_text(encoding="utf-8") != normalized:
                atomic_write(normalized_path, normalized)
            output.parent.mkdir(parents=True, exist_ok=True)
            if (
                output.is_file()
                and not force
                and output.stat().st_mtime_ns
                >= max(
                    source.stat().st_mtime_ns,
                    normalized_path.stat().st_mtime_ns,
                    Path(__file__).stat().st_mtime_ns,
                    COMPILER.stat().st_mtime_ns,
                )
            ):
                graph = compiler.parse_markdown(output.read_text(encoding="utf-8"))
            else:
                graph = repair_graph(compiler.parse_markdown(normalized), compiler)
                issues = compiler.validate(graph)
                if issues:
                    details = "\n".join(
                        f"[{issue.level} {issue.code}] {issue.message}" for issue in issues
                    )
                    raise RuntimeError(details)
                atomic_write(output, compiler.render(graph))
            validate_skill_markdown(output.read_text(encoding="utf-8"), expected_name=task["skill_name"], canonical=True)
            print(f"[compiled] {task['task_id']}")
        except Exception as exc:
            failures.append(f"{task['task_id']}: {exc}")
            print(f"[failed] {task['task_id']}: {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(f"{len(failures)} compilations failed")


def build_instruction_maps(
    tasks: Sequence[dict[str, Any]], paths: Paths, arms: Sequence[str]
) -> None:
    arm_sources = (
        ("skill", paths.source_skill),
        ("agent-authored-skill", paths.agent_authored_skill),
        ("skillgraph", paths.graph_skill),
        ("skillgraph-schema", paths.schema_skill),
        ("skillgraph-schema-md", paths.schema_markdown),
        ("skillgraph-markdown", paths.model_markdown_skill),
        ("task-skill-schema", paths.task_schema_skill),
    )
    for arm, path_getter in arm_sources:
        if arm not in arms:
            continue
        mapping = {}
        for task in tasks:
            path = path_getter(task)
            if not path.is_file():
                raise FileNotFoundError(path)
            content = path.read_text(encoding="utf-8")
            if arm == "agent-authored-skill":
                validate_skill_markdown(content, expected_name=task["skill_name"])
            mapping[task["task_id"]] = content
        atomic_write(paths.instruction_map(arm), json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def _python_executable() -> Path:
    preferred = AUTOMATIONBENCH_ROOT / ".venv" / "Scripts" / "python.exe"
    if preferred.is_file():
        return preferred
    return Path(sys.executable)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    suffixes = {".py", ".jsonc", ".tsv", ".toml"}
    for path in sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in suffixes
            and "__pycache__" not in path.parts
        ),
        key=lambda path: path.as_posix(),
    ):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def experiment_config(
    arm: str,
    tasks: Sequence[dict[str, Any]],
    paths: Paths,
    *,
    max_steps: int,
    max_concurrent: int,
) -> dict[str, Any]:
    instruction_sha = None
    if arm != "baseline":
        instruction_sha = hashlib.sha256(paths.instruction_map(arm).read_bytes()).hexdigest()
    config = {
        "schema_version": 1,
        "arm": arm,
        "model": _required_env("MODEL_ID"),
        "base_url": _required_env("OPENAI_BASE_URL"),
        "toolset": "api",
        "max_steps": max_steps,
        "max_concurrent": max_concurrent,
        "tasks": [task["task_id"] for task in tasks],
        "instruction_sha256": instruction_sha,
        "benchmark_runtime_sha256": _tree_sha256(AUTOMATIONBENCH_ROOT / "automationbench"),
        "compiler_sha256": hashlib.sha256(COMPILER.read_bytes()).hexdigest(),
    }
    if arm in {"skillgraph-schema", "skillgraph-schema-md"}:
        config["schema_prompt_sha256"] = hashlib.sha256(
            SCHEMA_PROMPT_FILE.read_bytes()
        ).hexdigest()
    if arm == "skillgraph-markdown":
        config["markdown_prompt_sha256"] = hashlib.sha256(
            SCHEMA_PROMPT_FILE.read_bytes()
        ).hexdigest()
    if arm == "task-skill-schema":
        config["task_schema_prompt_sha256"] = hashlib.sha256(
            TASK_SCHEMA_PROMPT_FILE.read_bytes()
        ).hexdigest()
    if arm == "skillgraph-schema-md":
        config["renderer_sha256"] = hashlib.sha256(
            (ROOT / "scripts" / "render_schema_markdown.py").read_bytes()
        ).hexdigest()
    config["fingerprint"] = sha256_text(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return config


def _stamp_evaluation(path: Path, config: dict[str, Any]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("meta", {})["experiment"] = config
    payload["meta"]["experiment_fingerprint"] = config["fingerprint"]
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _completed_for_config(path: Path, config: dict[str, Any]) -> bool:
    if not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("meta", {}).get("experiment_fingerprint") == config["fingerprint"]


def _merge_shards(
    arm: str,
    tasks: Sequence[dict[str, Any]],
    paths: Paths,
    shard_paths: Sequence[Path],
    config: dict[str, Any],
) -> None:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in shard_paths]
    by_name = {
        task["name"]: task for payload in payloads for task in payload.get("tasks", [])
    }
    expected = [task["task_id"] for task in tasks]
    if set(by_name) != set(expected):
        raise RuntimeError(f"{arm} shard coverage does not match the manifest")
    merged_tasks = [by_name[name] for name in expected]
    first = payloads[0]
    summary = {
        "avg_score": sum(float(task["score"]) for task in merged_tasks) / len(merged_tasks),
        "pass_rate": sum(bool(task["passed"]) for task in merged_tasks) / len(merged_tasks),
        "passed_count": sum(bool(task["passed"]) for task in merged_tasks),
        "failed_count": sum(not bool(task["passed"]) for task in merged_tasks),
    }
    additive = [
        "total_input_tokens",
        "total_output_tokens",
        "total_cached_input_tokens",
        "total_reasoning_tokens",
        "total_tool_calls",
        "total_model_time_s",
        "total_tool_time_s",
        "total_cost",
        "tasks_with_empty_responses",
        "tasks_with_errors",
        "tasks_with_zero_output",
    ]
    for key in additive:
        values = [payload.get("summary", {}).get(key) for payload in payloads]
        summary[key] = sum(float(value or 0) for value in values)
    summary["cost_formatted"] = "N/A" if not summary["total_cost"] else str(summary["total_cost"])
    meta = dict(first.get("meta", {}))
    meta.update(
        {
            "total_tasks": len(merged_tasks),
            "duration_seconds": sum(
                float(payload.get("meta", {}).get("duration_seconds") or 0)
                for payload in payloads
            ),
            "experiment": config,
            "experiment_fingerprint": config["fingerprint"],
        }
    )
    merged = {
        "meta": meta,
        "summary": summary,
        "tasks": merged_tasks,
        "usage_by_task": [
            {
                "task_id": index,
                "task_name": task["name"],
                "input_tokens": task["input_tokens"],
                "output_tokens": task["output_tokens"],
                "total_tokens": task["input_tokens"] + task["output_tokens"],
                "cost": task.get("cost"),
            }
            for index, task in enumerate(merged_tasks, start=1)
        ],
    }
    atomic_write(paths.evaluation(arm), json.dumps(merged, ensure_ascii=False, indent=2) + "\n")


def evaluate_arm(
    arm: str,
    tasks: Sequence[dict[str, Any]],
    paths: Paths,
    *,
    max_steps: int,
    max_concurrent: int,
    shard_size: int,
    force: bool,
) -> dict[str, Any]:
    output = paths.evaluation(arm)
    config = experiment_config(
        arm, tasks, paths, max_steps=max_steps, max_concurrent=max_concurrent
    )
    if not force and _completed_for_config(output, config):
        return {"arm": arm, "status": "skipped", "path": str(output)}
    if shard_size < 1:
        raise ValueError("shard_size must be positive")
    shard_paths = []
    for start in range(0, len(tasks), shard_size):
        shard_tasks = list(tasks[start : start + shard_size])
        shard_index = start // shard_size
        shard_output = paths.evaluation_shard(arm, shard_index)
        shard_config = experiment_config(
            arm,
            shard_tasks,
            paths,
            max_steps=max_steps,
            max_concurrent=max_concurrent,
        )
        shard_paths.append(shard_output)
        if not force and _completed_for_config(shard_output, shard_config):
            print(f"[shard skipped] {arm} {shard_index + 1}")
            continue
        shard_output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(_python_executable()),
            "-m",
            "automationbench.scripts.eval",
            "--model",
            _required_env("MODEL_ID"),
            "--base-url",
            _required_env("OPENAI_BASE_URL"),
            "--api-key-var",
            "OPENAI_API_KEY",
            "--api",
            "chat_completions",
            "--domains",
            "all",
            "--tasks",
            ",".join(task["task_id"] for task in shard_tasks),
            "--toolset",
            "api",
            "--max-steps",
            str(max_steps),
            "--max-concurrent",
            str(min(max_concurrent, len(shard_tasks))),
            "--no-ensure-complete",
            "--export-json",
            str(shard_output),
        ]
        if arm != "baseline":
            command.extend(["--task-instructions-json", str(paths.instruction_map(arm))])
        completed = subprocess.run(command, cwd=AUTOMATIONBENCH_ROOT)
        if completed.returncode:
            raise RuntimeError(
                f"AutomationBench {arm} shard {shard_index + 1} exited with "
                f"code {completed.returncode}"
            )
        _stamp_evaluation(shard_output, shard_config)
        print(f"[shard completed] {arm} {shard_index + 1}/{(len(tasks) + shard_size - 1) // shard_size}")
    _merge_shards(arm, tasks, paths, shard_paths, config)
    return {"arm": arm, "status": "completed", "path": str(output)}


def evaluate_all(
    arms: Sequence[str],
    tasks: Sequence[dict[str, Any]],
    paths: Paths,
    *,
    max_steps: int,
    max_concurrent: int,
    parallel_arms: int,
    shard_size: int,
    force: bool,
) -> None:
    unknown = sorted(set(arms) - set(ARMS))
    if unknown:
        raise ValueError(f"Unknown arms: {unknown}")
    build_instruction_maps(tasks, paths, arms)
    failures = []
    with ThreadPoolExecutor(max_workers=parallel_arms) as executor:
        futures = {
            executor.submit(
                evaluate_arm,
                arm,
                tasks,
                paths,
                max_steps=max_steps,
                max_concurrent=max_concurrent,
                shard_size=shard_size,
                force=force,
            ): arm
            for arm in arms
        }
        for future in as_completed(futures):
            arm = futures[future]
            try:
                result = future.result()
                print(f"[{result['status']}] {arm} -> {result['path']}")
            except Exception as exc:
                failures.append(f"{arm}: {exc}")
                print(f"[failed] {arm}: {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError("; ".join(failures))


def score(arms: Sequence[str], paths: Paths) -> dict[str, Any]:
    summaries = {}
    task_rows: dict[str, dict[str, Any]] = {}
    for arm in arms:
        path = paths.evaluation(arm)
        if not path.is_file():
            raise FileNotFoundError(path)
        result = json.loads(path.read_text(encoding="utf-8"))
        summaries[arm] = result["summary"]
        for task in result["tasks"]:
            task_rows.setdefault(task["name"], {})[arm] = {
                "score": task["score"],
                "passed": task["passed"],
                "steps": task["steps"],
                "tool_calls": task.get("num_tool_calls", 0),
                "input_tokens": task["input_tokens"],
                "output_tokens": task["output_tokens"],
            }
    payload = {"schema_version": 1, "arms": summaries, "tasks": task_rows}
    output = paths.scores()
    atomic_write(output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({arm: {"pass_rate": summaries[arm].get("pass_rate"), "avg_score": summaries[arm].get("avg_score")} for arm in arms}, indent=2))
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--label",
        default="",
        help=(
            "Namespace for instructions/, evaluation/, and scores.json. Use this for any "
            "subset run (for example --domains support --label support-only) so its "
            "artifacts never overwrite a previous full-manifest run."
        ),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    domain_help = (
        "Only operate on manifest tasks in these domains. "
        f"Available domains: {', '.join(DOMAINS)}"
    )
    task_help = (
        "Exact manifest task IDs to operate on. Provide one or more IDs separated by "
        "spaces; task order is preserved. This can be combined with --domains."
    )

    # select
    select_parser = subparsers.add_parser(
        "select",
        help="Select benchmark tasks and create the manifest",
    )
    select_parser.add_argument(
        "--domains",
        nargs="+",
        choices=DOMAINS,
        default=list(DOMAINS),
        metavar="DOMAIN",
        help=(
            "Domains to select. Multiple domains can be separated by spaces. "
            f"Available domains: {', '.join(DOMAINS)}"
        ),
    )
    select_parser.add_argument("--per-domain", type=int, default=5)
    select_parser.add_argument("--force", action="store_true")

    # generate
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate source skills for tasks in the manifest",
    )
    generate_parser.add_argument(
        "--domains", nargs="+", choices=DOMAINS, default=None, metavar="DOMAIN", help=domain_help
    )
    generate_parser.add_argument("--tasks", nargs="+", metavar="TASK_ID", help=task_help)
    generate_parser.add_argument("--workers", type=int, default=2)
    generate_parser.add_argument("--timeout-seconds", type=int, default=600)
    generate_parser.add_argument("--limit", type=int)
    generate_parser.add_argument("--force", action="store_true")

    # compile
    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile generated skills into skill graphs",
    )
    compile_parser.add_argument(
        "--domains", nargs="+", choices=DOMAINS, default=None, metavar="DOMAIN", help=domain_help
    )
    compile_parser.add_argument("--tasks", nargs="+", metavar="TASK_ID", help=task_help)
    compile_parser.add_argument(
        "--arms",
        nargs="+",
        choices=("skillgraph", "skillgraph-schema", "skillgraph-schema-md", "skillgraph-markdown", "task-skill-schema"),
        default=["skillgraph"],
        help=(
            "Which graph arms to build. skillgraph runs the deterministic compiler; "
            "skillgraph-schema asks the model to author the graph from the same source; "
            "skillgraph-schema-md renders that YAML to Markdown with no extra model call; "
            "skillgraph-markdown asks the model to author Markdown directly; "
            "task-skill-schema authors YAML directly from the task request."
        ),
    )
    compile_parser.add_argument("--workers", type=int, default=2)
    compile_parser.add_argument("--timeout-seconds", type=int, default=600)
    compile_parser.add_argument("--limit", type=int)
    compile_parser.add_argument("--force", action="store_true")

    # evaluate
    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate tasks already stored in the manifest",
    )
    evaluate_parser.add_argument(
        "--domains",
        nargs="+",
        choices=DOMAINS,
        default=None,
        metavar="DOMAIN",
        help=(
            "Only evaluate manifest tasks belonging to these domains. "
            "If omitted, evaluate all tasks in the manifest."
        ),
    )
    evaluate_parser.add_argument("--tasks", nargs="+", metavar="TASK_ID", help=task_help)
    evaluate_parser.add_argument(
        "--arms",
        nargs="+",
        choices=ARMS,
        default=list(DEFAULT_ARMS),
    )
    evaluate_parser.add_argument("--limit", type=int)
    evaluate_parser.add_argument("--max-steps", type=int, default=20)
    evaluate_parser.add_argument("--max-concurrent", type=int, default=2)
    evaluate_parser.add_argument("--parallel-arms", type=int, default=len(DEFAULT_ARMS))
    evaluate_parser.add_argument("--shard-size", type=int, default=2)
    evaluate_parser.add_argument("--force", action="store_true")

    # score
    score_parser = subparsers.add_parser(
        "score",
        help="Aggregate evaluation results",
    )
    score_parser.add_argument(
        "--arms",
        nargs="+",
        choices=ARMS,
        default=list(DEFAULT_ARMS),
    )

    # run
    run_parser = subparsers.add_parser(
        "run",
        help="Run selection, generation, compilation, evaluation, and scoring",
    )
    run_parser.add_argument(
        "--domains",
        nargs="+",
        choices=DOMAINS,
        default=list(DOMAINS),
        metavar="DOMAIN",
        help=(
            "Domains to run. Multiple domains can be separated by spaces. "
            f"Available domains: {', '.join(DOMAINS)}"
        ),
    )
    run_parser.add_argument("--tasks", nargs="+", metavar="TASK_ID", help=task_help)
    run_parser.add_argument("--per-domain", type=int, default=5)
    run_parser.add_argument("--workers", type=int, default=2)
    run_parser.add_argument(
        "--generation-timeout-seconds",
        type=int,
        default=600,
    )
    run_parser.add_argument(
        "--arms",
        nargs="+",
        choices=ARMS,
        default=list(DEFAULT_ARMS),
    )
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument("--max-steps", type=int, default=20)
    run_parser.add_argument("--max-concurrent", type=int, default=2)
    run_parser.add_argument("--parallel-arms", type=int, default=len(DEFAULT_ARMS))
    run_parser.add_argument("--shard-size", type=int, default=2)
    run_parser.add_argument("--force", action="store_true")

    return parser

def _limited(tasks: Sequence[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    return list(tasks[:limit] if limit is not None else tasks)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    args = build_parser().parse_args(argv)
    paths = Paths(args.run_dir.resolve(), args.label)
    domains = getattr(args, "domains", None)
    task_ids = getattr(args, "tasks", None)
    if args.command == "select":
        select_tasks(paths, per_domain=args.per_domain, domains=domains, force=args.force)
        return 0

    if args.command == "run":
        tasks = _limited(
            filter_by_task_id(
                select_tasks(paths, per_domain=args.per_domain, domains=domains, force=False),
                task_ids,
            ),
            args.limit,
        )
        source_dependent_arms = {"skill", "skillgraph", "skillgraph-schema", "skillgraph-schema-md", "skillgraph-markdown"}
        if source_dependent_arms & set(args.arms):
            generate_all(tasks, paths, workers=args.workers, force=args.force, timeout_seconds=args.generation_timeout_seconds)
        if "skillgraph" in args.arms:
            compile_all(tasks, paths, force=args.force)
        if "skillgraph-schema" in args.arms:
            compile_schema_all(
                tasks,
                paths,
                workers=args.workers,
                force=args.force,
                timeout_seconds=args.generation_timeout_seconds,
            )
        if "skillgraph-schema-md" in args.arms:
            render_schema_markdown_all(tasks, paths, force=args.force)
        if "skillgraph-markdown" in args.arms:
            generate_markdown_all(
                tasks, paths, workers=args.workers, force=args.force,
                timeout_seconds=args.generation_timeout_seconds,
            )
        if "task-skill-schema" in args.arms:
            generate_task_schema_all(
                tasks,
                paths,
                workers=args.workers,
                force=args.force,
                timeout_seconds=args.generation_timeout_seconds,
            )
        evaluate_all(args.arms, tasks, paths, max_steps=args.max_steps, max_concurrent=args.max_concurrent, parallel_arms=args.parallel_arms, shard_size=args.shard_size, force=args.force)
        score(args.arms, paths)
        return 0

    tasks = _limited(
        filter_by_task_id(filter_by_domain(read_manifest(paths), domains), task_ids),
        getattr(args, "limit", None),
    )
    if args.command == "generate":
        generate_all(tasks, paths, workers=args.workers, force=args.force, timeout_seconds=args.timeout_seconds)
    elif args.command == "compile":
        if "skillgraph" in args.arms:
            compile_all(tasks, paths, force=args.force)
        needs_yaml = {"skillgraph-schema", "skillgraph-schema-md"} & set(args.arms)
        if needs_yaml:
            missing = [task for task in tasks if not paths.schema_skill(task).is_file()]
            if "skillgraph-schema" in args.arms or missing:
                compile_schema_all(
                    tasks if "skillgraph-schema" in args.arms else missing,
                    paths,
                    workers=args.workers,
                    force=args.force,
                    timeout_seconds=args.timeout_seconds,
                )
        if "task-skill-schema" in args.arms:
            generate_task_schema_all(
                tasks,
                paths,
                workers=args.workers,
                force=args.force,
                timeout_seconds=args.timeout_seconds,
            )
        if "skillgraph-markdown" in args.arms:
            generate_markdown_all(
                tasks, paths, workers=args.workers, force=args.force,
                timeout_seconds=args.timeout_seconds,
            )
        if "skillgraph-schema-md" in args.arms:
            render_schema_markdown_all(tasks, paths, force=args.force)
    elif args.command == "evaluate":
        evaluate_all(args.arms, tasks, paths, max_steps=args.max_steps, max_concurrent=args.max_concurrent, parallel_arms=args.parallel_arms, shard_size=args.shard_size, force=args.force)
    elif args.command == "score":
        score(args.arms, paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
