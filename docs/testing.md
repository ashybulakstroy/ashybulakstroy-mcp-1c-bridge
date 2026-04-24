# Testing

Проект v0.8 содержит тестовый контур, чтобы проверять жизнеспособность кода без реальной базы 1С.

## Что проверяется

- парсинг таблиц отчёта 1С, скопированных с экрана или из Excel;
- сверка строк MCP против строк отчёта 1С;
- разбор fake `$metadata` OData;
- авто-поиск источника остатков;
- нормализация строк остатков;
- фича `get_low_stock_items`.

## Как запустить локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest -q
```

На Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest -q
```

## Fake OData

Тестовый metadata-файл лежит здесь:

```text
tests/fixtures/fake_odata_metadata.xml
```

Он имитирует минимальную OData-публикацию с регистром:

```text
AccumulationRegister_ТоварыНаСкладах
```

Это не замена реальной 1С, а безопасный test fixture для проверки логики discovery и нормализации.

## GitHub Actions

Workflow находится здесь:

```text
.github/workflows/tests.yml
```

После правильной загрузки файлов в GitHub тесты будут запускаться автоматически при `push` и `pull_request`.
