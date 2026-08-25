# ALFWorld SkillGraph Stage 0 runner

`stage0_core.py` contains the dependency-free structural contract: Skill Package validation, scope and budget checks, one deterministic renderer, strict structured patch application, canonical IR diff/full-rewrite checking, task IDs/groups, and paired outcomes.

`stage0_run.py` is intentionally a preflight only. It accepts only an ALFWorld `json_2.1.1` root containing `train`, or a terminal `train` directory. `valid_train`, `valid_seen`, `valid_unseen`, and other split roots are rejected. The sampler writes relative-to-`train` canonical `game.tw-pddl` IDs, recursively scans nested task fields, top-level arrays, and `gamefile` values while filtering noise, compares exact canonical IDs across known split markers, keeps near-duplicate groups disjoint, hashes the denylist/manifests, records `environment_seed`, and assigns the six validation condition permutations three times each.

```powershell
python stage0_run.py --repo-root .. --data-root ..\data\json_2.1.1 --dry-run
python stage0_run.py --repo-root .. --data-root <path-to-real-alfworld-data> --s0-file <human-gated-s0.json>
```

The first command can produce only artifacts marked `scaffold_placeholder` / `not_experiment_artifact`; its hard-coded S0 is not an experimental S0. The second command exits non-zero with a clear `blocked_non_dry_run_unimplemented` status because rollout, DeepSeek API integration, Failure/Preservation IR, and the three-layer validation loop are not implemented in this repository. Supplying `--s0-file` does not bypass that fail-closed guard. Every preflight writes the final `preregistration.json` once and records its exact UTF-8 SHA-256 in the adjacent `preregistration.sha256` sidecar.

On 2026-08-25 the configured data entry was an inaccessible link and no local train `game.tw-pddl` files were available, so no dynamic Stage 0 result was fabricated.
