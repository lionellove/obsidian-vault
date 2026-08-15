import importlib.util
import sys
from pathlib import Path

import pytest
import yaml


PIPELINE = Path(__file__).resolve().parents[1] / "automationbench_pipeline.py"
SPEC = importlib.util.spec_from_file_location("automationbench_pipeline", PIPELINE)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = pipeline
SPEC.loader.exec_module(pipeline)


def test_evenly_spaced_indices_are_deterministic():
    assert pipeline.evenly_spaced_indices(100, 5) == [0, 25, 50, 74, 99]


def test_generation_prompt_contains_state_but_excludes_assertions():
    task = {
        "task_id": "sales.example",
        "domain": "sales",
        "skill_name": "ab-sales-example-deadbeef",
        "task_request": "Update the requested account.",
        "available_tools": {"callable_runtime_tools": ["api_search"]},
        "initial_state": {"account": "TOP-SECRET-INITIAL-STATE"},
        "assertions": ["TOP-SECRET-ASSERTION"],
    }

    prompt = pipeline.build_generation_prompt(task, existing_skill="OLD-SKILL")

    assert "Update the requested account." in prompt
    assert "ab-sales-example-deadbeef" in prompt
    assert "api_search" in prompt
    assert "TOP-SECRET-INITIAL-STATE" in prompt
    assert "TOP-SECRET-ASSERTION" not in prompt
    assert "OLD-SKILL" in prompt
    assert "{{task_name}}" not in prompt


def test_normalizer_accepts_procedure_as_graph_source():
    markdown = """---
name: ab-example-deadbeef
description: test
---
# Example
## Overview
x
## Procedure
1. [action] Inspect {#inspect}
   - -> finish
2. [finish] Finish {#finish}
## Completion Criteria
- done
"""

    normalized = pipeline.normalize_workflow_markdown(markdown)

    assert "## Procedure" in normalized
    assert "- -> finish" in normalized
    assert "## Completion Check" in normalized
    assert "## Completion Criteria" not in normalized


def test_validator_accepts_task_compiler_skill_structure():
    markdown = """---
name: ab-example-deadbeef
description: test
---
# Example
## Overview
x
## When to Use
x
## Do Not Use When
x
## Inputs and Authoritative Sources
x
## Required Tools
x
## Tool Limitations
x
## Core Rules
x
## Procedure
1. [action] Act {#act}
   - -> finish
2. [finish] Finish {#finish}
## Mutation Ordering
x
## Verification
x
## Failure Handling
x
## Completion Criteria
x
## Output Requirements
x
"""

    pipeline.validate_skill_markdown(
        markdown,
        expected_name="ab-example-deadbeef",
    )


def test_validator_rejects_empty_task_compiler_sections():
    markdown = """---
name: ab-example-deadbeef
description: test
---
# Example
## Overview
## Inputs and Authoritative Sources
x
"""

    with pytest.raises(ValueError, match="section ## Overview must not be empty"):
        pipeline.validate_skill_markdown(
            markdown,
            expected_name="ab-example-deadbeef",
        )


def test_failed_generation_record_is_not_cacheable():
    previous = {
        "status": "failed",
        "generation_input_sha256": "same-input",
        "model_id": "same-model",
    }

    assert not pipeline._generation_record_is_cacheable(
        previous,
        generation_input_sha256="same-input",
        model_id="same-model",
    )


def test_skill_names_are_valid_and_stable():
    first = pipeline.make_skill_name("sales.multi_hop_lookup")
    second = pipeline.make_skill_name("sales.multi_hop_lookup")
    assert first == second
    assert len(first) <= 64


def test_normalizer_repairs_common_generated_graph_errors():
    markdown = """---
name: ab-example-deadbeef
description: test
---
## Overview
x
## When to Use
- x
## Do Not Use When
- x
## Core Rules
- x
## Tools
- x
## Workflow
1. [action] Inspect {#inspect}
   - -> found -> act
   - -> missing -> nonexistent
2. [action] Act {#act}
   - -> retry -> inspect
   - -> done -> finish
3. [fail] Stop {#fail}
   - -> -> fail
4. [finish] Finish {#finish}
   - -> -> finish
## Completion Check
- x
"""

    normalized = pipeline.normalize_workflow_markdown(markdown)

    assert "1. [decision] Inspect {#inspect}" in normalized
    assert "- found -> act" in normalized
    assert "- missing -> act" in normalized
    assert "- retry -> inspect {loop=retry_act max=1}" in normalized
    assert "- -> fail" not in normalized
    assert "- -> finish\n## Completion Check" not in normalized


VALID_SCHEMA_GRAPH = """
skillgraph:
  name: ab-support-example
  entry: start
  nodes:
    - id: start
      tag: start
      instruction: Begin.
    - id: sync_case
      tag: operation
      instruction: Sync the case.
    - id: verify_sync
      tag: verification
      instruction: Verify the sync.
    - id: done
      tag: end
      instruction: Complete.
  edges:
    - source: start
      target: sync_case
      tag: sequence
    - source: sync_case
      target: verify_sync
      tag: sequence
    - source: verify_sync
      target: done
      tag: conditional
      condition: sync_is_correct
    - source: verify_sync
      target: sync_case
      tag: retry
      condition: sync_is_incorrect
      max_retry: 2
"""


def test_schema_validator_accepts_a_wellformed_graph():
    stats = pipeline.validate_schema_yaml(VALID_SCHEMA_GRAPH)

    assert stats == {"nodes": 4, "edges": 4, "entry": "start"}


@pytest.mark.parametrize(
    ("substitution", "expected"),
    [
        (("target: done", "target: nonexistent"), "not a declared node"),
        (("entry: start", "entry: missing_node"), "entry"),
        (("tag: sequence", "tag: goto"), "invalid tag"),
        (("max_retry: 2", "max_retry: 0"), "non-positive max_retry"),
    ],
)
def test_schema_validator_rejects_broken_graphs(substitution, expected):
    old, new = substitution
    broken = VALID_SCHEMA_GRAPH.replace(old, new, 1)

    with pytest.raises(ValueError, match=expected):
        pipeline.validate_schema_yaml(broken)


def test_schema_validator_rejects_unreachable_and_leaking_terminals():
    orphan = VALID_SCHEMA_GRAPH.replace(
        "    - id: done", "    - id: orphan\n      tag: operation\n      instruction: Stranded.\n    - id: done", 1
    )
    with pytest.raises(ValueError, match="unreachable nodes"):
        pipeline.validate_schema_yaml(orphan)

    leaking = VALID_SCHEMA_GRAPH + """    - source: done
      target: sync_case
      tag: sequence
"""
    with pytest.raises(ValueError, match="no outgoing edges"):
        pipeline.validate_schema_yaml(leaking)


def test_schema_prompt_embeds_the_source_skill_and_transport_markers():
    prompt = pipeline.build_schema_prompt("# SOURCE-SKILL-BODY")

    assert "# SOURCE-SKILL-BODY" in prompt
    assert "{{SKILL_CONTENT}}" not in prompt
    assert "<skill_md>" in prompt


def test_task_schema_prompt_embeds_only_the_public_task_request():
    task = {
        "task_id": "support.example",
        "task_request": "Synchronize the requested support records.",
    }

    prompt = pipeline.build_task_schema_prompt(task)

    assert "Synchronize the requested support records." in prompt
    assert "{{TASK_DESCRIPTION}}" not in prompt
    assert "initial_state" not in prompt
    assert "<skill_md>" in prompt


def test_markdown_prompt_embeds_the_source_skill():
    prompt = pipeline.build_markdown_prompt("# SOURCE-SKILL-BODY")

    assert "# SOURCE-SKILL-BODY" in prompt
    assert "{{SKILL_CONTENT}}" not in prompt


def test_markdown_validator_accepts_the_prompt_node_tags():
    markdown = """---
name: example
description: example graph
---
# Example
## Overview
x
## Graph
```text
[start] -> [work]
[work] -> [done]
```
## Nodes
### `start` — Start
**Type:** start
### `work` — Work
**Type:** operation
### `done` — Done
**Type:** end
## Completion Check
- done
"""

    assert pipeline.validate_skillgraph_markdown(markdown) == {
        "nodes": 3, "edges": 2, "entry": "start"
    }


def test_yaml_fence_is_stripped_when_the_model_adds_one():
    assert pipeline._strip_yaml_fence("```yaml\nskillgraph:\n  name: x\n```") == (
        "skillgraph:\n  name: x\n"
    )
    assert pipeline._strip_yaml_fence("skillgraph:\n  name: x\n") == "skillgraph:\n  name: x\n"
    assert pipeline._strip_yaml_fence("<skill_md>\n```yaml\nskillgraph:\n  name: x\n```\n</skill_md>") == (
        "skillgraph:\n  name: x\n"
    )
    assert pipeline._strip_yaml_fence("<skill_md>\n```yaml\nskillgraph:\n  name: x\n</skill_md>") == (
        "skillgraph:\n  name: x\n"
    )
    assert pipeline._strip_yaml_fence("<skill_md>\n```yaml\nskillgraph:\n  name: x\n```") == (
        "skillgraph:\n  name: x\n"
    )


MANIFEST_TASKS = [
    {"task_id": "sales.a", "domain": "sales"},
    {"task_id": "support.a", "domain": "support"},
    {"task_id": "hr.a", "domain": "hr"},
    {"task_id": "support.b", "domain": "support"},
]


def test_domain_filter_selects_one_domain_in_manifest_order():
    filtered = pipeline.filter_by_domain(MANIFEST_TASKS, ["support"])

    assert [task["task_id"] for task in filtered] == ["support.a", "support.b"]


def test_domain_filter_without_domains_returns_every_task():
    assert pipeline.filter_by_domain(MANIFEST_TASKS, None) == MANIFEST_TASKS


def test_domain_filter_rejects_an_empty_result_instead_of_running_nothing():
    with pytest.raises(ValueError, match="No manifest tasks match"):
        pipeline.filter_by_domain([{"task_id": "sales.a", "domain": "sales"}], ["support"])


def test_task_filter_selects_explicit_tasks_in_requested_order():
    filtered = pipeline.filter_by_task_id(MANIFEST_TASKS, ["support.b", "sales.a"])

    assert [task["task_id"] for task in filtered] == ["support.b", "sales.a"]


def test_task_filter_rejects_task_ids_absent_from_the_manifest():
    with pytest.raises(ValueError, match="unknown.task"):
        pipeline.filter_by_task_id(MANIFEST_TASKS, ["sales.a", "unknown.task"])


def test_label_namespaces_derived_artifacts_without_touching_the_manifest():
    unlabeled = pipeline.Paths(Path("/run"))
    labeled = pipeline.Paths(Path("/run"), "support-only")

    assert labeled.manifest == unlabeled.manifest
    assert labeled.evaluation("skill") != unlabeled.evaluation("skill")
    assert labeled.evaluation("skill") == Path("/run/support-only/evaluation/skill.json")
    assert labeled.instruction_map("skill") == Path("/run/support-only/instructions/skill.json")
    assert labeled.scores() == Path("/run/support-only/scores.json")
    assert labeled.evaluation_shard("skill", 0) == Path(
        "/run/support-only/evaluation/shards/skill/000.json"
    )
    assert unlabeled.scores() == Path("/run/scores.json")
    assert unlabeled.evaluation("skill") == Path("/run/evaluation/skill.json")


def test_every_non_baseline_arm_has_an_instruction_source():
    paths = pipeline.Paths(Path("/run"))
    task = {"skill_name": "ab-example-deadbeef"}
    getters = {
        "skill": paths.source_skill,
        "agent-authored-skill": paths.agent_authored_skill,
        "skillgraph": paths.graph_skill,
        "skillgraph-schema": paths.schema_skill,
        "skillgraph-schema-md": paths.schema_markdown,
        "skillgraph-markdown": paths.model_markdown_skill,
        "task-skill-schema": paths.task_schema_skill,
    }

    assert set(pipeline.ARMS) - {"baseline"} == set(getters)
    assert len({str(getter(task)) for getter in getters.values()}) == len(getters)


def test_agent_authored_skill_uses_an_isolated_directory():
    paths = pipeline.Paths(Path("/run"))
    task = {"skill_name": "ab-example-deadbeef"}

    assert paths.agent_authored_skill(task) == Path(
        "/run/skills/agent-authored/ab-example-deadbeef/SKILL.md"
    )
    assert paths.agent_authored_skill(task) != paths.source_skill(task)


def test_agent_authored_arm_is_explicit_not_an_end_to_end_default():
    args = pipeline.build_parser().parse_args(["run"])

    assert "agent-authored-skill" in pipeline.ARMS
    assert "agent-authored-skill" not in args.arms


def test_instruction_map_validates_agent_authored_skills(tmp_path):
    paths = pipeline.Paths(tmp_path)
    task = {
        "task_id": "sales.example",
        "skill_name": "ab-sales-example-deadbeef",
    }
    skill = paths.agent_authored_skill(task)
    skill.parent.mkdir(parents=True)
    skill.write_text("# Missing frontmatter\n", encoding="utf-8")

    with pytest.raises(ValueError, match="frontmatter"):
        pipeline.build_instruction_maps([task], paths, ["agent-authored-skill"])


RENDERER = Path(__file__).resolve().parents[1] / "scripts" / "render_schema_markdown.py"
RENDERER_SPEC = importlib.util.spec_from_file_location("render_schema_markdown", RENDERER)
renderer = importlib.util.module_from_spec(RENDERER_SPEC)
assert RENDERER_SPEC.loader is not None
sys.modules[RENDERER_SPEC.name] = renderer
RENDERER_SPEC.loader.exec_module(renderer)


def test_renderer_preserves_every_node_edge_and_criterion():
    graph = yaml.safe_load(VALID_SCHEMA_GRAPH)["skillgraph"]
    graph["constraints"] = ["never_guess_a_missing_capacity"]
    graph["nodes"][1]["verification"] = ["case_was_synced"]

    markdown = renderer.render_markdown(graph)

    for node in graph["nodes"]:
        assert f"### `{node['id']}`" in markdown
    for edge in graph["edges"]:
        assert f"[{edge['source']}] -- " in markdown
        assert f"--> [{edge['target']}]" in markdown
        if edge.get("condition"):
            assert edge["condition"] in markdown
    assert "never_guess_a_missing_capacity" in markdown
    assert "case_was_synced" in markdown
    assert "max=2" in markdown
    assert "**Entry:** `start`" in markdown


def test_renderer_marks_terminal_nodes_and_escapes_table_pipes():
    graph = yaml.safe_load(VALID_SCHEMA_GRAPH)["skillgraph"]
    graph["nodes"][1]["instruction"] = "Sync the case | then stop"

    markdown = renderer.render_markdown(graph)

    assert "- terminal, no outgoing edges" in markdown
    assert "Sync the case \\| then stop" in markdown


def test_renderer_rejects_yaml_without_a_skillgraph_mapping(tmp_path):
    broken = tmp_path / "skillgraph.yaml"
    broken.write_text("nodes: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing top-level skillgraph mapping"):
        renderer.load_graph(broken)


def test_markdown_arm_is_a_pure_rendering_of_the_yaml_arm(tmp_path):
    """The md arm must vary only in format, so it shares the renderer with the script."""
    task = {"task_id": "support.example", "skill_name": "ab-support-example-deadbeef"}
    paths = pipeline.Paths(tmp_path)
    yaml_path = paths.schema_skill(task)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(VALID_SCHEMA_GRAPH, encoding="utf-8")

    pipeline.render_schema_markdown_all([task], paths, force=False)

    rendered = paths.schema_markdown(task)
    assert rendered.read_text(encoding="utf-8") == renderer.render_markdown(
        renderer.load_graph(yaml_path)
    )
    assert yaml_path.read_text(encoding="utf-8") == VALID_SCHEMA_GRAPH


def test_markdown_arm_fails_loudly_when_the_yaml_is_missing(tmp_path):
    task = {"task_id": "support.example", "skill_name": "ab-support-example-deadbeef"}

    with pytest.raises(RuntimeError, match="1 schema renderings failed"):
        pipeline.render_schema_markdown_all([task], pipeline.Paths(tmp_path), force=False)
