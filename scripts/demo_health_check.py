from __future__ import annotations

import sys
from pathlib import Path


CRITICAL_RELATIVE_PATHS = (
    "config/policy.yaml",
    "docs/DEMO_PROMPTS.md",
    "docs/DEMO_READONLY_SECURE_MODE.md",
    "docs/DEMO_CHECKLIST.md",
    "scripts/verify_audit_log.py",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_demo_health_check(repo_root: Path | None = None) -> tuple[int, list[tuple[str, bool, str]]]:
    repo_root = repo_root or _repo_root()
    results: list[tuple[str, bool, str]] = []

    for relative_path in CRITICAL_RELATIVE_PATHS:
        target = repo_root / relative_path
        results.append(
            (
                f"exists:{relative_path}",
                target.exists(),
                str(target),
            )
        )

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    try:
        from ashybulakstroy_mcp_1c_bridge.core_server import (
            POLICY,
            ensure_secure_runtime_configuration,
            mcp,
        )
        from ashybulakstroy_mcp_1c_bridge.security import load_policy
    except Exception as exc:
        results.append(("import_runtime", False, f"{exc.__class__.__name__}: {exc}"))
        return 1, results

    try:
        policy = load_policy(repo_root / "config/policy.yaml")
        results.append(("load_policy", True, f"mode={policy.mode} version={policy.version}"))
    except Exception as exc:
        results.append(("load_policy", False, f"{exc.__class__.__name__}: {exc}"))
        return 1, results

    try:
        ensure_secure_runtime_configuration(POLICY, mcp)
        results.append(("startup_policy_validation", True, "policy coverage passed without 1C connection"))
    except Exception as exc:
        results.append(("startup_policy_validation", False, f"{exc.__class__.__name__}: {exc}"))
        return 1, results

    critical_failures = [name for name, ok, _detail in results if not ok]
    return (1 if critical_failures else 0), results


def main() -> int:
    exit_code, results = run_demo_health_check()
    print("Demo Health Check")
    for name, ok, detail in results:
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")
    if exit_code != 0:
        print("Demo health check failed.")
    else:
        print("Demo health check passed.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
