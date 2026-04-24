from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register reusable MCP prompts for common accounting workflows."""

    @mcp.prompt(name="inspect_buh_database")
    def inspect_buh_database_prompt() -> str:
        return (
            "Проверь подключение к 1С через buh tools/resources. "
            "Сначала вызови inspect/health, затем перечисли доступные документы и справочники. "
            "Не угадывай имена объектов 1С — используй metadata."
        )

    @mcp.prompt(name="create_sales_invoice")
    def create_sales_invoice_prompt() -> str:
        return (
            "Создай реализацию товаров/услуг в 1С безопасно: найди контрагента и номенклатуру, "
            "проверь остатки, подготовь payload, создай документ через RPC и проводи только после подтверждения пользователя."
        )

    @mcp.prompt(name="check_stock")
    def check_stock_prompt() -> str:
        return (
            "Проверь остатки товаров по складам в 1С. Используй OData для справочников и RPC/регистр для остатков. "
            "Верни понятный итог: товар, склад, количество, дата проверки."
        )

    @mcp.prompt(name="analyze_debt")
    def analyze_debt_prompt() -> str:
        return (
            "Проанализируй задолженность контрагентов в 1С. Сначала уточни период, затем вызови debt tools, "
            "сгруппируй результат по контрагентам и выдели крупнейшие долги."
        )

    @mcp.prompt(name="validate_before_post")
    def validate_before_post_prompt() -> str:
        return (
            "Перед проведением документа в 1С выполни validate-before-post: проверь ссылку документа, тип документа, "
            "статус, остатки/обязательные поля и только затем вызывай post_document_validated. "
            "Если валидация вернула ошибку — не проводи документ."
        )

    @mcp.prompt(name="capability_planning")
    def capability_planning_prompt() -> str:
        return (
            "Планируй действие через capabilities: сначала выбери capability, проверь preferred_transport и risk, "
            "для write/posting обязательно используй validation. Не вызывай низкоуровневый buh_call без необходимости."
        )

    @mcp.prompt(name="normalize_sales_invoice_input")
    def normalize_sales_invoice_input_prompt() -> str:
        return (
            "Перед созданием реализации всегда выполняй AI-нормализацию: parse_sales_invoice_text для свободного текста, "
            "find_buh_entity для спорных контрагентов/товаров/складов, затем normalize_sales_invoice. "
            "Если normalize_sales_invoice вернул issues с not_found/ambiguous_match/missing_value — остановись и попроси выбрать вариант. "
            "Не вызывай create_sales_invoice или post_document напрямую, пока нет ref/GUID всех сущностей 1С."
        )

    @mcp.prompt(name="resolve_1c_ambiguity")
    def resolve_1c_ambiguity_prompt() -> str:
        return (
            "Если поиск в 1С вернул несколько кандидатов, покажи пользователю краткий список: name, ref, score. "
            "Не выбирай сам при близких score. После выбора пользователя повтори normalize_sales_invoice с explicit ref."
        )
