"""Fail-closed policy gate for Ali-Mind operations.

This module evaluates requests only. It never performs the requested operation.
The live wrapper binds a policy decision to verified, read-only evidence fetched
from the approved Ali-Control repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Tuple

ALLOWED_REPOSITORY = "AligasSRM/Ali-Mind"
ALLOWED_BRANCH = "main"
CONTROL_EVIDENCE_PREFIX = "ali-control:"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class ControlSnapshot:
    """Project-specific control contract; live evidence binding is checked separately."""

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


def evaluate(snapshot: Optional[ControlSnapshot], request: OperationRequest) -> GateResult:
    """Evaluate caller-supplied policy fields only; does not prove live control linkage."""
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
        return GateResult(Decision.DENY, "Request objective is missing or differs from the controlled objective.", tuple(checks + ["objective_match"]))
    checks.append("objective_match")

    if request.phase != snapshot.active_phase:
        if request.phase in snapshot.phase_sequence and snapshot.active_phase in snapshot.phase_sequence:
            return GateResult(Decision.REQUIRE_APPROVAL, "Phase differs from the active controlled phase; explicit approval is required.", tuple(checks + ["phase_match"]))
        return GateResult(Decision.DENY, "Requested phase is absent from the controlled phase sequence.", tuple(checks + ["phase_sequence"]))
    if not snapshot.phase_sequence or snapshot.active_phase not in snapshot.phase_sequence:
        return GateResult(Decision.DENY, "Control phase sequence is missing or inconsistent.", tuple(checks + ["phase_sequence"]))
    checks.extend(("phase_sequence", "phase_match"))

    if not request.paths:
        return GateResult(Decision.DENY, "No target path supplied; fail closed.", tuple(checks + ["path_scope"]))
    outside = sorted(set(request.paths) - set(snapshot.allowed_paths))
    if outside:
        return GateResult(Decision.DENY, "Target path outside the explicitly allowed set: " + ", ".join(outside), tuple(checks + ["path_scope"]))
    if any(path.startswith("/") or ".." in path.split("/") or "\\" in path for path in request.paths):
        return GateResult(Decision.DENY, "Unsafe or non-repository-relative path supplied.", tuple(checks + ["path_safety"]))
    checks.extend(("path_scope", "path_safety"))

    if not request.expected_head_sha or request.expected_head_sha != snapshot.observed_head_sha:
        return GateResult(Decision.DENY, "Expected branch head is missing or does not match the observed head.", tuple(checks + ["head_match"]))
    checks.append("head_match")

    if request.action in {"write", "document"}:
        if not request.decision_ref or request.decision_ref not in snapshot.approved_decisions:
            return GateResult(Decision.REQUIRE_APPROVAL, "No matching explicit approval decision reference was supplied.", tuple(checks + ["approval_reference"]))
        checks.append("approval_reference")

    return GateResult(Decision.ALLOW, "Policy checks passed. This is a decision only; no operation was executed.", tuple(checks + ["decision_only_no_side_effects"]))


def evaluate_with_live_control(
    snapshot: Optional[ControlSnapshot],
    request: OperationRequest,
    timeout: float = 10.0,
) -> GateResult:
    """Require fresh, verified Ali-Control evidence before evaluating any request.

    The live report proves source identity/integrity and a stable Ali-Control main
    HEAD. It does not itself define project-specific policy fields or grant approval.
    Those fields remain explicit in snapshot and are accepted only when its evidence
    reference is bound to the exact live HEAD observed in this call.
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
    return GateResult(
        result.decision,
        result.reason,
        ("live_control_evidence_verified", "live_control_source_set", "live_control_evidence_consistent", "live_control_evidence_binding") + result.checks,
    )
