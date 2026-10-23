"""Tests for the live-source contract reader; all HTTP responses are mocked."""
import base64
import hashlib
import json
import unittest
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch

import ali_control_reader as reader


HEAD = "a" * 40
SOURCES = {
    "README.md": b"# control rules\n",
    "docs/CONTROL-STATUS-AND-ROADMAP.md": b"# phase status\n",
    ".github/CODEOWNERS": b"* @AligasSRM\n",
}


def blob_sha(raw):
    return hashlib.sha1(f"blob {len(raw)}\\0".encode("ascii") + raw).hexdigest()


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
        self.calls = []
        self.head_responses = [HEAD, HEAD]
        self.source_overrides = {}

    def fake_urlopen(self, request, timeout=10.0):
        url = request.full_url
        self.calls.append(url)
        parsed = urlparse(url)
        path = parsed.path

        if path == f"/repos/{reader.CONTROL_REPOSITORY}":
            return FakeResponse({"full_name": reader.CONTROL_REPOSITORY, "archived": False})

        if path == f"/repos/{reader.CONTROL_REPOSITORY}/commits/{reader.CONTROL_BRANCH}":
            if not self.head_responses:
                raise AssertionError("Unexpected extra HEAD request")
            return FakeResponse({"sha": self.head_responses.pop(0)})

        prefix = f"/repos/{reader.CONTROL_REPOSITORY}/contents/"
        if path.startswith(prefix):
            source_path = path[len(prefix):]
            requested_ref = parse_qs(parsed.query).get("ref", [""])[0]
            self.assertEqual(requested_ref, HEAD)
            raw = self.source_overrides.get(source_path, SOURCES.get(source_path))
            if raw is None:
                raise OSError("simulated missing source")
            return FakeResponse({
                "type": "file",
                "path": source_path,
                "sha": blob_sha(raw),
                "content": base64.b64encode(raw).decode("ascii"),
                "encoding": "base64",
            })

        raise AssertionError(f"Unexpected URL requested: {url}")

    def resolve(self):
        with patch.object(reader, "urlopen", side_effect=self.fake_urlopen):
            return reader.read_control_evidence()

    def test_all_sources_verified_at_stable_head_require_approval(self):
        report = self.resolve()
        self.assertEqual(report.status, "REQUIRE_APPROVAL")
        self.assertEqual(report.head_sha, HEAD)
        self.assertEqual([item.path for item in report.sources], list(reader.SOURCE_PATHS))
        self.assertTrue(all(item.verified for item in report.sources))
        self.assertTrue(all(item.commit_sha == HEAD for item in report.sources))
        self.assertIn("no operation was executed", report.detail)
        self.assertEqual(len([u for u in self.calls if "/contents/" in u]), 3)
        self.assertEqual(len([u for u in self.calls if "/commits/" in u]), 2)

    def test_repository_identity_mismatch_denies(self):
        def fake(request, timeout=10.0):
            return FakeResponse({"full_name": "someone/else", "archived": False})
        with patch.object(reader, "urlopen", side_effect=fake):
            report = reader.read_control_evidence()
        self.assertEqual(report.status, "DENY")
        self.assertIn("identity", report.detail)

    def test_archived_repository_denies(self):
        def fake(request, timeout=10.0):
            return FakeResponse({"full_name": reader.CONTROL_REPOSITORY, "archived": True})
        with patch.object(reader, "urlopen", side_effect=fake):
            report = reader.read_control_evidence()
        self.assertEqual(report.status, "DENY")
        self.assertIn("archived", report.detail)

    def test_missing_source_denies(self):
        self.source_overrides["README.md"] = None
        # Explicitly simulate a 404-like source failure.
        def fake(request, timeout=10.0):
            if request.full_url.endswith("/contents/README.md?ref=" + HEAD):
                raise OSError("404 Not Found")
            return self.fake_urlopen(request, timeout)
        with patch.object(reader, "urlopen", side_effect=fake):
            report = reader.read_control_evidence()
        self.assertEqual(report.status, "DENY")
        self.assertIn("OSError", report.detail)

    def test_blob_sha_mismatch_denies(self):
        def fake(request, timeout=10.0):
            url = request.full_url
            if "/contents/README.md?" in url:
                return FakeResponse({
                    "type": "file", "path": "README.md", "sha": "0" * 40,
                    "content": base64.b64encode(SOURCES["README.md"]).decode("ascii"),
                })
            return self.fake_urlopen(request, timeout)
        with patch.object(reader, "urlopen", side_effect=fake):
            report = reader.read_control_evidence()
        self.assertEqual(report.status, "DENY")
        self.assertIn("SHA mismatch", report.detail)

    def test_head_change_during_collection_denies(self):
        self.head_responses = [HEAD, "b" * 40]
        report = self.resolve()
        self.assertEqual(report.status, "DENY")
        self.assertIn("changed while", report.detail)

    def test_invalid_head_denies(self):
        self.head_responses = ["not-a-sha"]
        report = self.resolve()
        self.assertEqual(report.status, "DENY")

    def test_json_report_is_serializable_and_does_not_include_source_contents(self):
        report = self.resolve()
        payload = json.loads(json.dumps(report.to_dict()))
        self.assertEqual(payload["status"], "REQUIRE_APPROVAL")
        self.assertEqual(len(payload["sources"]), 3)
        self.assertNotIn("# control rules", json.dumps(payload))

    def test_only_approved_source_paths_are_requested(self):
        self.resolve()
        requested = [urlparse(url).path.split("/contents/", 1)[-1] for url in self.calls if "/contents/" in url]
        self.assertEqual(requested, list(reader.SOURCE_PATHS))


if __name__ == "__main__":
    unittest.main()
