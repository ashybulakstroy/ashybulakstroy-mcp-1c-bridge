def register_buh_tester_prompt(mcp):
    @mcp.prompt()
    def buh_tester():
        return """
Ты тестировщик интеграции MCP + 1С.
Проверяй пустые данные, неоднозначности, ошибки 1С, недоступность OData/RPC, большие документы и негативные значения.
"""
