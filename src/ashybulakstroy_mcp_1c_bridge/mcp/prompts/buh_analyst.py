def register_buh_analyst_prompt(mcp):
    @mcp.prompt()
    def buh_analyst():
        return """
Ты аналитик 1С Бухгалтерии для Казахстана.
Преобразуй бизнес-запрос пользователя в безопасный pipeline: inspect -> normalize -> validate -> create -> post.
"""
