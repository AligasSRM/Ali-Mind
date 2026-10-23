# Ali-Control ↔ Ali-Mind Link Verification

**Checked:** 2026-10-23  
**Repository under change:** `AligasSRM/Ali-Mind`, branch `main`  
**Reference repository:** `AligasSRM/Ali-Control`, read-only  
**Current verification scope:** read-only live source check plus policy-gate binding tests.

## Implementation added

- `evaluate_with_live_control(snapshot, request)` runs the read-only Ali-Control reader before evaluating the request.
- It fails closed unless the report has status `REQUIRE_APPROVAL`, contains exactly the three approved sources, and every source is verified against the same live `Ali-Control/main` commit.
- It requires `snapshot.evidence_ref` to equal `ali-control:<live-head-sha>`; stale or unrelated evidence references are denied.
- The ordinary policy checks still run after the live evidence binding. Forbidden actions remain denied, and write/document requests still require an explicit approval reference.
- `test_live_control_binding.py` covers successful binding and fail-closed cases.
- `.github/workflows/tests.yml` now runs the unit tests and `verify_live_control.py`. The live check performs GET requests only and prints evidence metadata, not source contents.

## Verified evidence

The GitHub Actions run for commit `5c0eaa3851d8d5f0c69a91e4975e00e28eb32bf6` completed successfully:

- Unit tests: **25 passed**.
- Live source verification: **PASS**.
- Ali-Control `main` observed by the live check: `11a61ddb5b52a5696d530cf262ace7fd0b426c67`.
- All three approved sources were fetched at that same commit and their Git Blob SHAs verified.
- Reader result: `REQUIRE_APPROVAL`. This is expected: source integrity does not grant permission to perform an operation.
- No write, merge, delete, permission change, or protection change was performed in Ali-Control.

Run evidence: https://github.com/AligasSRM/Ali-Mind/actions/runs/39964166297

## Important remaining boundary

Ali-Control currently exposes these references as Markdown and CODEOWNERS, not as a dedicated machine-readable policy/approval contract. Therefore:

- The live wrapper proves the approved sources are reachable, intact, and pinned to a stable HEAD, and binds a policy evaluation to that exact HEAD.
- Project-specific fields in `ControlSnapshot` (objective, phase, allowed paths, checkpoint, and operation approval references) are still supplied by the caller; they are **not automatically parsed or proven to originate from the Markdown sources**.
- The live check does not constitute approval for a particular write operation.
- The low-level `evaluate()` function remains a policy-only evaluator; callers requiring a live link must use `evaluate_with_live_control()`.

Accordingly, the **live-source and gate-binding conditions are verified**, but a claim that all policy fields are automatically derived from Ali-Control evidence would be unsupported. Full end-to-end closure requires an approved, machine-readable contract or a separately reviewed deterministic mapping for those fields, without changing Ali-Control in this task. Until then, do not describe the entire control relationship as fully closed.
