#!/usr/bin/env bash
set -euo pipefail

export ONEC_ODATA_URL="${ONEC_ODATA_URL:-http://localhost/AccountingKazakhstan/odata/standard.odata}"
export ONEC_USERNAME="${ONEC_USERNAME:-odata_user}"
export ONEC_PASSWORD="${ONEC_PASSWORD:-secret}"
export BRIDGE_DB_PATH="${BRIDGE_DB_PATH:-./bridge_knowledge.sqlite3}"
export BRIDGE_MAX_TOP="${BRIDGE_MAX_TOP:-500}"

exec 1c-bridge
