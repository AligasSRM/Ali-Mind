"""Fail-closed policy gate for Ali-Mind operations.

The live wrapper verifies read-only Ali-Control source integrity. Because Ali-Control
currently has no machine-readable policy/operation-approval contract, live source
verification alone must never turn caller-supplied policy fields into authorization.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ALLOWED_REPOSITORY = "AligasSRM/Ali-Mind"
ALLOWED_BRANCH = "main"
CONTROL_EVIDENCE_PREFIX = "ali-control:"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class ControlSnapshot:
    """Caller-supplied policy fields; not an authority source by themselves."""

    source: str
    evidence_ref: str
    verified: bool
    repository: str
    branch: str
    objective: str
    active_phase: str
    phase_sequence: Tuple[str, ...]
    allowed_paths: FrozenSet[str]
    approved_decisions: FrozenSet[str]
    observed_head_sha: str
    historical_checkpoint_sha: str


@dataclass(frozen=True)
class OperationRequest:
    action: str
    repository: str
    branch: str
    objective: str
    phase: str
    paths: Tuple[str, ...]
    expected_head_sha: str
    decision_ref: str = ""


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    reason: str
    checks: Tuple[str, ...]


_FORBIDDEN_ACTIONS = frozenset({
    "delete", "rollback", "change_protection", "change_permissions",
    "create_branch", "merge",
})


class ResumeStatus(str, Enum):
    """Read-only result of comparing the saved checkpoint with the current HEAD."""

    AT_CHECKPOINT = "AT_CHECKPOINT"
    HEAD_DIVERGED = "HEAD_DIVERGED"
    DENY = "DENY"


@dataclass(frozen=True)
class ResumeContext:
    """Context needed to resume work; never performs a Git checkout or rollback."""

    status: ResumeStatus
    repository: str
    branch: str
    checkpoint_sha: str
    observed_head_sha: str
    objective: str
    active_phase: str
    phase_sequence: Tuple[str, ...]
    allowed_paths: FrozenSet[str]
    next_step: str
    reason: str


def prepare_resume_context(
    snapshot: Optional[ControlSnapshot],
    current_head_sha: str,
) -> ResumeContext:
    """Recover the approved work context and compare refs without changing Git.

    A divergent HEAD is not reset. The result preserves the historical checkpoint
    and tells the caller to inspect the difference before resuming.
    """
    if snapshot is None:
        return ResumeContext(
            ResumeStatus.DENY, ALLOWED_REPOSITORY, ALLOWED_BRANCH, "", "",
            "", "", (), frozenset(), "stop", "Missing checkpoint context.",
        )

    required = (
        snapshot.source,
        snapshot.evidence_ref,
        snapshot.historical_checkpoint_sha,
        snapshot.observed_head_sha,
        snapshot.objective,
        snapshot.active_phase,
    )
    if not all(required):
        return ResumeContext(
            ResumeStatus.DENY, snapshot.repository, snapshot.branch,
            snapshot.historical_checkpoint_sha, snapshot.observed_head_sha,
            snapshot.objective, snapshot.active_phase, snapshot.phase_sequence,
            snapshot.allowed_paths, "stop", "Checkpoint context is incomplete.",
        )
    if not snapshot.verified:
        return ResumeContext(
            ResumeStatus.DENY, snapshot.repository, snapshot.branch,
            snapshot.historical_checkpoint_sha, snapshot.observed_head_sha,
            snapshot.objective, snapshot.active_phase, snapshot.phase_sequence,
            snapshot.allowed_paths, "stop", "Checkpoint evidence is not marked verified.",
        )
    if not snapshot.phase_sequence or snapshot.active_phase not in snapshot.phase_sequence or not snapshot.allowed_paths:
        return ResumeContext(
            ResumeStatus.DENY, snapshot.repository, snapshot.branch,
            snapshot.historical_checkpoint_sha, snapshot.observed_head_sha,
            snapshot.objective, snapshot.active_phase, snapshot.phase_sequence,
            snapshot.allowed_paths, "stop", "Checkpoint phase or allowed-path context is incomplete.",
        )
    if snapshot.repository != ALLOWED_REPOSITORY or snapshot.branch != ALLOWED_BRANCH:
        return ResumeContext(
            ResumeStatus.DENY, snapshot.repository, snapshot.branch,
            snapshot.historical_checkpoint_sha, snapshot.observed_head_sha,
            snapshot.objective, snapshot.active_phase, snapshot.phase_sequence,
            snapshot.allowed_paths, "stop", "Checkpoint is outside the permitted repository or branch.",
        )
    if not current_head_sha or current_head_sha != snapshot.observed_head_sha:
        return ResumeContext(
            ResumeStatus.DENY, snapshot.repository, snapshot.branch,
            snapshot.historical_checkpoint_sha, snapshot.observed_head_sha,
            snapshot.objective, snapshot.active_phase, snapshot.phase_sequence,
            snapshot.allowed_paths, "recheck_current_head",
            "The supplied current HEAD does not match the observed HEAD in the snapshot.",
        )

    if current_head_sha == snapshot.historical_checkpoint_sha:
        return ResumeContext(
            ResumeStatus.AT_CHECKPOINT, snapshot.repository, snapshot.branch,
            snapshot.historical_checkpoint_sha, current_head_sha,
            snapshot.objective, snapshot.active_phase, snapshot.phase_sequence,
            snapshot.allowed_paths, "resume_from_checkpoint_context",
            "Current HEAD matches the historical checkpoint; no Git mutation was performed.",
        )
    return ResumeContext(
        ResumeStatus.HEAD_DIVERGED, snapshot.repository, snapshot.branch,
        snapshot.historical_checkpoint_sha, current_head_sha,
        snapshot.objective, snapshot.active_phase, snapshot.phase_sequence,
        snapshot.allowed_paths, "compare_current_head_with_checkpoint",
        "Current HEAD differs from the historical checkpoint. Preserve both references; compare the difference and resume context without resetting or rewriting Git.",
    )


class CheckpointComparisonStatus(str, Enum):
    MATCHES = "MATCHES"
    DIFFERS = "DIFFERS"
    DENY = "DENY"


@dataclass(frozen=True)
class CheckpointComparison:
    """Read-only comparison of a historical checkpoint against live main."""

    status: CheckpointComparisonStatus
    checkpoint_sha: str
    current_head_sha: str
    ahead_by: int
    behind_by: int
    changed_paths: Tuple[str, ...]
    reason: str


def _request_github_json(url: str, timeout: float = 10.0) -> dict:
    """Perform a read-only GitHub API GET and require a JSON object response."""
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Ali-Mind-checkpoint-reader",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        if getattr(response, "status", 200) != 200:
            raise ValueError("GitHub returned a non-200 response.")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub returned an unexpected JSON response.")
    return payload


def compare_checkpoint_changes(
    snapshot: Optional[ControlSnapshot],
    current_head_sha: str,
    timeout: float = 10.0,
) -> CheckpointComparison:
    """Compare the pinned historical checkpoint with live Ali-Mind/main, read-only.

    The live branch head must match the supplied current HEAD and the snapshot.
    The function reports changed paths and ahead/behind counts; it never changes
    files, checks out a commit, or rewrites Git history.
    """
    context = prepare_resume_context(snapshot, current_head_sha)
    checkpoint_sha = context.checkpoint_sha
    if context.status == ResumeStatus.DENY:
        return CheckpointComparison(
            CheckpointComparisonStatus.DENY, checkpoint_sha, current_head_sha,
            0, 0, (), context.reason,
        )
    if not re.fullmatch(r"[0-9a-fA-F]{40}", checkpoint_sha or "") or not re.fullmatch(
        r"[0-9a-fA-F]{40}", current_head_sha or ""
    ):
        return CheckpointComparison(
            CheckpointComparisonStatus.DENY, checkpoint_sha, current_head_sha,
            0, 0, (), "Checkpoint and current HEAD must be full 40-character Git SHAs.",
        )

    api_root = "https://api.github.com/repos/AligasSRM/Ali-Mind"
    try:
        live_head = _request_github_json(f"{api_root}/commits/main", timeout)
        live_sha = live_head.get("sha")
        if live_sha != current_head_sha:
            return CheckpointComparison(
                CheckpointComparisonStatus.DENY, checkpoint_sha, current_head_sha,
                0, 0, (), "Live main HEAD changed or does not match the supplied current HEAD; refresh the checkpoint context.",
            )
        if checkpoint_sha == current_head_sha:
            return CheckpointComparison(
                CheckpointComparisonStatus.MATCHES, checkpoint_sha, current_head_sha,
                0, 0, (), "Historical checkpoint matches live main HEAD; no Git mutation was performed.",
            )

        comparison = _request_github_json(
            f"{api_root}/compare/{checkpoint_sha}...{current_head_sha}", timeout
        )
        base = comparison.get("base_commit") or {}
        head = comparison.get("head_commit") or {}
        if base.get("sha") != checkpoint_sha or head.get("sha") != current_head_sha:
            return CheckpointComparison(
                CheckpointComparisonStatus.DENY, checkpoint_sha, current_head_sha,
                0, 0, (), "GitHub comparison did not return the exact requested checkpoint and HEAD.",
            )
        files = comparison.get("files") or []
        changed_paths = tuple(
            item["filename"] for item in files
            if isinstance(item, dict) and isinstance(item.get("filename"), str)
        )
        ahead_by = comparison.get("ahead_by")
        behind_by = comparison.get("behind_by")
        if not isinstance(ahead_by, int) or not isinstance(behind_by, int):
            return CheckpointComparison(
                CheckpointComparisonStatus.DENY, checkpoint_sha, current_head_sha,
                0, 0, (), "GitHub comparison omitted valid ahead/behind counts.",
            )
        return CheckpointComparison(
            CheckpointComparisonStatus.DIFFERS, checkpoint_sha, current_head_sha,
            ahead_by, behind_by, changed_paths,
            "Read-only comparison completed. Resume from the saved work context; do not reset or rewrite Git.",
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return CheckpointComparison(
            CheckpointComparisonStatus.DENY, checkpoint_sha, current_head_sha,
            0, 0, (), f"Read-only checkpoint comparison failed: {type(exc).__name__}: {exc}",
        )


def evaluate(snapshot: Optional[ControlSnapshot], request: OperationRequest) -> GateResult:
    """Evaluate supplied fields as consistency checks only; not a live authorization."""
    checks = []
    if snapshot is None:
        return GateResult(Decision.DENY, "Missing control snapshot; fail closed.", ("control_snapshot_present",))

    required = {
        "source": snapshot.source, "evidence_ref": snapshot.evidence_ref,
        "repository": snapshot.repository, "branch": snapshot.branch,
        "objective": snapshot.objective, "active_phase": snapshot.active_phase,
        "observed_head_sha": snapshot.observed_head_sha,
        "historical_checkpoint_sha": snapshot.historical_checkpoint_sha,
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        return GateResult(Decision.DENY, "Control snapshot is incomplete: " + ", ".join(missing) + ".", ("control_snapshot_complete",))
    checks.append("control_snapshot_complete")

    if not snapshot.verified:
        return GateResult(Decision.DENY, "Control evidence has not been verified.", tuple(checks + ["control_evidence_verified"]))
    checks.append("control_evidence_verified")

    if snapshot.repository != ALLOWED_REPOSITORY or request.repository != ALLOWED_REPOSITORY:
        return GateResult(Decision.DENY, "Only AligasSRM/Ali-Mind is in scope.", tuple(checks + ["repository_scope"]))
    if snapshot.branch != ALLOWED_BRANCH or request.branch != ALLOWED_BRANCH:
        return GateResult(Decision.DENY, "Only the existing main branch is in scope.", tuple(checks + ["branch_scope"]))
    checks.extend(("repository_scope", "branch_scope"))

    if request.action in _FORBIDDEN_ACTIONS:
        return GateResult(Decision.DENY, f"Action '{request.action}' is prohibited by this gate.", tuple(checks + ["action_policy"]))
    if request.action not in {"read", "write", "test", "document"}:
        return GateResult(Decision.DENY, f"Unknown action '{request.action}'; fail closed.", tuple(checks + ["action_policy"]))
    checks.append("action_policy")

    if not request.objective or request.objective != snapshot.objective:
        return GateResult(Decision.DENY, "Request objective is missing or differs from the supplied snapshot.", tuple(checks + ["objective_match"]))
    checks.append("objective_match")

    if request.phase != snapshot.active_phase:
        if request.phase in snapshot.phase_sequence and snapshot.active_phase in snapshot.phase_sequence:
            return GateResult(Decision.REQUIRE_APPROVAL, "Phase differs from the supplied active phase; explicit approval is required.", tuple(checks + ["phase_match"]))
        return GateResult(Decision.DENY, "Requested phase is absent from the supplied phase sequence.", tuple(checks + ["phase_sequence"]))
    if not snapshot.phase_sequence or snapshot.active_phase not in snapshot.phase_sequence:
        return GateResult(Decision.DENY, "Supplied phase sequence is missing or inconsistent.", tuple(checks + ["phase_sequence"]))
    checks.extend(("phase_sequence", "phase_match"))

    if not request.paths:
        return GateResult(Decision.DENY, "No target path supplied; fail closed.", tuple(checks + ["path_scope"]))
    outside = sorted(set(request.paths) - set(snapshot.allowed_paths))
    if outside:
        return GateResult(Decision.DENY, "Target path outside the supplied allowed set: " + ", ".join(outside), tuple(checks + ["path_scope"]))
    if any(path.startswith("/") or ".." in path.split("/") or "\\" in path for path in request.paths):
        return GateResult(Decision.DENY, "Unsafe or non-repository-relative path supplied.", tuple(checks + ["path_safety"]))
    checks.extend(("path_scope", "path_safety"))

    if not request.expected_head_sha or request.expected_head_sha != snapshot.observed_head_sha:
        return GateResult(Decision.DENY, "Expected branch head does not match the supplied observed head.", tuple(checks + ["head_match"]))
    checks.append("head_match")

    if request.action in {"write", "document"}:
        if not request.decision_ref or request.decision_ref not in snapshot.approved_decisions:
            return GateResult(Decision.REQUIRE_APPROVAL, "No matching explicit approval decision reference was supplied.", tuple(checks + ["approval_reference"]))
        checks.append("approval_reference")

    return GateResult(Decision.ALLOW, "Consistency checks passed only; this result is not a live authorization.", tuple(checks + ["consistency_only_no_side_effects"]))


def evaluate_with_live_control(
    snapshot: Optional[ControlSnapshot],
    request: OperationRequest,
    timeout: float = 10.0,
) -> GateResult:
    """Verify live sources, then fail closed on absent machine-readable policy authority.

    Ali-Control's approved sources are Markdown and CODEOWNERS, not a structured
    policy/operation-approval contract. Therefore caller-supplied snapshot fields
    cannot be promoted to ALLOW solely because the source files are intact.
    """
    from ali_control_reader import SOURCE_PATHS, read_control_evidence

    if snapshot is None:
        return GateResult(Decision.DENY, "Missing control snapshot; live evidence cannot be bound.", ("control_snapshot_present",))
    report = read_control_evidence(timeout=timeout)
    if report.status != "REQUIRE_APPROVAL":
        return GateResult(Decision.DENY, "Live Ali-Control evidence could not be verified: " + report.detail, ("live_control_evidence_verified",))
    if len(report.sources) != len(SOURCE_PATHS) or tuple(item.path for item in report.sources) != SOURCE_PATHS:
        return GateResult(Decision.DENY, "Live report does not contain exactly the approved source set.", ("live_control_source_set",))
    if not report.head_sha or any(
        not item.verified or item.commit_sha != report.head_sha or item.repository != "AligasSRM/Ali-Control" or item.branch != "main"
        for item in report.sources
    ):
        return GateResult(Decision.DENY, "Live evidence is incomplete or not pinned to one verified Ali-Control main HEAD.", ("live_control_evidence_consistent",))
    expected_ref = CONTROL_EVIDENCE_PREFIX + report.head_sha
    if snapshot.evidence_ref != expected_ref:
        return GateResult(Decision.DENY, "Snapshot evidence_ref is not bound to the live Ali-Control HEAD.", ("live_control_evidence_binding",))
    if not snapshot.verified:
        return GateResult(Decision.DENY, "Snapshot policy fields are not marked verified.", ("snapshot_policy_verified",))

    result = evaluate(snapshot, request)
    checks = ("live_control_evidence_verified", "live_control_source_set", "live_control_evidence_consistent", "live_control_evidence_binding") + result.checks
    if result.decision != Decision.ALLOW:
        return GateResult(result.decision, result.reason, checks)

    return GateResult(
        Decision.REQUIRE_APPROVAL,
        "Live source integrity is verified, but Ali-Control has no machine-readable policy/operation-approval contract. Caller-supplied phase, paths, checkpoint, and decision fields cannot authorize this request. No operation was executed.",
        checks + ("machine_readable_policy_authority_missing", "fail_closed_no_automatic_allow"),
    )
