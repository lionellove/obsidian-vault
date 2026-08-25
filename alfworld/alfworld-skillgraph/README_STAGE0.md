# ALFWorld SkillGraph Stage 0 runner

`stage0_core.py` contains the dependency-free structural contract: Skill Package validation, scope and budget checks, one deterministic renderer, strict structured patch application, canonical IR diff/full-rewrite checking, task IDs/groups, and paired outcomes.

`stage0_llm.py`, `stage0_executor.py`, and `stage0_episode.py` provide the first offline-testable vertical slice. The DeepSeek client uses an injected standard-library transport (or real HTTPS transport), records request/response metadata without persisting API keys, sends explicit Executor/meta thinking settings, parses only one exact `FINAL_ACTION:`, and runs a 50-step-bounded environment protocol while recording skill text/hash, actions, observations, requests, usage, and termination. `stage0_alfworld.py` is a lazy-import, train-only `AlfredTWEnv` adapter; optional ALFWorld dependencies are not needed for structural tests.

`stage0_ir.py`, `stage0_evolution.py`, `stage0_format.py`, `stage0_verifier.py`, and `stage0_artifacts.py` provide an offline evolution seam: strict representation-neutral Failure/Preservation/Root Cause IR, analyzer input firewall, support-gated root-cause selection, identical de-instantiated generator context, bounded format-only repair, budgeted Structured Patch/Full Rewrite checks, blind seven-field semantic audits with no veto, and JSON/JSONL plus exact-byte SHA-256 artifact sidecars. These modules stop before ALFWorld rollout and never consult expert/PDDL state.

`stage0_run.py` is the train-only preflight sampler. It accepts only an ALFWorld `json_2.1.1` root containing `train`, or a terminal `train` directory. `valid_train`, `valid_seen`, `valid_unseen`, and other split roots are rejected. The sampler writes relative-to-`train` canonical `game.tw-pddl` IDs, recursively scans nested task fields, top-level arrays, and `gamefile` values while filtering noise, compares exact canonical IDs across known split markers, keeps near-duplicate groups disjoint, hashes the denylist/manifests, records `environment_seed`, and assigns the six validation condition permutations three times each.

```powershell
python stage0_run.py --repo-root .. --data-root ..\data\json_2.1.1 --dry-run
python stage0_run.py --repo-root .. --data-root <path-to-real-alfworld-data> --s0-file <human-gated-s0.json>
```

The first command can produce only artifacts marked `scaffold_placeholder` / `not_experiment_artifact`; its hard-coded S0 is not an experimental S0. A non-dry preflight without a complete live configuration exits non-zero as `blocked_prerequisites`; the lifecycle CLI below is the only path that can unlock a real run, and it requires explicit confirmation, credentials, train data, and an approved human gate. Every preflight writes the final `preregistration.json` once and records its exact UTF-8 SHA-256 in the adjacent `preregistration.sha256` sidecar.

On 2026-08-25 the configured data entry was an inaccessible link and no local train `game.tw-pddl` files were available, so no dynamic Stage 0 result was fabricated.

An offline smoke run proves the seam without network/API calls:

```powershell
python stage0_smoke.py --output <temporary-path>\trajectory.json
```

It writes a clearly marked `scaffold_smoke` trajectory using fake transport/environment objects. This does not enable the formal runner's non-dry-run path.

The complete paused lifecycle is available through `stage0_cli.py`:

```powershell
python stage0_cli.py prepare --run-dir <run> --data-root <json_2.1.1> --repo-root <repo>
python stage0_cli.py approve --run-dir <run> --checklist <five-boolean-json> --auditor <name>
python stage0_cli.py run --run-dir <run> --data-root <train> --confirm-live-run
python stage0_cli.py resume --run-dir <run> --data-root <train> --confirm-live-run
python stage0_cli.py status --run-dir <run>
python stage0_cli.py offline-smoke --run-dir <temporary-run>
```

`offline-smoke` is explicitly a scaffold and performs no API request or episode. The formal `run`/`resume` commands remain fail-closed when ALFWorld environment configuration or the required external approvals are absent.
