from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_demo_health_check_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "demo_health_check.py"
    spec = importlib.util.spec_from_file_location("demo_health_check", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_health_check_passes_for_repository() -> None:
    module = _load_demo_health_check_module()
    exit_code, results = module.run_demo_health_check(Path(__file__).resolve().parents[1])
    assert exit_code == 0
    assert all(ok for _name, ok, _detail in results)
    names = {name for name, _ok, _detail in results}
    assert "exists:docs/SECURITY_BASELINE.md" in names
    assert "exists:docs/AUDIT_LOG_EXAMPLES.md" in names
    assert "load_policy" in names
    assert "startup_policy_validation" in names
