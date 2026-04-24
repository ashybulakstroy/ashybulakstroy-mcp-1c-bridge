# AshybulakStroy MCP 1C Bridge

**AshybulakStroy MCP 1C Bridge** — MCP-сервер для безопасного AI-доступа к данным 1С:Бухгалтерия для Казахстана 3.0 через OData.

Сервер позволяет AI-клиенту работать с 1С обычным языком: искать опубликованные сущности, получать остатки, находить товары с низким остатком, сверять данные с отчётом 1С и сохранять проверенные рецепты запросов.

## Возможности

- Подключение к 1С через OData в режиме чтения.
- Мастер первичной настройки `setup_wizard`.
- Паспорт базы `generate_1c_database_profile`.
- Поиск источников остатков `discover_inventory_sources`.
- Авто-получение остатков `get_inventory_auto`.
- Контроль низких остатков `get_low_stock_items`.
- Сверка с отчётом 1С через вставленный текст `validate_inventory_report_text`.
- Сохранение и повторный запуск рецептов.
- Человеческий интерфейс `ask_1c`, чтобы пользователь не писал JSON вручную.

## Установка

```bash
git clone https://github.com/AshybulakStroy/ashybulakstroy-mcp-1c-bridge.git
cd ashybulakstroy-mcp-1c-bridge
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

На Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
```

## Настройка `.env`

```env
ONEC_ODATA_URL=http://server/base/odata/standard.odata/
ONEC_USERNAME=readonly_user
ONEC_PASSWORD=password
ONEC_TIMEOUT=30
ONEC_MAX_TOP=100
BRIDGE_DB_PATH=.data/ashybulakstroy_bridge.sqlite3
```

Пользователь 1С должен иметь права только на чтение. Сервер не проводит документы и не изменяет данные 1С.

## Запуск

```bash
ashybulak-1c-bridge
```

## Подключение к MCP-клиенту

```json
{
  "mcpServers": {
    "ashybulakstroy-1c": {
      "command": "ashybulak-1c-bridge",
      "env": {
        "ONEC_ODATA_URL": "http://server/base/odata/standard.odata/",
        "ONEC_USERNAME": "readonly_user",
        "ONEC_PASSWORD": "password"
      }
    }
  }
}
```

## Как пользоваться без JSON

Пользователь пишет обычным языком:

```text
Проверь подключение к 1С.
Сделай паспорт базы 1С.
Покажи остатки товаров.
Где заканчивается товар?
Покажи товары меньше 5 по складу Основной.
Объясни последний ответ.
```

Для этого используется tool `ask_1c`. AI-клиент сам формирует параметры вызова tools.

## Сверка с отчётом 1С

1. В 1С сформируйте отчёт, например «Материальная ведомость».
2. Поставьте тот же склад, период и номенклатуру.
3. Скопируйте табличную часть отчёта.
4. Вставьте в чат:

```text
Сверь остатки с этим отчётом:
Номенклатура    Склад           Количество    Сумма
Цемент М400     Основной склад  100           250000
Песок           Основной склад  50            30000
```

Сервер распарсит таблицу и сравнит её с результатом MCP.

## Рекомендуемый первый сценарий

```text
Проверь подключение к 1С и запусти мастер настройки.
Сделай паспорт базы 1С.
Найди источники остатков.
Покажи остатки товаров.
Где заканчивается товар?
Объясни последний ответ.
```

## Безопасность

- Сервер работает в read-only режиме.
- Сервер не изменяет данные 1С.
- Сервер не проводит документы.
- Доступ к OData нужно выдавать отдельному пользователю с минимальными правами.

## Структура проекта

```text
src/ashybulakstroy_mcp_1c_bridge/
  core_server.py  # MCP tools and entrypoint
  odata.py        # OData client and discovery logic
  knowledge.py    # SQLite recipe storage
  validation.py   # report parsing and reconciliation
  config.py       # environment settings
```

## Статус

Текущая версия — MVP/early product. Главный сценарий: безопасный AI-доступ к данным 1С, остатки, низкие остатки и сверка с отчётом 1С.

## Лицензия

MIT.

## 🧪 Тестирование

В v0.8 добавлен тестовый контур без подключения к реальной 1С:

```bash
pip install -e .[dev]
pytest -q
```

Тесты проверяют парсинг отчётов, сверку, fake OData `$metadata`, поиск источника остатков и `get_low_stock_items`. Подробнее: `docs/testing.md`.

## Restoration note

This build preserves the v0.8 smart OData/inventory logic and adds the later platform layers: capabilities, resources/prompts, rules, templates, validation guardrails and AI normalization.

See `MERGE_MAP.md` for the exact migration map.
