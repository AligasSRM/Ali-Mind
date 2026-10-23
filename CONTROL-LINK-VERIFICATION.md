# Ali-Control ↔ Ali-Mind Link Verification

**Updated:** 2026-10-23  
**Repository under change:** `AligasSRM/Ali-Mind`, branch `main`  
**Reference repository:** `AligasSRM/Ali-Control`, read-only

## Official checkpoint — completed workstream

This section is the repository reference for the completed Ali-Mind scope as of commit `1ed10bdc0221c320f558f914b3d7ccab238bc2e6`.

Completed and verified within the approved scope:
- Work-direction consistency checks bind the request to the saved context's repository, branch, objective, phase, allowed paths, and observed HEAD.
- Read-only checkpoint resumption distinguishes the historical checkpoint SHA from the current HEAD and reports whether the context is at the checkpoint or the HEAD has diverged.
- Read-only checkpoint comparison verifies the live `Ali-Mind/main` HEAD and reports ahead/behind counts and changed paths without changing Git state.
- Tests cover checkpoint match/divergence, changed-path reporting, stale HEAD, incomplete/unverified context, and repository-scope rejection.
- The latest verification recorded for the implementation commit passed **34 tests** and the live read-only Ali-Control source verification.

**Checkpoint rule:** Treat the above workstream as complete for the current scope. Do not reopen, repeat, or expand these tasks unless a concrete, reproducible defect or a newly authorized requirement is identified. The checkpoint is a reference for resuming work, not a command to roll Git back to the historical SHA.

**Next-work boundary:** Start a separate, explicitly requested task from the current `Ali-Mind/main` state. Do not infer extra requirements or approvals, create a branch, or broaden the scope. Keep `Ali-Control` read-only. This checkpoint does not close A7 or establish operational authorization.

## Decision and required approval authority

Ali-Control's currently approved sources are Markdown and CODEOWNERS. They do not expose a verified machine-readable policy contract or a trusted operation-specific approval interface for the objective, active phase, allowed paths, checkpoint, and approval references expected by Ali-Mind.

**Decision: fail closed; do not infer, invent, or accept caller-supplied approval authority.** For an operation that requires approval, the required approval must come from a trusted, independently verifiable authority and must be bound to the specific operation and its scope. A string or reference supplied by the caller is not proof that an authorized reviewer approved that operation. The current Ali-Control sources do not provide the required machine-readable contract, so this repository cannot validate such an approval automatically.

Until that contract is explicitly approved and made available by the authority source, the live guard must return `REQUIRE_APPROVAL` after successful consistency checks; it must not return `ALLOW` on the strength of source integrity or caller-provided approval data alone. This document records the required authority boundary; it does not claim that a trusted approval interface already exists.

The live wrapper `evaluate_with_live_control()`:
1. Fetches the approved Ali-Control sources read-only and verifies their Git Blob SHAs at one stable `main` HEAD.
2. Requires the exact approved source set and binds `snapshot.evidence_ref` to `ali-control:<verified-head-sha>`.
3. Denies missing, stale, inconsistent, or unverified evidence.
4. Keeps explicitly forbidden actions denied.
5. Returns `REQUIRE_APPROVAL` rather than `ALLOW` when consistency checks pass but the trusted machine-readable policy/operation-approval contract is absent. Caller-supplied approval references do not bypass this rule.

The lower-level `evaluate()` function performs consistency checks on supplied fields only. Its `ALLOW` result is **not live authorization** and must not be used as a substitute for `evaluate_with_live_control()` in an operational path.

## Scoped work-direction and checkpoint-resume behavior

The local guard's `evaluate()` checks the supplied work request against the supplied context for repository, branch, objective, phase, allowed paths, and observed HEAD. It is a consistency gate, not proof that caller-supplied policy fields are authoritative. The live wrapper therefore continues to fail closed when Ali-Control lacks a trusted machine-readable operation-policy contract.

The read-only `prepare_resume_context(snapshot, current_head_sha)` function:
- rejects missing, incomplete, unverified, out-of-scope, or stale checkpoint context;
- preserves the historical checkpoint SHA separately from the observed current HEAD;
- returns `AT_CHECKPOINT` when both references match, or `HEAD_DIVERGED` when they differ;
- returns the saved objective, phase sequence, and allowed paths needed to resume the work context.

The read-only `compare_checkpoint_changes(snapshot, current_head_sha)` function verifies that live `Ali-Mind/main` still matches the supplied HEAD, then compares the historical checkpoint against that exact HEAD through GitHub's read-only compare endpoint. It returns ahead/behind counts and changed file paths, or fails closed if the live HEAD or comparison evidence is stale/inconsistent. Neither function checks out, resets, rewrites, or otherwise mutates Git.

## Automated verification and evidence

GitHub Actions workflow `.github/workflows/tests.yml` runs:
- `python -m unittest discover -v`
- `python verify_live_control.py` against the real GitHub API, using read-only GET requests.

Latest implementation verification recorded before this checkpoint documentation commit:
- Workflow run: **39968175841**
- Result: `completed` / `success`
- Unit tests: **34 passed**
- Live read-only Ali-Control source verification: passed

Run evidence: https://github.com/AligasSRM/Ali-Mind/actions/runs/39968175841

That run verifies the implementation revision it tested; it does **not** by itself verify this subsequent documentation commit. The resulting documentation commit must have its workflow result checked before this document is considered fully verified.

The live verification is limited to the approved Ali-Control sources:
- `README.md`
- `docs/CONTROL-STATUS-AND-ROADMAP.md`
- `.github/CODEOWNERS`

## Acceptance evidence and remaining boundary

Evidence currently established:
- The recorded implementation workflow completed successfully for unit tests and read-only live-source verification.
- The live verification is limited to the three approved Ali-Control sources listed above.
- The guard's documented decision remains fail-closed when trusted operation-specific approval authority is absent.
- No evidence in this report establishes that branch protection is enabled; access to the relevant protection endpoint was unavailable to the integration.
- No evidence here establishes that A7's formal project acceptance criteria have all been met.

Acceptance conditions still requiring evidence before claiming full operational authorization or formally closing A7:
1. A trusted, approved, machine-readable operation-specific policy/approval contract is provided by the authorized source; until then, `REQUIRE_APPROVAL` remains the correct outcome.
2. The workflow run for this checkpoint documentation commit completes successfully.
3. The project's formal A7 acceptance criteria are checked against evidence and an explicit closure decision is recorded.

## Scope and safety

- This documentation change is limited to this existing file in `AligasSRM/Ali-Mind` on its existing `main` branch.
- `AligasSRM/Ali-Control` remains read-only.
- No new branch is created.
- No branch protection, permissions, repository settings, or phase status are changed.
- No merge, deletion, rollback, or other repository change is performed.
- Source integrity is not approval to perform a particular operation.
- Full automatic policy-based authorization remains unavailable until an approved structured policy/approval contract exists.
