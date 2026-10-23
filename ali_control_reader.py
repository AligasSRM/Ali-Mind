"""Resolve the approved Ali-Control repository and branch without reading files."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CONTROL_REPOSITORY = "AligasSRM/Ali-Control"
CONTROL_BRANCH = "main"
API_ROOT = "https://api.github.com"
REPOSITORY_URL = f"https://github.com/{CONTROL_REPOSITORY}"
BRANCH_URL = f"{REPOSITORY_URL}/tree/{CONTROL_BRANCH}"


@dataclass(frozen=True)
class PathReport:
    repository: str
    branch: str
    repository_url: str
    branch_url: str
    head_sha: str
    checked_at_utc: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocatorError(RuntimeError):
    """Raised when the approved repository or branch cannot be verified."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _request_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Ali-Mind-control-path-reader",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise LocatorError(f"GitHub returned HTTP {status}.")
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise LocatorError("GitHub returned an unexpected JSON response.")
    return payload


def resolve_control_path(timeout: float = 10.0) -> PathReport:
    """Verify repository identity and main-branch head metadata only."""
    checked_at = _now()

    def unverified(detail: str, head_sha: str = "") -> PathReport:
        return PathReport(
            repository=CONTROL_REPOSITORY,
            branch=CONTROL_BRANCH,
            repository_url=REPOSITORY_URL,
            branch_url=BRANCH_URL,
            head_sha=head_sha,
            checked_at_utc=checked_at,
            status="PATH_UNVERIFIED",
            detail=detail,
        )

    try:
        metadata = _request_json(
            f"{API_ROOT}/repos/{CONTROL_REPOSITORY}",
            timeout,
        )
        if metadata.get("full_name", "").casefold() != CONTROL_REPOSITORY.casefold():
            return unverified("Repository identity does not match the approved path.")
        if metadata.get("archived") is True:
            return unverified("The approved repository is archived.")

        branch_data = _request_json(
            f"{API_ROOT}/repos/{CONTROL_REPOSITORY}/commits/{CONTROL_BRANCH}",
            timeout,
        )
        head_sha = branch_data.get("sha")
        if (
            not isinstance(head_sha, str)
            or len(head_sha) != 40
            or any(char not in "0123456789abcdefABCDEF" for char in head_sha)
        ):
            return unverified("The main branch has no valid commit SHA.")

        return PathReport(
            repository=CONTROL_REPOSITORY,
            branch=CONTROL_BRANCH,
            repository_url=REPOSITORY_URL,
            branch_url=BRANCH_URL,
            head_sha=head_sha,
            checked_at_utc=checked_at,
            status="PATH_VERIFIED",
            detail=(
                "Repository identity and main-branch head verified. "
                "No repository file contents were read; "
                "this status does not authorize any operation."
            ),
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        LocatorError,
    ) as exc:
        return unverified(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    print(
        json.dumps(
            resolve_control_path().to_dict(),
            indent=2,
            ensure_ascii=False,
        )
    )
