# Контракт HTTP-сервиса на стороне 1С

Нужно опубликовать HTTP-сервис в 1С, который принимает POST-запросы с JSON-RPC телом.

## Вход

```json
{
  "jsonrpc": "2.0",
  "method": "documents.post",
  "params": {
    "document_ref": "..."
  },
  "id": 10
}
```

## Выход при успехе

```json
{
  "jsonrpc": "2.0",
  "result": {
    "posted": true
  },
  "id": 10
}
```

## Выход при ошибке

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32000,
    "message": "Документ не найден",
    "data": {
      "document_ref": "..."
    }
  },
  "id": 10
}
```

## Минимальные методы

1. `ping`
2. `accounting.get_balance`
3. `directory.counterparties.search`
4. `documents.create`
5. `documents.post`

## Важно для 1С:Бухгалтерия Казахстан 3.0

Имена объектов метаданных могут отличаться в конкретной базе. Поэтому bridge не зашивает внутренние имена документов и справочников 1С. Эти детали лучше держать на стороне HTTP-сервиса 1С.
