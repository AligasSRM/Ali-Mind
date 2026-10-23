"""Unit tests for the Ali-Mind consistency gate; no GitHub operations are performed."""
import unittest
from unittest.mock import patch

from ali_mind_guard import (
    CheckpointComparisonStatus, ControlSnapshot, Decision, OperationRequest,
    ResumeStatus, compare_checkpoint_changes, evaluate, prepare_resume_context,
)


def snapshot(**overrides):
    values = {
        "source": "caller-supplied-evidence",
        "evidence_ref": "evidence:review-001",
        "verified": True,
        "repository": "AligasSRM/Ali-Mind",
        "branch": "main",
        "objective": "Implement a local fail-closed policy gate",
        "active_phase": "A7",
        "phase_sequence": ("A1", "A2", "A3", "A4", "A5", "A6", "A7"),
        "allowed_paths": frozenset({"ali_mind_guard.py", "test_ali_mind_guard.py"}),
        "approved_decisions": frozenset({"decision-ref-001"}),
        "observed_head_sha": "current-head-sha",
        "historical_checkpoint_sha": "historical-checkpoint-sha",
    }
    values.update(overrides)
    return ControlSnapshot(**values)


def request(**overrides):
    values = {
        "action": "read", "repository": "AligasSRM/Ali-Mind", "branch": "main",
        "objective": "Implement a local fail-closed policy gate", "phase": "A7",
        "paths": ("ali_mind_guard.py",), "expected_head_sha": "current-head-sha",
    }
    values.update(overrides)
    return OperationRequest(**values)


class GateTests(unittest.TestCase):
    def test_missing_snapshot_fails_closed(self):
        self.assertEqual(evaluate(None, request()).decision, Decision.DENY)

    def test_unverified_control_evidence_fails_closed(self):
        self.assertEqual(evaluate(snapshot(verified=False), request()).decision, Decision.DENY)

    def test_other_repository_is_denied(self):
        self.assertEqual(evaluate(snapshot(), request(repository="AligasSRM/another-repo")).decision, Decision.DENY)

    def test_path_outside_allowlist_is_denied(self):
        self.assertEqual(evaluate(snapshot(), request(paths=("README.md",))).decision, Decision.DENY)

    def test_prohibited_rollback_is_denied(self):
        self.assertEqual(evaluate(snapshot(), request(action="rollback")).decision, Decision.DENY)

    def test_stale_or_missing_head_is_denied(self):
        self.assertEqual(evaluate(snapshot(), request(expected_head_sha="stale-head")).decision, Decision.DENY)

    def test_write_without_reference_requires_approval(self):
        self.assertEqual(evaluate(snapshot(), request(action="write")).decision, Decision.REQUIRE_APPROVAL)

    def test_write_with_reference_is_consistency_only(self):
        result = evaluate(snapshot(), request(action="write", decision_ref="decision-ref-001"))
        self.assertEqual(result.decision, Decision.ALLOW)
        self.assertIn("consistency_only_no_side_effects", result.checks)
        self.assertIn("not a live authorization", result.reason)

    def test_read_within_scope_is_consistency_only(self):
        result = evaluate(snapshot(), request())
        self.assertEqual(result.decision, Decision.ALLOW)
        self.assertIn("consistency_only_no_side_effects", result.checks)

    def test_historical_checkpoint_is_distinct_from_observed_head(self):
        control = snapshot()
        self.assertNotEqual(control.historical_checkpoint_sha, control.observed_head_sha)
        result = evaluate(control, request(expected_head_sha=control.observed_head_sha))
        self.assertEqual(result.decision, Decision.ALLOW)
        self.assertIn("not a live authorization", result.reason)


    def test_resume_context_returns_checkpoint_without_mutating_git(self):
        control = snapshot()
        result = prepare_resume_context(control, control.observed_head_sha)
        self.assertEqual(result.status, ResumeStatus.HEAD_DIVERGED)
        self.assertEqual(result.checkpoint_sha, control.historical_checkpoint_sha)
        self.assertEqual(result.observed_head_sha, control.observed_head_sha)
        self.assertEqual(result.next_step, "compare_current_head_with_checkpoint")
        self.assertIn("without resetting", result.reason)

    def test_resume_context_reports_when_head_matches_checkpoint(self):
        control = snapshot(historical_checkpoint_sha="current-head-sha")
        result = prepare_resume_context(control, control.observed_head_sha)
        self.assertEqual(result.status, ResumeStatus.AT_CHECKPOINT)
        self.assertEqual(result.next_step, "resume_from_checkpoint_context")

    def test_resume_context_rejects_stale_observed_head(self):
        control = snapshot()
        result = prepare_resume_context(control, "different-current-head")
        self.assertEqual(result.status, ResumeStatus.DENY)
        self.assertEqual(result.next_step, "recheck_current_head")

    def test_checkpoint_comparison_reports_changed_paths_read_only(self):
        checkpoint = "1" * 40
        head = "2" * 40
        control = snapshot(
            historical_checkpoint_sha=checkpoint,
            observed_head_sha=head,
        )
        responses = [
            {"sha": head},
            {
                "base_commit": {"sha": checkpoint},
                "head_commit": {"sha": head},
                "ahead_by": 2,
                "behind_by": 0,
                "files": [{"filename": "ali_mind_guard.py"}, {"filename": "test_ali_mind_guard.py"}],
            },
        ]
        with patch("ali_mind_guard._request_github_json", side_effect=responses):
            result = compare_checkpoint_changes(control, head)
        self.assertEqual(result.status, CheckpointComparisonStatus.DIFFERS)
        self.assertEqual(result.ahead_by, 2)
        self.assertEqual(result.behind_by, 0)
        self.assertEqual(result.changed_paths, ("ali_mind_guard.py", "test_ali_mind_guard.py"))
        self.assertIn("Read-only", result.reason)

    def test_checkpoint_comparison_reports_exact_checkpoint_match(self):
        head = "3" * 40
        control = snapshot(historical_checkpoint_sha=head, observed_head_sha=head)
        with patch("ali_mind_guard._request_github_json", return_value={"sha": head}):
            result = compare_checkpoint_changes(control, head)
        self.assertEqual(result.status, CheckpointComparisonStatus.MATCHES)
        self.assertEqual(result.changed_paths, ())

    def test_checkpoint_comparison_rejects_changed_live_head(self):
        checkpoint = "4" * 40
        observed = "5" * 40
        live = "6" * 40
        control = snapshot(historical_checkpoint_sha=checkpoint, observed_head_sha=observed)
        with patch("ali_mind_guard._request_github_json", return_value={"sha": live}):
            result = compare_checkpoint_changes(control, observed)
        self.assertEqual(result.status, CheckpointComparisonStatus.DENY)
        self.assertIn("Live main HEAD changed", result.reason)

    def test_resume_context_rejects_unverified_checkpoint(self):
        control = snapshot(verified=False)
        result = prepare_resume_context(control, control.observed_head_sha)
        self.assertEqual(result.status, ResumeStatus.DENY)
        self.assertEqual(result.next_step, "stop")

    def test_resume_context_rejects_other_repository(self):
        control = snapshot(repository="AligasSRM/another-repo")
        result = prepare_resume_context(control, control.observed_head_sha)
        self.assertEqual(result.status, ResumeStatus.DENY)
        self.assertEqual(result.next_step, "stop")

if __name__ == "__main__":
    unittest.main()
