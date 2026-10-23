"""Tests for the read-only Ali-Control evidence collector; all HTTP is mocked."""
import base64
import hashlib
import json
import unittest
from unittest.mock import patch

import ali_control_reader as reader


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


class FakeResponse:
    status = 200
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.payload


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40
        self.contents = {
            path: (f"approved reference {path}\n".encode())
            for path in reader.REQUIRED_PATHS
        }
        self.tree = {
            "sha": "tree-sha",
            "truncated": False,
            "tree": [
                {"path": path, "type": "blob", "sha": blob_sha(content)}
                for path, content in self.contents.items()
            ],
        }
        self.latest_head = self.head
        self.fail_path = None
        self.changed_content = False

    def fake_urlopen(self, request, timeout=10.0):
        url = request.full_url
        if url.endswith("/commits/main"):
            return FakeResponse({"sha": self.latest_head})
        if "/git/trees/" in url:
            return FakeResponse(self.tree)
        if "/contents/" in url:
            path_and_query = url.split("/contents/", 1)[1]
            path = path_and_query.split("?")[0]
            if path == self.fail_path:
                raise OSError("simulated unavailable source")
            content = self.contents[path]
            if self.changed_content and path == reader.REQUIRED_PATHS[0]:
                content = b"tampered content"
            return FakeResponse({
                "type": "file",
                "encoding": "base64",
                "sha": blob_sha(content),
                "content": base64.b64encode(content).decode(),
            })
        raise AssertionError("Unexpected URL: " + url)

    def collect(self):
        with patch.object(reader, "urlopen", side_effect=self.fake_urlopen):
            return reader.collect_evidence()

    def test_git_blob_sha_matches_canonical_git_header(self):
        self.assertEqual(reader.git_blob_sha(b"hello\n"), blob_sha(b"hello\n"))

    def test_all_sources_verified_but_approval_still_required(self):
        report = self.collect()
        self.assertEqual(report.decision, "REQUIRE_APPROVAL")
        self.assertFalse(report.authorization_established)
        self.assertEqual(len(report.sources), 3)
        self.assertTrue(all(item.verified for item in report.sources))

    def test_missing_tree_source_denied(self):
        self.tree["tree"] = self.tree["tree"][:-1]
        report = self.collect()
        self.assertEqual(report.decision, "DENY")
        self.assertFalse(report.authorization_established)
        self.assertTrue(any(item.status == "MISSING" for item in report.sources))

    def test_content_hash_mismatch_denied(self):
        self.changed_content = True
        report = self.collect()
        self.assertEqual(report.decision, "DENY")
        self.assertTrue(any("Blob SHA" in error for error in report.errors))

    def test_unavailable_source_denied(self):
        self.fail_path = reader.REQUIRED_PATHS[1]
        report = self.collect()
        self.assertEqual(report.decision, "DENY")
        self.assertTrue(any(item.status == "UNVERIFIED" for item in report.sources))

    def test_head_movement_during_collection_denied(self):
        calls = 0
        original = self.fake_urlopen
        def moving(request, timeout=10.0):
            nonlocal calls
            if request.full_url.endswith("/commits/main"):
                calls += 1
                if calls == 2:
                    self.latest_head = "b" * 40
            return original(request, timeout)
        with patch.object(reader, "urlopen", side_effect=moving):
            report = reader.collect_evidence()
        self.assertEqual(report.decision, "DENY")
        self.assertTrue(any("moved during collection" in error for error in report.errors))

    def test_json_report_is_serializable(self):
        self.assertIn('"authorization_established": false', json.dumps(self.collect().to_dict()))


if __name__ == "__main__":
    unittest.main()
