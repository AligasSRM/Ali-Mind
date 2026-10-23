"""Live, read-only smoke check for the approved Ali-Control source contract."""
import json
import sys

from ali_control_reader import SOURCE_PATHS, read_control_evidence


def main() -> int:
    report = read_control_evidence()
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    if report.status != "REQUIRE_APPROVAL":
        print("FAIL: live Ali-Control source verification was denied.", file=sys.stderr)
        return 1
    if tuple(item.path for item in report.sources) != SOURCE_PATHS:
        print("FAIL: report does not contain exactly the approved sources.", file=sys.stderr)
        return 1
    if not report.head_sha or any(
        not item.verified or item.commit_sha != report.head_sha
        or item.repository != "AligasSRM/Ali-Control" or item.branch != "main"
        for item in report.sources
    ):
        print("FAIL: source evidence is not consistently verified at one HEAD.", file=sys.stderr)
        return 1
    print("PASS: live read-only source verification succeeded; no operation was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
