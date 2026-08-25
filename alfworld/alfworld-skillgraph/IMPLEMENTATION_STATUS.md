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

Still intentionally unavailable and therefore blocked:

- ALFWorld rollout/evaluator integration, DeepSeek API adapter and request logging.
- Failure IR, Preservation IR, Root Cause merge, candidate generation/format repair, semantic audit, dynamic validation, and the final go/no-go experiment.
- A human-gated generated S0; the dry-run baseline is a placeholder and cannot be used as an experiment artifact.

`pytest` is not installed in this environment. `python -m py_compile` and direct invocation of all `test_*` functions in `test_stage0_core.py` and `test_stage0_run.py` pass.
