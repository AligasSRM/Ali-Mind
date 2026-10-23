"""Read-only evidence reader for the approved Ali-Control contract.

Fetches only the explicitly approved reference files from the pinned main HEAD.
It never writes to GitHub. Valid evidence yields REQUIRE_APPROVAL, not permission
to execute a separate operation.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

CONTROL_REPOSITORY = "AligasSRM/Ali-Control"
CONTROL_BRANCH = "main"
API_ROOT = "https://api.github.com"
REPOSITORY_URL = f"https://github.com/{CONTROL_REPOSITORY}"
BRANCH_URL = f"{REPOSITORY_URL}/tree/{CONTROL_BRANCH}"
SOURCE_PATHS = (
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
    detail: str


@dataclass(frozen=True)
class ControlReport:
    repository: str
    branch: str
    repository_url: str
    branch_url: str
    head_sha: str
    checked_at_utc: str
    status: str
    sources: tuple[SourceEvidence, ...]
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ControlReadError(RuntimeError):
    """Raised internally when a remote source cannot be verified."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _request_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Ali-Mind-control-evidence-reader",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise ControlReadError(f"GitHub returned HTTP {status}.")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ControlReadError("GitHub returned an unexpected JSON response.")
    return payload


def _blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _get_head(timeout: float) -> str:
    metadata = _request_json(f"{API_ROOT}/repos/{CONTROL_REPOSITORY}", timeout)
    if metadata.get("full_name", "").casefold() != CONTROL_REPOSITORY.casefold():
        raise ControlReadError("Repository identity does not match the approved path.")
    if metadata.get("archived") is True:
        raise ControlReadError("The approved repository is archived.")
    branch = _request_json(
        f"{API_ROOT}/repos/{CONTROL_REPOSITORY}/commits/{CONTROL_BRANCH}",
        timeout,
    )
    sha = branch.get("sha")
    if (
        not isinstance(sha, str)
        or len(sha) != 40
        or any(ch not in "0123456789abcdefABCDEF" for ch in sha)
    ):
        raise ControlReadError("The main branch has no valid commit SHA.")
    return sha


def _fetch_source(path: str, head_sha: str, checked_at: str, timeout: float) -> SourceEvidence:
    encoded_path = quote(path, safe="/")
    url = (
        f"{API_ROOT}/repos/{CONTROL_REPOSITORY}/contents/{encoded_path}"
        f"?ref={head_sha}"
    )
    data = _request_json(url, timeout)
    if data.get("type") != "file" or data.get("path") != path:
        raise ControlReadError(f"Expected file source is missing or has the wrong path: {path}")
    blob_sha = data.get("sha")
    encoded = data.get("content")
    if not isinstance(blob_sha, str) or not isinstance(encoded, str):
        raise ControlReadError(f"GitHub did not return blob metadata and content for {path}")
    try:
        raw = base64.b64decode(encoded, validate=False)
    except (ValueError, TypeError) as exc:
        raise ControlReadError(f"Invalid base64 content for {path}: {exc}") from exc
    calculated = _blob_sha(raw)
    if calculated != blob_sha:
        raise ControlReadError(f"Git blob SHA mismatch for {path}")
    # Validate UTF-8 and preserve no file content in the report.
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ControlReadError(f"Source is not valid UTF-8: {path}") from exc
    return SourceEvidence(
        repository=CONTROL_REPOSITORY,
        branch=CONTROL_BRANCH,
        path=path,
        commit_sha=head_sha,
        blob_sha=blob_sha,
        checked_at_utc=checked_at,
        verified=True,
        detail="Fetched at pinned commit and Git blob SHA verified.",
    )


def read_control_evidence(timeout: float = 10.0) -> ControlReport:
    """Fetch and verify the approved sources against one stable main HEAD."""
    checked_at = _now()
    head_sha = ""
    evidence: list[SourceEvidence] = []
    try:
        head_sha = _get_head(timeout)
        for path in SOURCE_PATHS:
            evidence.append(_fetch_source(path, head_sha, checked_at, timeout))
        final_head = _get_head(timeout)
        if final_head != head_sha:
            raise ControlReadError("Ali-Control main changed while evidence was being collected.")
        return ControlReport(
            repository=CONTROL_REPOSITORY,
            branch=CONTROL_BRANCH,
            repository_url=REPOSITORY_URL,
            branch_url=BRANCH_URL,
            head_sha=head_sha,
            checked_at_utc=checked_at,
            status="REQUIRE_APPROVAL",
            sources=tuple(evidence),
            detail=(
                "All required sources were fetched and verified at one stable HEAD. "
                "Source integrity is not operation-specific approval; no operation was executed."
            ),
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, ControlReadError) as exc:
        return ControlReport(
            repository=CONTROL_REPOSITORY,
            branch=CONTROL_BRANCH,
            repository_url=REPOSITORY_URL,
            branch_url=BRANCH_URL,
            head_sha=head_sha,
            checked_at_utc=checked_at,
            status="DENY",
            sources=tuple(evidence),
            detail=f"{type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    print(json.dumps(read_control_evidence().to_dict(), indent=2, ensure_ascii=False))
