"""Tests for live source binding and fail-closed policy authority."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ali_mind_guard import (
    CONTROL_EVIDENCE_PREFIX, ControlSnapshot, Decision, OperationRequest,
    evaluate_with_live_control,
)
from ali_control_reader import SOURCE_PATHS

HEAD = "1" * 40


def live_report(status="REQUIRE_APPROVAL", head=HEAD, paths=SOURCE_PATHS, verified=True):
    sources = tuple(SimpleNamespace(
        path=path, verified=verified, commit_sha=head,
        repository="AligasSRM/Ali-Control", branch="main",
    ) for path in paths)
    return SimpleNamespace(status=status, head_sha=head, sources=sources, detail="test report")


def make_snapshot(**overrides):
    values = dict(
        source="caller-supplied",
        evidence_ref=CONTROL_EVIDENCE_PREFIX + HEAD,
        verified=True,
        repository="AligasSRM/Ali-Mind",
        branch="main",
        objective="Read-only integration verification",
        active_phase="A7",
        phase_sequence=("A1", "A2", "A3", "A4", "A5", "A6", "A7"),
        allowed_paths=frozenset({"ali_mind_guard.py"}),
        approved_decisions=frozenset({"invented-approval"}),
        observed_head_sha="current-head",
        historical_checkpoint_sha="historical-checkpoint",
    )
    values.update(overrides)
    return ControlSnapshot(**values)


def make_request(**overrides):
    values = dict(
        action="read", repository="AligasSRM/Ali-Mind", branch="main",
        objective="Read-only integration verification", phase="A7",
        paths=("ali_mind_guard.py",), expected_head_sha="current-head",
    )
    values.update(overrides)
    return OperationRequest(**values)


class LiveBindingTests(unittest.TestCase):
    def test_verified_sources_do_not_turn_caller_snapshot_into_authorization(self):
        with patch("ali_control_reader.read_control_evidence", return_value=live_report()):
            result = evaluate_with_live_control(make_snapshot(), make_request())
        self.assertEqual(result.decision, Decision.REQUIRE_APPROVAL)
        self.assertIn("live_control_evidence_verified", result.checks)
        self.assertIn("live_control_evidence_binding", result.checks)
        self.assertIn("machine_readable_policy_authority_missing", result.checks)

    def test_snapshot_with_unbound_or_stale_head_is_denied(self):
        with patch("ali_control_reader.read_control_evidence", return_value=live_report()):
            result = evaluate_with_live_control(
                make_snapshot(evidence_ref=CONTROL_EVIDENCE_PREFIX + "2" * 40),
                make_request(),
            )
        self.assertEqual(result.decision, Decision.DENY)
        self.assertIn("live Ali-Control HEAD", result.reason)

    def test_live_reader_denial_fails_closed(self):
        with patch("ali_control_reader.read_control_evidence", return_value=live_report(status="DENY")):
            result = evaluate_with_live_control(make_snapshot(), make_request())
        self.assertEqual(result.decision, Decision.DENY)
        self.assertIn("live_control_evidence_verified", result.checks)

    def test_missing_approved_source_fails_closed(self):
        with patch("ali_control_reader.read_control_evidence", return_value=live_report(paths=SOURCE_PATHS[:-1])):
            result = evaluate_with_live_control(make_snapshot(), make_request())
        self.assertEqual(result.decision, Decision.DENY)
        self.assertIn("approved source set", result.reason)

    def test_source_from_another_head_fails_closed(self):
        report = live_report()
        report.sources = report.sources[:-1] + (SimpleNamespace(
            path=SOURCE_PATHS[-1], verified=True, commit_sha="2" * 40,
            repository="AligasSRM/Ali-Control", branch="main",
        ),)
        with patch("ali_control_reader.read_control_evidence", return_value=report):
            result = evaluate_with_live_control(make_snapshot(), make_request())
        self.assertEqual(result.decision, Decision.DENY)

    def test_forbidden_action_remains_denied(self):
        with patch("ali_control_reader.read_control_evidence", return_value=live_report()):
            result = evaluate_with_live_control(make_snapshot(), make_request(action="delete"))
        self.assertEqual(result.decision, Decision.DENY)

    def test_caller_invented_approval_never_authorizes_write(self):
        with patch("ali_control_reader.read_control_evidence", return_value=live_report()):
            result = evaluate_with_live_control(
                make_snapshot(),
                make_request(action="write", decision_ref="invented-approval"),
            )
        self.assertEqual(result.decision, Decision.REQUIRE_APPROVAL)
        self.assertIn("machine-readable policy/operation-approval contract", result.reason)


if __name__ == "__main__":
    unittest.main()
