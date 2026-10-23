# Ali-Control ↔ Ali-Mind Link Verification

**Updated:** 2026-10-23  
**Repository under change:** `AligasSRM/Ali-Mind`, branch `main`  
**Reference repository:** `AligasSRM/Ali-Control`, read-only

## Decision and required approval authority

Ali-Control's currently approved sources are Markdown and CODEOWNERS. They do not expose a verified machine-readable policy contract or a trusted operation-specific approval interface for the objective, active phase, allowed paths, checkpoint, and approval references expected by Ali-Mind.

**Decision: fail closed; do not infer, invent, or accept caller-supplied approval authority.**

For an operation that requires approval, the required approval must come from a trusted, independently verifiable authority and must be bound to the specific operation and its scope. A string or reference supplied by the caller is not proof that an authorized reviewer approved that operation. The current Ali-Control sources do not provide the required machine-readable contract, so this repository cannot validate such an approval automatically.

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

The read-only `prepare_resume_context(snapshot, current_head_sha)` function now:
- rejects missing, incomplete, out-of-scope, or stale checkpoint context;
- preserves the historical checkpoint SHA separately from the observed current HEAD;
- returns `AT_CHECKPOINT` when both references match, or `HEAD_DIVERGED` when they differ;
- returns the saved objective, phase sequence, and allowed paths needed to resume the work context;
- instructs the caller to compare the current HEAD with the checkpoint when they differ; it never checks out, resets, rewrites, or otherwise mutates Git.

The tests in `test_ali_mind_guard.py` cover matching and divergent checkpoint references, stale HEAD context, and repository-scope rejection. These tests validate the local context decision only; they do not establish a trusted structured Ali-Control policy source or live authorization.

## Automated verification and evidence

GitHub Actions workflow `.github/workflows/tests.yml` runs:
- `python -m unittest discover -v`
- `python verify_live_control.py` against the real GitHub API, using read-only GET requests.

The latest verified run before this documentation update was **39964750173**:
- Workflow job: `Python unit tests and live control link`
- Job conclusion: `success`
- `Run unit tests`: `success`
- `Verify live Ali-Control sources (read-only)`: `success`

Run evidence: https://github.com/AligasSRM/Ali-Mind/actions/runs/39964750173

An earlier live verification run, `39964166297`, passed 25 tests and verified these three sources at the same Ali-Control HEAD `11a61ddb5b52a5696d530cf262ace7fd0b426c67`:
- `README.md`
- `docs/CONTROL-STATUS-AND-ROADMAP.md`
- `.github/CODEOWNERS`

Run `39964750173` supersedes the earlier statement that a successful run was still pending for the policy/test update. Its successful result is evidence for that tested revision, **not** evidence that a subsequent documentation commit has passed. The workflow must run against the resulting commit, and its actual result must be checked before that commit is marked verified.

## Acceptance evidence and remaining boundary

Evidence currently established:
- The recorded workflow run completed successfully for unit tests and read-only live-source verification.
- The live verification is limited to the three approved Ali-Control sources listed above.
- The guard's documented decision remains fail-closed when trusted operation-specific approval authority is absent.
- No evidence in this report establishes that branch protection is enabled; access to the relevant protection endpoint was unavailable to the integration.
- No evidence here establishes that A7's formal project acceptance criteria have all been met.

Acceptance conditions still requiring evidence before claiming full operational authorization or formally closing A7:
1. A trusted, approved, machine-readable operation-specific policy/approval contract is provided by the authorized source; until then, `REQUIRE_APPROVAL` remains the correct outcome.
2. The workflow run for the resulting documentation commit completes successfully.
3. The project's formal A7 acceptance criteria are checked against evidence and an explicit closure decision is recorded.

## Scope and safety

- The only intended write for this task is this verification document in `AligasSRM/Ali-Mind` on its existing `main` branch.
- `AligasSRM/Ali-Control` remains read-only.
- No new branch is created.
- No branch protection, permissions, repository settings, or phase status are changed.
- No merge, deletion, rollback, or other repository change is performed.
- Source integrity is not approval to perform a particular operation.
- Full automatic policy-based authorization remains unavailable until an approved structured policy/approval contract exists.
