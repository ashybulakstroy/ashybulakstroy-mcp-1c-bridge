from __future__ import annotations

from pathlib import Path

import httpx

from live_1c_common import configure_quiet_logging, now_iso, prepare_live_env, repo_root, sanitize_error, write_markdown


def main() -> int:
    configure_quiet_logging()
    config = prepare_live_env()
    report_path = repo_root() / "reports" / "live_1c_smoke_test_report.md"

    checks: list[tuple[str, str, str]] = []
    exit_code = 0

    if not config.base_url or not config.service_url:
        checks.append(("config", "FAIL", "Set ONEC_ODATA_URL or ONEC_ODATA_BASE_URL."))
        exit_code = 1
    else:
        checks.append(("config", "OK", f"service_url={config.service_url}"))

    if not config.username or not config.password:
        checks.append(("auth_env", "FAIL", "Set ONEC_USERNAME/ONEC_PASSWORD or ONEC_ODATA_USERNAME/ONEC_ODATA_PASSWORD."))
        exit_code = 1
    else:
        checks.append(("auth_env", "OK", "username/password are configured in environment"))

    entity_count = None
    if exit_code == 0:
        try:
            with httpx.Client(
                timeout=config.timeout_seconds,
                verify=config.verify_ssl,
                auth=(config.username, config.password),
            ) as client:
                base_resp = client.get(config.base_url)
                checks.append(("base_url_reachable", "OK" if base_resp.status_code < 500 else "FAIL", f"HTTP {base_resp.status_code}"))
                if base_resp.status_code >= 500:
                    exit_code = 1

                meta_resp = client.get(f"{config.service_url}/$metadata", headers={"Accept": "application/xml"})
                if meta_resp.status_code == 200:
                    checks.append(("metadata_reachable", "OK", f"HTTP 200, bytes={len(meta_resp.text)}"))
                    entity_count = meta_resp.text.count("<EntitySet ")
                    checks.append(("authentication", "OK", "metadata authenticated successfully"))
                    checks.append(("odata_metadata_has_entity_sets", "OK" if entity_count > 0 else "FAIL", f"entity_sets={entity_count}"))
                    if entity_count == 0:
                        exit_code = 1
                else:
                    checks.append(("metadata_reachable", "FAIL", f"HTTP {meta_resp.status_code}"))
                    checks.append(("authentication", "FAIL", "metadata request did not authenticate successfully"))
                    exit_code = 1
        except Exception as exc:
            checks.append(("connectivity", "FAIL", sanitize_error(exc, config)))
            exit_code = 1

    checks.append(("write_operations", "OK", "Smoke test performs GET/read-only metadata access only."))

    lines = [
        "# Live 1C Smoke Test Report",
        "",
        f"- Generated: `{now_iso()}`",
        f"- Base URL: `{config.base_url or '<missing>'}`",
        f"- Service URL: `{config.service_url or '<missing>'}`",
        f"- Entity sets discovered in metadata: `{entity_count}`" if entity_count is not None else "- Entity sets discovered in metadata: `<not checked>`",
        "",
        "| Check | Status | Details |",
        "|---|---|---|",
    ]
    for name, status, details in checks:
        lines.append(f"| `{name}` | `{status}` | {details} |")

    write_markdown(report_path, "\n".join(lines) + "\n")

    print("Live 1C Smoke Test")
    for name, status, details in checks:
        print(f"[{status}] {name}: {details}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
