# Family-level Incremental SkillGraph experiment

`family_skillgraph.py` implements the frozen HR-family experiment. It selects the 25
tasks deterministically, authors and optimizes the family artifacts, prevents test
rollouts before artifact freeze, and reports the paired task-level bootstrap result.

## Prerequisites

- AutomationBench dependencies installed in `AutomationBench/.venv`.
- `OPENAI_API_KEY` and `OPENAI_BASE_URL` configured.
- `STUDENT_MODEL_ID` set to the frozen student model (or `MODEL_ID` as a fallback).
- The Pi authoring harness installed. Artifact authoring is hard-coded to
  `deepseek-v4-flash`; changing `MODEL_ID` does not change the author model.

## Run

Run the phases separately so the frozen artifacts can be inspected before the sealed
test is opened:

```powershell
AutomationBench\.venv\Scripts\python.exe automationbench-skill-suite\family_skillgraph.py select
AutomationBench\.venv\Scripts\python.exe automationbench-skill-suite\family_skillgraph.py author
AutomationBench\.venv\Scripts\python.exe automationbench-skill-suite\family_skillgraph.py optimize
AutomationBench\.venv\Scripts\python.exe automationbench-skill-suite\family_skillgraph.py freeze
AutomationBench\.venv\Scripts\python.exe automationbench-skill-suite\family_skillgraph.py test
AutomationBench\.venv\Scripts\python.exe automationbench-skill-suite\family_skillgraph.py report
```

`run` performs all phases, but is intended for a fresh run directory only. Use
`--run-dir PATH` to isolate replications. The `test` command is intentionally
one-shot: rerunning it after the state changes from `artifacts_frozen` is rejected.

Each task repetition is a fresh AutomationBench subprocess with a 20-step cap and
the task's exact `limited_zapier` tool list. Runner failures are retried twice, then
stored as missing observations. Raw evaluation JSON is never overwritten by the
optimizer; Analyzer receives only the explicit allowlisted optimizer view.

## Outputs

- `manifest.json`: frozen hash split and instance-free task cards.
- `artifacts/`: all Markdown and SkillGraph versions used by the arms.
- `records/`: versioned diagnoses, atomic diffs, gate outcomes, and author usage.
- `evaluations/raw/`: immutable per-rollout evaluator exports and run fingerprints.
- `evaluations/sealed-test.json`: the seven-arm sealed result bundle.
- `report.json`: primary comparison, exploratory secondary comparisons, costs, and
  graph complexity.

The primary claim is emitted only when the Incremental SkillGraph mean paired task
difference is positive and the task-level bootstrap 95% confidence interval has a
strictly positive lower bound.

The eight test tasks are held out from this new optimization workflow. They remain
public AutomationBench tasks and are not claimed to be historically never-run items.
