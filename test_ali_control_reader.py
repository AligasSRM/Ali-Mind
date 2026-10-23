"""Tests for path-only Ali-Control verification; all HTTP is mocked."""
import json
import unittest
from unittest.mock import patch

import ali_control_reader as reader


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40
        self.metadata = {
            "full_name": reader.CONTROL_REPOSITORY,
            "archived": False,
        }
        self.commit = {"sha": self.head}
        self.requested_urls = []

    def fake_urlopen(self, request, timeout=10.0):
        url = request.full_url
        self.requested_urls.append(url)

        if url.endswith(f"/repos/{reader.CONTROL_REPOSITORY}"):
            return FakeResponse(self.metadata)

        if url.endswith(
            f"/repos/{reader.CONTROL_REPOSITORY}/commits/{reader.CONTROL_BRANCH}"
        ):
            return FakeResponse(self.commit)

        raise AssertionError(f"Unexpected URL requested: {url}")

    def resolve(self):
        with patch.object(
            reader, "urlopen", side_effect=self.fake_urlopen
        ):
            return reader.resolve_control_path()

    def test_valid_repository_and_branch_verify_path(self):
        report = self.resolve()

        self.assertEqual(report.status, "PATH_VERIFIED")
        self.assertEqual(report.repository, "AligasSRM/Ali-Control")
        self.assertEqual(report.branch, "main")
        self.assertEqual(report.head_sha, self.head)
        self.assertEqual(
            report.repository_url,
            "https://github.com/AligasSRM/Ali-Control",
        )
        self.assertEqual(
            report.branch_url,
            "https://github.com/AligasSRM/Ali-Control/tree/main",
        )
        self.assertIn("does not authorize any operation", report.detail)

    def test_repository_identity_mismatch_is_unverified(self):
        self.metadata["full_name"] = "OtherOwner/OtherRepo"

        report = self.resolve()

        self.assertEqual(report.status, "PATH_UNVERIFIED")
        self.assertEqual(report.head_sha, "")
        self.assertEqual(len(self.requested_urls), 1)

    def test_archived_repository_is_unverified(self):
        self.metadata["archived"] = True

        report = self.resolve()

        self.assertEqual(report.status, "PATH_UNVERIFIED")
        self.assertEqual(len(self.requested_urls), 1)

    def test_invalid_commit_sha_is_unverified(self):
        self.commit["sha"] = "not-a-valid-sha"

        report = self.resolve()

        self.assertEqual(report.status, "PATH_UNVERIFIED")

    def test_missing_commit_sha_is_unverified(self):
        self.commit = {}

        report = self.resolve()

        self.assertEqual(report.status, "PATH_UNVERIFIED")

    def test_unavailable_endpoint_is_unverified(self):
        with patch.object(
            reader,
            "urlopen",
            side_effect=OSError("simulated network failure"),
        ):
            report = reader.resolve_control_path()

        self.assertEqual(report.status, "PATH_UNVERIFIED")
        self.assertIn("OSError", report.detail)

    def test_json_report_is_serializable(self):
        report = self.resolve()
        payload = json.loads(json.dumps(report.to_dict()))

        self.assertEqual(payload["status"], "PATH_VERIFIED")
        self.assertEqual(payload["head_sha"], self.head)
        self.assertIn("repository_url", payload)
        self.assertIn("branch_url", payload)

    def test_reader_only_requests_repository_and_branch_metadata(self):
        self.resolve()

        self.assertEqual(len(self.requested_urls), 2)
        self.assertTrue(
            all("/contents/" not in url for url in self.requested_urls)
        )
        self.assertTrue(
            all("/git/trees/" not in url for url in self.requested_urls)
        )
        self.assertTrue(
            all("/git/blobs/" not in url for url in self.requested_urls)
        )


if __name__ == "__main__":
    unittest.main()
