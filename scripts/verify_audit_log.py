from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "timestamp",
    "trace_id",
    "actor",
    "tool",
    "risk",
    "capabilities",
    "decision",
    "policy_version",
    "duration_ms",
)


def verify_audit_log(path: Path) -> tuple[int, list[str]]:
    errors: list[str] = []
    if not path.exists():
        return 1, [f"audit log not found: {path}"]

    line_count = 0
    for index, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        line_count += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {index}: invalid JSON ({exc})")
            continue

        missing = [field for field in REQUIRED_FIELDS if field not in record]
        if missing:
            errors.append(f"line {index}: missing required fields {missing}")
            continue

        if not isinstance(record.get("capabilities"), list):
            errors.append(f"line {index}: capabilities must be a list")
        if not isinstance(record.get("duration_ms"), int):
            errors.append(f"line {index}: duration_ms must be an integer")
        if not record.get("trace_id"):
            errors.append(f"line {index}: trace_id must be non-empty")

    if line_count == 0:
        errors.append("audit log contains no records")

    return (0 if not errors else 1), errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify append-only audit JSONL records for required fields.")
    parser.add_argument(
        "path",
        nargs="?",
        default="audit/audit.jsonl",
        help="Path to audit jsonl file (default: audit/audit.jsonl)",
    )
    args = parser.parse_args()

    exit_code, errors = verify_audit_log(Path(args.path))
    if errors:
        print("Audit verification failed:")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"Audit verification passed: {args.path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
