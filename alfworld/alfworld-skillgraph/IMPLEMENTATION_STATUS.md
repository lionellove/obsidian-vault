# Stage 0 implementation status — 2026-08-25

Implemented and directly smoke-tested with the standard library:

- Correct six-family classification, including `look_at_obj_in_light-` for Examine in Light.
- Train-only root resolution (`json_2.1.1/train` or terminal `train`); all validation/other split roots fail closed.
- Machine-independent relative `game.tw-pddl` IDs across `train`/`valid_train`/`valid_seen`/`valid_unseen` markers, recursive denylist extraction from nested objects, top-level arrays and `gamefile` values with path-shape filtering, exact comparisons, denylist/manifest SHA-256 files, and explicit `environment_seed`.
- Near-duplicate keys containing task type/goal template, object, movable receptacle, target receptacle, scene, and sliced state while omitting trial IDs; ID/group disjointness across all three splits.
- Complete node/constraint/verification/fallback scope and reference checks, six-family targets, instance-scope rejection, global ID uniqueness, configurable structural budgets, and production budget enforcement for the placeholder S0 preflight.
- Fail-closed `ADD`/`UPDATE`/`DELETE` patches with mandatory root-cause addresses, shape/target checks, input immutability, and strict Full Rewrite canonical IR/change-manifest validation including package-level changes.
- Paired outcomes reject duplicate IDs and set mismatches, and report repairs, regressions, stable successes, stable failures, and `NetGain`.
- Deterministic renderer locked by an exact golden string and UTF-8 file-byte SHA-256.
- Balanced 18-task validation scheduling (six condition orders, exactly three occurrences each).
- `stage0_run.py --dry-run` emits only explicitly marked scaffold/placeholder artifacts.
- Preregistration is written once per run; its exact final JSON-byte SHA-256 is stored only in `preregistration.sha256` (no self-referential JSON hash).
- Offline vertical slice: injectable standard-library DeepSeek request seam with explicit Executor/meta thinking contracts, frozen role/system prompts plus JSON response-format/schema envelopes, auditable usage/latency/error records, strict one-action Executor parser, reproducible trace IDs, 50-step-bounded EpisodeRunner, close-on-error behavior, and seeded lazy train-only `AlfredTWEnv` adapter.
- Offline fake transport/environment smoke CLI writes a marked `scaffold_smoke` trajectory JSON without network/API calls.
- Offline evolution seam validates representation-neutral Failure/Preservation/Root Cause IR, rejects hidden expert/PDDL and instance scope, gates Root Cause selection on distinct support and patchability, and sends identical de-instantiated generator context with one semantic call per generator.
- Structured JSON responses have deterministic display normalization plus at most three format-only repairs with semantic fingerprint checking; candidates are budget-validated through the existing patch/full-rewrite validators and stored as unified `CandidateResult` records.
- Blind seven-field semantic verification hides method/provenance/score labels and cannot veto a structurally valid candidate; `ArtifactWriter` emits IR/candidate/verifier JSON/JSONL and exact UTF-8 SHA-256 sidecars while rejecting credential fields.
- Paused orchestration is available through `Stage0Pipeline`: train-only manifests, S0 generation/human gate with label-only rejection/regeneration, authoritative versioned checkpoint journal, exact-sidecar evolution resume, code/data/model hash-checked resume, calibration floor/ceiling stop, shared evolution artifact reuse, balanced validation scheduling, descriptive metrics, explicit seven-condition go/no-go, uniformly shaped randomly blinded candidate packets with private mapping, request-record/model-fingerprint aggregation, captured pricing/cost estimates, code-state/dependency/data-version record, and §16 artifact layout. `stage0_cli.py` exposes prepare/reject-s0/approve/run/resume/status/offline-smoke and `submit-audit`.

Still intentionally unavailable and therefore blocked:

- Offline sampler verification has a real WSL train dataset at `/home/lionel/.cache/alfworld/json_2.1.1/train` (3,553 game files) and produced three 18-task manifests; WSL/pyenv still lacks pip `alfworld`/`textworld`, so live adapter execution remains blocked.
- Formal ALFWorld rollout/evaluator integration and live DeepSeek execution remain blocked unless the lifecycle CLI receives explicit confirmation, credentials, real train data, and an approved frozen S0; the HTTPS transport seam exists but was not invoked in tests.
- No real API request or 90-episode run was executed here. Live ALFWorld environment wiring, credentials, human approval, and explicit `--confirm-live-run` remain required external inputs; CLI is fail-closed without them.
- A human-gated generated S0; the dry-run baseline is a placeholder and cannot be used as an experiment artifact.
- Blind-audit packets deliberately mark `expert_plan_status=deferred_unavailable_in_public_trajectory_artifacts`: the current public EpisodeRunner never records privileged ALFWorld plans, and no hidden state is read or fabricated. Supplying a separately authorized expert-plan artifact remains an external audit input.

`pytest` is not installed in this environment. `python -m py_compile`, 83 direct target `test_*` functions (including atomic-state, checkpoint-journal, evolution-hash, blind-packet, reject-s0, pricing, and earlier P0/S0/metrics/pipeline/CLI suites), and the existing 8 `run_alf_bench` unittest cases pass. A run remains `awaiting_human_audit` until a complete blinded eight-item score packet is submitted for every anonymous candidate; only then can it become `completed` (with expert-plan evidence explicitly deferred and cost usage complete).
