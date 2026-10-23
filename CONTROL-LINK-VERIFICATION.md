# Ali-Control ↔ Ali-Mind Link Verification

**Updated:** 2026-10-23  
**Repository under change:** `AligasSRM/Ali-Mind`, branch `main`  
**Reference repository:** `AligasSRM/Ali-Control`, read-only

## Decision that resolves the authority gap

Ali-Control's approved sources are Markdown and CODEOWNERS. They do not provide a machine-readable policy contract or a trusted operation-specific approval interface for the objective, active phase, allowed paths, checkpoint, and approval references expected by Ali-Mind.

**Resolution: fail closed; do not infer or invent policy authority.** Live source integrity alone must never grant `ALLOW` based on caller-supplied `ControlSnapshot` fields.

The live wrapper `evaluate_with_live_control()` now:
1. Fetches the approved Ali-Control sources read-only and verifies the Git Blob SHAs at one stable `main` HEAD.
2. Requires the exact approved source set and binds `snapshot.evidence_ref` to `ali-control:<verified-head-sha>`.
3. Denies missing, stale, inconsistent, or unverified evidence.
4. Keeps explicitly forbidden actions denied.
5. Returns `REQUIRE_APPROVAL` rather than `ALLOW` when the consistency checks pass but the trusted machine-readable policy/operation-approval contract is absent. Caller-supplied approval references do not bypass this rule.

The lower-level `evaluate()` function performs consistency checks on supplied fields only. Its `ALLOW` result is **not live authorization** and must not be used as a substitute for `evaluate_with_live_control()` in an operational path.

## Automated verification

GitHub Actions workflow `.github/workflows/tests.yml` runs:
- `python -m unittest discover -v`
- `python verify_live_control.py` against the real GitHub API, using read-only GET requests.

The earlier live verification run `39964166297` passed 25 tests and verified these three sources at the same Ali-Control HEAD `11a61ddb5b52a5696d530cf262ace7fd0b426c67`:
- `README.md`
- `docs/CONTROL-STATUS-AND-ROADMAP.md`
- `.github/CODEOWNERS`

The new tests additionally require fail-closed behavior when source authority is missing, including an attempt to use a caller-invented approval reference. The current workflow must pass again after this policy change before the updated revision is considered verified.

## Scope and safety

- Only `AligasSRM/Ali-Mind` on its existing `main` branch was changed.
- `AligasSRM/Ali-Control` was read only; no writes, merges, deletions, permission changes, or protection changes were made there.
- No phase status was changed and no new project phase was opened.
- Source integrity is not approval to perform a particular operation.
- Full automatic policy-based authorization remains intentionally unavailable until an approved structured policy/approval contract exists. That is now a defined fail-closed outcome, not an implicit authorization gap.
