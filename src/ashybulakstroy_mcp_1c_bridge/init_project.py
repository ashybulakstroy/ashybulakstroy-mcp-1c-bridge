from __future__ import annotations

import json
from pathlib import Path


PROJECT_KNOWLEDGE_FILES: dict[str, str] = {
    "project_knowledge/1c_kazakhstan.md": """# 1C Kazakhstan knowledge\n\nDescribe the exact 1C configuration/version, publication path, roles and known metadata names discovered by `ashybulak-1c-bridge inspect`.\n\n## Discovered endpoints\n\n- OData: TBD\n- RPC: TBD\n\n## Important metadata names\n\n- Counterparties catalog: TBD\n- Nomenclature catalog: TBD\n- Warehouses catalog: TBD\n- Sales document: TBD\n- Purchase document: TBD\n""",
    "project_knowledge/business_rules.md": """# Business rules\n\nProject-specific rules for AshybulakStroy accounting automation.\n\n## Before posting documents\n\n- Validate counterparty exists.\n- Validate nomenclature exists.\n- Validate stock availability where applicable.\n- Validate required tax/VAT fields according to the real 1C base.\n""",
    "project_knowledge/roles_and_permissions.md": """# Roles and permissions\n\nDocument which 1C user is used for integration and what it is allowed to do.\n\n## Integration user\n\n- Username: TBD\n- Allowed read operations: TBD\n- Allowed write operations: TBD\n- Posting allowed: TBD\n""",
    "project_knowledge/document_mapping.md": """# Document mapping\n\nFill this after running `inspect`. Do not guess internal document names.\n\n| Business action | 1C document/entity | Transport | Notes |\n| --- | --- | --- | --- |\n| Sales invoice | TBD | RPC | Requires validation |\n| Purchase invoice | TBD | RPC | Requires validation |\n""",
    "project_knowledge/odata_entities.md": """# OData entities\n\nPaste relevant entity names discovered from `$metadata`.\n\n## Catalogs\n\n- TBD\n\n## Documents\n\n- TBD\n\n## Registers\n\n- TBD\n""",
    "docs/specs/create_sales_invoice.md": """# Specification: create_sales_invoice\n\n## Goal\n\nCreate a sales document in 1C through RPC after validating required fields and stock availability.\n\n## Required input\n\n- counterparty\n- organization\n- warehouse (when goods are involved)\n- items[] with nomenclature, quantity, price\n\n## Validation\n\n- Payload is a dictionary.\n- `items` is not empty.\n- Every item has quantity > 0.\n- If `post=true`, stock validation should pass first.\n\n## Expected result\n\nRPC response must include one of: `document_ref`, `ref`, `Ref_Key`, or `id`.\n""",
    "tests/contracts/test_validate_before_post.py": """from ashybulakstroy_mcp_1c_bridge.documents import DocumentService\nfrom ashybulakstroy_mcp_1c_bridge.buh.rpc import BuhError\n\n\nclass DummyClient:\n    rpc = object()\n\n    async def call(self, method, params):\n        if method == \"documents.validate_sales_invoice\":\n            return {\"ok\": True}\n        if method == \"documents.create_sales_invoice\":\n            return {\"document_ref\": \"dummy-ref\"}\n        if method == \"documents.post\":\n            return {\"posted\": True}\n        raise AssertionError(method)\n\n    async def create_document(self, document_type, payload):\n        return {\"document_ref\": \"dummy-ref\"}\n\n    async def post_document(self, document_ref):\n        return {\"posted\": True, \"document_ref\": document_ref}\n\n\nasync def test_create_sales_invoice_validates_before_post():\n    service = DocumentService(DummyClient())\n    result = await service.create_sales_invoice({\"items\": [{\"quantity\": 1}]}, post=True)\n    assert result[\"posted\"][\"posted\"] is True\n\n\ndef test_validation_rejects_empty_items():\n    service = DocumentService(DummyClient())\n    try:\n        service.validate_sales_invoice_payload({\"items\": []})\n    except BuhError as exc:\n        assert \"items\" in str(exc)\n    else:\n        raise AssertionError(\"Expected BuhError\")\n""",
}


DEFAULT_CONFIG = {
    "buh": {
        "odata_url": "http://localhost/base/odata/standard.odata",
        "rpc_url": "http://localhost/base/hs/ashybulak/api",
        "mode": "auto",
        "username": "user",
        "password": "password",
    },
    "server": {"name": "AshybulakStroy MCP 1C Bridge", "transport": "stdio"},
}


def init_project(target_dir: str | Path = ".", overwrite: bool = False) -> list[str]:
    root = Path(target_dir).resolve()
    created: list[str] = []
    root.mkdir(parents=True, exist_ok=True)

    config_path = root / "config.json"
    if overwrite or not config_path.exists():
        config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        created.append(str(config_path))

    env_path = root / ".env"
    if overwrite or not env_path.exists():
        env_path.write_text(
            "BUH_ODATA_URL=http://localhost/base/odata/standard.odata\n"
            "BUH_RPC_URL=http://localhost/base/hs/ashybulak/api\n"
            "BUH_MODE=auto\n"
            "BUH_USERNAME=user\n"
            "BUH_PASSWORD=password\n",
            encoding="utf-8",
        )
        created.append(str(env_path))

    for rel_path, content in PROJECT_KNOWLEDGE_FILES.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite or not path.exists():
            path.write_text(content.rstrip() + "\n", encoding="utf-8")
            created.append(str(path))

    return created
