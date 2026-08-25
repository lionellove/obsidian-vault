# ALFWorld SkillGraph Stage 0 runner

`stage0_core.py` contains the dependency-free structural contract: Skill Package validation, scope and budget checks, one deterministic renderer, strict structured patch application, canonical IR diff/full-rewrite checking, task IDs/groups, and paired outcomes.

`stage0_llm.py`, `stage0_executor.py`, and `stage0_episode.py` provide the first offline-testable vertical slice. The DeepSeek client uses an injected standard-library transport (or real HTTPS transport), records request/response metadata without persisting API keys, sends explicit Executor/meta thinking settings and frozen role/schema envelopes, parses only one exact `FINAL_ACTION:`, and runs a 50-step-bounded environment protocol while recording reproducible trace IDs, skill text/hash, actions, observations, requests, usage, and termination; adapters close on every exit path. `stage0_alfworld.py` is a lazy-import, seeded, train-only `AlfredTWEnv` adapter; optional ALFWorld dependencies are not needed for structural tests.

`stage0_ir.py`, `stage0_evolution.py`, `stage0_format.py`, `stage0_verifier.py`, and `stage0_artifacts.py` provide an offline evolution seam: strict representation-neutral Failure/Preservation/Root Cause IR, analyzer input firewall, support-gated root-cause selection, identical de-instantiated generator context, bounded format-only repair, budgeted Structured Patch/Full Rewrite checks, blind seven-field semantic audits with no veto, and JSON/JSONL plus exact-byte SHA-256 artifact sidecars. These modules stop before ALFWorld rollout and never consult expert/PDDL state.

`stage0_run.py` is the train-only preflight sampler. It accepts only an ALFWorld `json_2.1.1` root containing `train`, or a terminal `train` directory. `valid_train`, `valid_seen`, `valid_unseen`, and other split roots are rejected. The sampler writes relative-to-`train` canonical `game.tw-pddl` IDs, recursively scans nested task fields, top-level arrays, and `gamefile` values while filtering noise, compares exact canonical IDs across known split markers, keeps near-duplicate groups disjoint, hashes the denylist/manifests, records `environment_seed`, and assigns the six validation condition permutations three times each.

```powershell
python stage0_run.py --repo-root .. --data-root ..\data\json_2.1.1 --dry-run
python stage0_run.py --repo-root .. --data-root <path-to-real-alfworld-data> --s0-file <human-gated-s0.json>
```

The first command can produce only artifacts marked `scaffold_placeholder` / `not_experiment_artifact`; its hard-coded S0 is not an experimental S0. A non-dry preflight without a complete live configuration exits non-zero as `blocked_prerequisites`; the lifecycle CLI below is the only path that can unlock a real run, and it requires explicit confirmation, credentials, train data, and an approved human gate. Every preflight writes the final `preregistration.json` once and records its exact UTF-8 SHA-256 in the adjacent `preregistration.sha256` sidecar.

Offline data verification found 3,553 train `game.tw-pddl` files at `/home/lionel/.cache/alfworld/json_2.1.1/train`; the dependency-free sampler generated three balanced 18-task manifests. The current WSL/pyenv Python lacks pip-installed `alfworld`/`textworld`, so live environment execution remains fail-closed.

An offline smoke run proves the seam without network/API calls:

```powershell
python stage0_smoke.py --output <temporary-path>\trajectory.json
```

It writes a clearly marked `scaffold_smoke` trajectory using fake transport/environment objects. This does not enable the formal runner's non-dry-run path.

The complete paused lifecycle is available through `stage0_cli.py`:

```powershell
python stage0_cli.py prepare --run-dir <run> --data-root <json_2.1.1> --repo-root <repo>
python stage0_cli.py reject-s0 --run-dir <run> --checklist <five-boolean-json> --reason "failed public gate label"
python stage0_cli.py approve --run-dir <run> --checklist <five-boolean-json> --auditor <name>
python stage0_cli.py run --run-dir <run> --data-root <train> --confirm-live-run
python stage0_cli.py resume --run-dir <run> --data-root <train> --confirm-live-run
python stage0_cli.py submit-audit --run-dir <run> --scores <human_scores.json>
python stage0_cli.py status --run-dir <run>
python stage0_cli.py offline-smoke --run-dir <temporary-run>
```

Lifecycle order is `prepare → (reject-s0 → approve, repeated only with a new S0 version) → run/resume → submit-audit`. `reject-s0` requires the API key and a valid train data root but never enables live episodes; it forwards only false public gate labels to S0 regeneration. `offline-smoke` is explicitly a scaffold and performs no API request or episode. Runtime episodes checkpoint under stable phase/task/condition keys and resume only executes incomplete units. A formal run pauses at `awaiting_human_audit` after writing the blinded packet; `submit-audit` validates a complete eight-item rubric for every anonymous candidate (with no condition mapping) before changing state to `completed`. The packet explicitly records `expert_plan_status=deferred_unavailable_in_public_trajectory_artifacts` because the public EpisodeRunner does not read privileged ALFWorld plans; no expert evidence is fabricated. The formal `run`/`resume` commands remain fail-closed when ALFWorld environment configuration or the required external approvals are absent.

Metrics and `code_state.json` include an estimated, base-rate DeepSeek cost using the captured pricing table (cache-hit $0.0028/M, cache-miss $0.14/M, output $0.28/M; reasoning tokens are reported separately and not double-counted). The source, model, capture time, and rates are recorded in state, preregistration, and metrics; missing billing usage keeps completion blocked and never claims an invoice amount.
