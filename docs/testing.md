# Testing

Проект содержит тестовый контур, который проверяет ключевую логику без подключения к реальной базе 1С.

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
python -m pytest -q
```

На Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m pytest -q
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

CI запускается автоматически при `push` и `pull_request`.

Матрица Python:
- `3.10`
- `3.11`
- `3.12`
