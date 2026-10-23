"""Read-only evidence collector for the approved Ali-Control sources.

This module fetches only public GitHub metadata/content for the fixed allowlist.
It never writes to GitHub or treats source integrity as operation approval.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CONTROL_REPOSITORY = "AligasSRM/Ali-Control"
CONTROL_BRANCH = "main"
API_ROOT = "https://api.github.com"
REQUIRED_PATHS = (
    "README.md",
    "docs/CONTROL-STATUS-AND-ROADMAP.md",
    ".github/CODEOWNERS",
)


@dataclass(frozen=True)
class SourceEvidence:
    repository: str
    branch: str
    path: str
    commit_sha: str
    blob_sha: str
    checked_at_utc: str
    verified: bool
    status: str
    detail: str = ""


@dataclass(frozen=True)
class ReaderReport:
    repository: str
    branch: str
    head_sha: str
    checked_at_utc: str
    decision: str
    authorization_established: bool
    sources: tuple[SourceEvidence, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "branch": self.branch,
            "head_sha": self.head_sha,
            "checked_at_utc": self.checked_at_utc,
            "decision": self.decision,
            "authorization_established": self.authorization_established,
            "sources": [asdict(source) for source in self.sources],
            "errors": list(self.errors),
        }


class ReaderError(RuntimeError):
    """Raised internally when a required source cannot be verified."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _request_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Ali-Mind-read-only-control-reader",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise ReaderError(f"GitHub returned HTTP {status} for {url}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ReaderError(f"Unexpected JSON shape for {url}")
    return payload


def git_blob_sha(content: bytes) -> str:
    """Compute Git's canonical SHA-1 for a blob, including its header."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def collect_evidence(timeout: float = 10.0) -> ReaderReport:
    """Collect source evidence from one pinned main-branch commit; never authorize."""
    checked_at = _now()
    evidence: list[SourceEvidence] = []
    errors: list[str] = []
    head_sha = ""

    def failed_report(reason: str) -> ReaderReport:
        return ReaderReport(
            repository=CONTROL_REPOSITORY,
            branch=CONTROL_BRANCH,
            head_sha=head_sha,
            checked_at_utc=checked_at,
            decision="DENY",
            authorization_established=False,
            sources=tuple(evidence),
            errors=tuple(errors + [reason]),
        )

    try:
        commit = _request_json(
            f"{API_ROOT}/repos/{CONTROL_REPOSITORY}/commits/{CONTROL_BRANCH}",
            timeout,
        )
        head_sha = commit.get("sha", "")
        if not isinstance(head_sha, str) or len(head_sha) != 40:
            return failed_report("Invalid or missing main-branch commit SHA.")
        tree_url = f"{API_ROOT}/repos/{CONTROL_REPOSITORY}/git/trees/{head_sha}?recursive=1"
        tree = _request_json(tree_url, timeout)
        entries = tree.get("tree")
        if not isinstance(entries, list) or tree.get("truncated") is True:
            return failed_report("Git tree is missing, malformed, or truncated.")
        tree_by_path = {
            item.get("path"): item.get("sha")
            for item in entries
            if isinstance(item, dict) and item.get("type") == "blob"
        }
        for path in REQUIRED_PATHS:
            expected_blob = tree_by_path.get(path)
            if not isinstance(expected_blob, str) or len(expected_blob) != 40:
                evidence.append(SourceEvidence(
                    CONTROL_REPOSITORY, CONTROL_BRANCH, path, head_sha, "",
                    checked_at, False, "MISSING", "Path absent from pinned Git tree."
                ))
                errors.append(f"Required source missing from tree: {path}")
                continue
            try:
                payload = _request_json(
                    f"{API_ROOT}/repos/{CONTROL_REPOSITORY}/contents/{path}?ref={head_sha}",
                    timeout,
                )
                if payload.get("type") != "file" or payload.get("encoding") != "base64":
                    raise ReaderError("GitHub content response is not a base64 file.")
                encoded = payload.get("content")
                if not isinstance(encoded, str):
                    raise ReaderError("GitHub content response lacks content.")
                raw = base64.b64decode(encoded, validate=False)
                actual_blob = git_blob_sha(raw)
                if not raw:
                    raise ReaderError("Required source is empty.")
                if actual_blob != expected_blob or payload.get("sha") != expected_blob:
                    raise ReaderError("Blob SHA does not match pinned Git tree.")
                evidence.append(SourceEvidence(
                    CONTROL_REPOSITORY, CONTROL_BRANCH, path, head_sha,
                    actual_blob, checked_at, True, "VERIFIED",
                    "Content hash matches the tree at the pinned commit."
                ))
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, ReaderError) as exc:
                errors.append(f"{path}: {type(exc).__name__}: {exc}")
                evidence.append(SourceEvidence(
                    CONTROL_REPOSITORY, CONTROL_BRANCH, path, head_sha,
                    "", checked_at, False, "UNVERIFIED", str(exc)
                ))

        latest = _request_json(
            f"{API_ROOT}/repos/{CONTROL_REPOSITORY}/commits/{CONTROL_BRANCH}",
            timeout,
        )
        if latest.get("sha") != head_sha:
            errors.append("Ali-Control main moved during collection; snapshot is stale.")
        if errors or len(evidence) != len(REQUIRED_PATHS) or not all(x.verified for x in evidence):
            return ReaderReport(
                CONTROL_REPOSITORY, CONTROL_BRANCH, head_sha, checked_at,
                "DENY", False, tuple(evidence), tuple(errors or ["Evidence incomplete."])
            )
        # Verified source evidence is not an approval signal. There is no
        # trusted per-operation authorization contract in the current control repo.
        return ReaderReport(
            CONTROL_REPOSITORY, CONTROL_BRANCH, head_sha, checked_at,
            "REQUIRE_APPROVAL", False, tuple(evidence),
            ("Sources verified; no trusted per-operation authorization evidence exists.",)
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, ReaderError) as exc:
        return failed_report(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    print(json.dumps(collect_evidence().to_dict(), indent=2, ensure_ascii=False))
