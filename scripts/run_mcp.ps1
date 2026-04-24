$env:ONEC_ODATA_URL = if ($env:ONEC_ODATA_URL) { $env:ONEC_ODATA_URL } else { "http://localhost/AccountingKazakhstan/odata/standard.odata" }
$env:ONEC_USERNAME = if ($env:ONEC_USERNAME) { $env:ONEC_USERNAME } else { "odata_user" }
$env:ONEC_PASSWORD = if ($env:ONEC_PASSWORD) { $env:ONEC_PASSWORD } else { "secret" }
$env:BRIDGE_DB_PATH = if ($env:BRIDGE_DB_PATH) { $env:BRIDGE_DB_PATH } else { "./bridge_knowledge.sqlite3" }
$env:BRIDGE_MAX_TOP = if ($env:BRIDGE_MAX_TOP) { $env:BRIDGE_MAX_TOP } else { "500" }

1c-bridge
