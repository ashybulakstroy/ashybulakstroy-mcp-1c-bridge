from __future__ import annotations

import logging
import re
import sys
from decimal import Decimal
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_settings
from .knowledge import KnowledgeStore, Recipe
from .odata import OneCODataClient, ODataError
from .validation import InventoryValidationConfig, parse_inventory_report_text as parse_inventory_report_text_impl, validate_inventory_rows

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("1c-cognitive-bridge")

settings = load_settings()
odata = OneCODataClient(settings)
store = KnowledgeStore(settings.db_path)
mcp = FastMCP("AshybulakStroy 1C Bridge")
LAST_ANSWER_TRACE: dict[str, Any] = {}


def _remember(tool: str, data: Any) -> None:
    global LAST_ANSWER_TRACE
    LAST_ANSWER_TRACE = {"tool": tool, "data": data}


def _ok(data: Any, tool: str | None = None) -> dict[str, Any]:
    if tool:
        _remember(tool, data)
    return {"ok": True, "data": data}


def _err(exc: Exception) -> dict[str, Any]:
    log.exception("Tool failed: %s", exc)
    return {"ok": False, "error": str(exc), "type": exc.__class__.__name__}


def _extract_limit(text: str, default: int = 50) -> int:
    match = re.search(r"(?:топ|top|limit|лимит|первые|последние|покажи)\s*(\d{1,4})", text.lower())
    if not match:
        return default
    return min(max(int(match.group(1)), 1), settings.max_top)


def _extract_after_keywords(text: str, keywords: list[str]) -> str | None:
    lowered = text.lower()
    for kw in keywords:
        idx = lowered.find(kw)
        if idx >= 0:
            tail = text[idx + len(kw):].strip(" :—-.,")
            tail = re.split(r"\b(?:на складе|по складу|склад|за период|за дату|на дату|лимит|limit|top)\b", tail, flags=re.IGNORECASE)[0]
            tail = tail.strip(" :—-.,")
            if tail:
                return tail[:120]
    return None


def _extract_warehouse(text: str) -> str | None:
    match = re.search(r"(?:на складе|по складу|склад)\s+([^,.;\n]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip(" :—-.,")[:120] if match else None


@mcp.tool()
def get_server_status() -> dict[str, Any]:
    """Проверить настройки сервера и доступность базовой конфигурации без чтения бизнес-данных."""
    try:
        return _ok(
            {
                "odata_url_configured": bool(settings.odata_url),
                "db_path": str(settings.db_path),
                "max_top": settings.max_top,
                "mode": "read-only",
            }
        )
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def setup_wizard(check_live_entities: bool = False, live_limit: int = 30) -> dict[str, Any]:
    """Запустить мастер первичной настройки AshybulakStroy 1C Bridge.

    Проверяет .env, доступность OData, чтение $metadata, количество опубликованных сущностей,
    вероятные источники остатков и, опционально, наличие данных в первых сущностях.
    Это первый tool, который нужно вызвать после установки сервера.
    """
    try:
        result = odata.setup_wizard(check_live_entities=check_live_entities, live_limit=live_limit)
        return _ok(result, tool="setup_wizard")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def generate_1c_database_profile(check_inventory_data: bool = True, live_limit: int = 0) -> dict[str, Any]:
    """Сформировать паспорт опубликованной OData-базы 1С.

    Показывает сколько видно справочников, документов, регистров и других сущностей,
    какие сущности похожи на остатки/продажи/контрагентов/номенклатуру,
    а также какие риски есть перед использованием данных.
    """
    try:
        result = odata.generate_database_profile(check_inventory_data=check_inventory_data, live_limit=live_limit)
        return _ok(result, tool="generate_1c_database_profile")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def explain_last_answer() -> dict[str, Any]:
    """Объяснить последний важный ответ сервера: какой tool работал, какой источник выбрал и какие есть предупреждения.

    Используйте после get_inventory_auto, validate_inventory_report_text, setup_wizard или generate_1c_database_profile,
    когда пользователь спрашивает: «почему сервер так решил?»
    """
    try:
        if not LAST_ANSWER_TRACE:
            return _ok({"message": "Пока нет сохраненного ответа для объяснения. Сначала вызовите setup_wizard, get_inventory_auto или другой бизнес-tool."})
        return _ok(_build_explanation(LAST_ANSWER_TRACE), tool="explain_last_answer")
    except Exception as exc:
        return _err(exc)


def _build_explanation(trace: dict[str, Any]) -> dict[str, Any]:
    data = trace.get("data") or {}
    tool = trace.get("tool")
    explanation: dict[str, Any] = {"last_tool": tool, "summary": [], "warnings": [], "source": None, "confidence": None}
    source = None
    if isinstance(data, dict):
        source = data.get("source") or data.get("mcp_source")
        if data.get("warnings"):
            explanation["warnings"].extend(data.get("warnings") or [])
        if data.get("mcp_warnings"):
            explanation["warnings"].extend(data.get("mcp_warnings") or [])
    if source:
        explanation["source"] = source.get("entity") if isinstance(source, dict) else source
        explanation["confidence"] = source.get("confidence") if isinstance(source, dict) else None
        explanation["summary"].append("Сервер выбрал источник по эвристике metadata: имя сущности, тип сущности и похожие поля номенклатуры, склада, количества и суммы.")
        if isinstance(source, dict):
            explanation["mapped_fields"] = source.get("mapped_fields")
            explanation["reasons"] = source.get("reasons")
    if tool == "setup_wizard":
        explanation["summary"].append("Мастер настройки проверил .env, OData, $metadata и кандидатов источника остатков.")
    elif tool == "generate_1c_database_profile":
        explanation["summary"].append("Паспорт базы построен по $metadata: сущности сгруппированы по типам и ключевым бизнес-словам.")
    elif tool in {"get_inventory_auto", "ask_1c"}:
        explanation["summary"].append("Остатки получены адаптивно: найден кандидат источника, строки прочитаны через OData и нормализованы в item/warehouse/quantity/amount.")
    elif tool == "get_low_stock_items":
        explanation["summary"].append("Низкие остатки рассчитаны детерминированно: сервер взял авто-остатки и отфильтровал позиции, где quantity меньше или равно заданному порогу.")
    elif tool == "validate_inventory_report_text":
        explanation["summary"].append("Сверка сравнила нормализованные строки MCP и строки отчета 1С по ключам item+warehouse с учетом допусков.")
    if not explanation["warnings"]:
        explanation["warnings"].append("Если это новый источник или новый фильтр, результат нужно сверить с официальным отчетом 1С перед доверием.")
    return explanation


@mcp.tool()
def ask_1c(text: str, limit: int | None = None) -> dict[str, Any]:
    """Понять простой пользовательский запрос к 1С обычным текстом и вызвать подходящий read-only инструмент.

    Используйте этот tool, когда пользователь не хочет писать JSON.

    Примеры:
    - "Покажи остатки цемента на складе Основной"
    - "Найди источник остатков"
    - "Какие таблицы есть в OData?"
    - "Найди в метаданных номенклатура"

    Сейчас поддерживаются намерения: остатки, дефицит/низкие остатки, поиск источников остатков, список сущностей, поиск metadata.
    """
    try:
        q = (text or "").strip()
        if not q:
            raise ValueError("Передайте обычный текст запроса, например: 'Покажи остатки цемента на складе Основной'.")
        ql = q.lower()
        effective_limit = limit or _extract_limit(q, default=50)

        if any(word in ql for word in ["мастер", "настрой", "первичн", "setup", "wizard", "проверь подключение"]):
            result = odata.setup_wizard(check_live_entities=False, live_limit=30)
            return _ok({"intent": "setup_wizard", "result": result}, tool="setup_wizard")

        if any(word in ql for word in ["паспорт базы", "профиль базы", "карта базы", "database profile", "profile"]):
            result = odata.generate_database_profile(check_inventory_data=True, live_limit=0)
            return _ok({"intent": "generate_1c_database_profile", "result": result}, tool="generate_1c_database_profile")

        if any(word in ql for word in ["почему", "объясни", "explain", "как решил"]):
            return _ok({"intent": "explain_last_answer", "result": _build_explanation(LAST_ANSWER_TRACE)}, tool="explain_last_answer")

        if any(word in ql for word in ["свер", "отчет", "отчёт", "материальная ведомость"]):
            return _ok({
                "intent": "validation_help",
                "message": "Для сверки вставьте скопированные строки отчета 1С в tool validate_inventory_report_text. Пример: Сверь остатки по складу Основной с этим отчетом: и ниже вставьте таблицу из 1С/Excel.",
                "next_tool": "validate_inventory_report_text"
            })



        if any(word in ql for word in ["заканч", "дефицит", "мало", "низк", "дозаказ", "закуп", "low stock", "stockout"]):
            warehouse = _extract_warehouse(q)
            item = _extract_after_keywords(q, ["товар", "товары", "номенклатура", "остатки", "остаток", "дефицит", "заканчивается"])
            threshold_match = re.search(r"(?:меньше|ниже|до|порог|threshold)\s*(\d+(?:[,.]\d+)?)", ql)
            threshold = threshold_match.group(1).replace(",", ".") if threshold_match else "10"
            result = odata.get_low_stock_items(warehouse=warehouse, item=item, threshold_quantity=threshold, limit=effective_limit)
            return _ok({"intent": "get_low_stock_items", "parsed": {"item": item, "warehouse": warehouse, "threshold_quantity": threshold, "limit": effective_limit}, "result": result}, tool="get_low_stock_items")

        if any(word in ql for word in ["источник остат", "где лежат остат", "найди остат", "discover inventory"]):
            return _ok({"intent": "discover_inventory_sources", "result": odata.discover_inventory_sources(limit=10, check_data=True)})

        if any(word in ql for word in ["остат", "склад", "товар", "тмз", "номенклатур", "inventory", "stock"]):
            warehouse = _extract_warehouse(q)
            item = _extract_after_keywords(q, ["остатки", "остаток", "товары", "товар", "номенклатура", "inventory", "stock"])
            result = odata.get_inventory_auto(warehouse=warehouse, item=item, limit=effective_limit)
            return _ok({"intent": "get_inventory_auto", "parsed": {"item": item, "warehouse": warehouse, "limit": effective_limit}, "result": result})

        if any(word in ql for word in ["таблиц", "сущност", "entities", "entity", "odata"]):
            entities = odata.list_entities(refresh=False)[:effective_limit]
            return _ok({"intent": "list_entities", "result": [{"name": e.name, "entity_type": e.entity_type, "field_count": len(e.fields or [])} for e in entities]})

        if any(word in ql for word in ["метадан", "поле", "поля", "найди", "search"]):
            search_text = re.sub(r"(?i)^(найди|поищи|search|в метаданных|метаданные|поле|поля)\s*", "", q).strip() or q
            return _ok({"intent": "search_metadata", "parsed": {"text": search_text}, "result": odata.search_metadata(search_text, limit=effective_limit)})

        return _ok({
            "intent": "unknown",
            "message": "Я не распознал сценарий. Попробуйте: 'Покажи остатки цемента на складе Основной', 'Найди источник остатков', 'Какие таблицы есть?', 'Найди в метаданных номенклатура'.",
            "available_tools": ["get_low_stock_items", "get_inventory_auto", "discover_inventory_sources", "list_entities", "search_metadata", "query_entity", "validate_inventory_against_1c_report"],
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_entities(refresh: bool = False, limit: int = 200) -> dict[str, Any]:
    """Показать, какие таблицы/справочники/документы/регистры опубликованы в OData 1С.

    Вызывайте, когда пользователь спрашивает: "какие таблицы есть", "что видно в 1С", "покажи сущности OData".
    Параметр refresh=true перечитывает $metadata, limit ограничивает размер ответа.
    """
    try:
        entities = odata.list_entities(refresh=refresh)
        return _ok([
            {"name": e.name, "entity_type": e.entity_type, "field_count": len(e.fields or [])}
            for e in entities[:limit]
        ])
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def describe_entity(entity_name: str) -> dict[str, Any]:
    """Показать поля конкретной OData-сущности 1С и их типы.

    Вызывайте после list_entities/search_metadata, когда нужно понять структуру выбранной таблицы.
    Если точное OData-имя неизвестно, сначала найдите сущность через search_metadata.
    """
    try:
        entity = odata.describe_entity(entity_name)
        if entity is None:
            raise ODataError(f"Сущность не найдена: {entity_name}")
        return _ok(
            {
                "name": entity.name,
                "entity_type": entity.entity_type,
                "fields": [f.__dict__ for f in (entity.fields or [])],
            }
        )
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sample_entity(entity_name: str, top: int = 5) -> dict[str, Any]:
    """Получить несколько примерных строк из выбранной сущности 1С.

    Используйте для безопасной разведки данных перед построением рецепта или фильтра. Это не полноценный отчет.
    """
    try:
        return _ok(odata.sample_entity(entity_name, top=top))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def query_entity(
    entity_name: str,
    top: int = 50,
    select: list[str] | None = None,
    filter_expr: str | None = None,
    orderby: str | None = None,
    skip: int = 0,
) -> dict[str, Any]:
    """Выполнить точный read-only OData-запрос к 1С.

    Используйте, когда уже известны entity_name и поля. Для обычного пользователя предпочтительнее ask_1c/get_inventory_auto.
    Поддерживает select, filter_expr, orderby, top и skip. Сервер не изменяет данные 1С.
    """
    try:
        return _ok(
            odata.query_entity(
                entity_name=entity_name,
                top=top,
                select=select,
                filter_expr=filter_expr,
                orderby=orderby,
                skip=skip,
            )
        )
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def search_metadata(text: str, limit: int = 30) -> dict[str, Any]:
    """Найти таблицы и поля 1С по обычному тексту.

    Примеры text: "номенклатура", "склад", "остатки", "контрагент", "реализация", "сумма".
    Это основной инструмент перед describe_entity/query_entity, если точное OData-имя неизвестно.
    """
    try:
        return _ok(odata.search_metadata(text=text, limit=limit))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def explore_live_entities(limit: int = 200) -> dict[str, Any]:
    """Проверить, какие опубликованные OData-сущности 1С реально содержат данные.

    Используйте после первичной настройки, чтобы отличить пустые служебные сущности от полезных бизнес-таблиц.
    Может быть медленным на больших публикациях OData.
    """
    try:
        return _ok(odata.explore_live_entities(limit=limit))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def discover_inventory_sources(limit: int = 10, check_data: bool = True) -> dict[str, Any]:
    """Найти вероятные источники остатков товаров/ТМЗ в 1С без знания точного имени регистра.

    Вызывайте, когда пользователь спрашивает: "где лежат остатки", "найди регистр остатков", "какой источник использовать для склада".
    Возвращает кандидатов, confidence, причины выбора, найденные поля номенклатуры/склада/количества/суммы и sample.
    """
    try:
        return _ok(odata.discover_inventory_sources(limit=limit, check_data=check_data))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_inventory_auto(
    warehouse: str | None = None,
    item: str | None = None,
    limit: int = 50,
    entity_name: str | None = None,
    save_as_recipe: bool = True,
) -> dict[str, Any]:
    """Автоматически получить похожие на остатки строки из 1С, подобрав источник по metadata.

    Это эвристический инструмент. Он не заменяет официальный отчет 1С и должен быть подтвержден
    через сверку/ручную проверку перед использованием как бухгалтерский источник истины.
    """
    try:
        result = odata.get_inventory_auto(warehouse=warehouse, item=item, limit=limit, entity_name=entity_name)
        source = result.get("source") or {}
        mapped = source.get("mapped_fields") or {}
        if save_as_recipe and source.get("entity"):
            select = [
                v for v in [
                    mapped.get("item"),
                    mapped.get("warehouse"),
                    mapped.get("quantity"),
                    mapped.get("amount"),
                    mapped.get("period"),
                ]
                if v
            ]
            store.save_recipe(
                Recipe(
                    name="auto_inventory_candidate",
                    description="Автоматически найденный кандидат источника остатков. Перед production-использованием подтвердить вручную.",
                    entity=source["entity"],
                    query={"top": min(limit, settings.max_top), "select": select or None},
                    verified=False,
                )
            )
            result["saved_candidate_recipe"] = "auto_inventory_candidate"
        return _ok(result, tool="get_inventory_auto")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_low_stock_items(
    warehouse: str | None = None,
    item: str | None = None,
    threshold_quantity: str = "10",
    limit: int = 50,
    entity_name: str | None = None,
    include_zero: bool = True,
) -> dict[str, Any]:
    """Показать товары с низким остатком: первая killer-фича «где заканчивается товар?».

    Пользователь может спрашивать обычным текстом через ask_1c: «Где заканчивается товар?»,
    «Покажи дефицит по складу Основной», «Какие товары меньше 5?».
    MVP-логика: берём get_inventory_auto и фильтруем строки, где quantity <= threshold_quantity.
    """
    try:
        result = odata.get_low_stock_items(
            warehouse=warehouse,
            item=item,
            threshold_quantity=threshold_quantity,
            limit=limit,
            entity_name=entity_name,
            include_zero=include_zero,
        )
        return _ok(result, tool="get_low_stock_items")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def parse_inventory_report_text(report_text: str) -> dict[str, Any]:
    """Преобразовать скопированную с экрана/из Excel таблицу отчета 1С в строки для сверки.

    Пользователь может просто скопировать строки из 1С/Excel и вставить текстом. JSON вручную писать не нужно.
    Поддерживаются табличные данные с разделителями TAB, ;, |, а также строки с несколькими пробелами.
    Ожидаемые колонки: Номенклатура/Товар, Склад, Количество, Сумма.
    """
    try:
        rows = parse_inventory_report_text_impl(report_text)
        return _ok({
            "rows": rows,
            "row_count": len(rows),
            "usage": "Передайте эти rows в compare_inventory_rows или используйте validate_inventory_report_text для сверки с текущими MCP-остатками.",
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def validate_inventory_report_text(
    report_text: str,
    warehouse: str | None = None,
    item: str | None = None,
    entity_name: str | None = None,
    limit: int = 500,
    tolerance_quantity: str = "0.001",
    tolerance_amount: str = "1.00",
    compare_amount: bool = True,
    key_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Сверить MCP-остатки с отчетом 1С, который пользователь вставил обычным текстом.

    Главный user-friendly способ сверки: пользователь формирует отчет 1С на экране,
    копирует таблицу через Ctrl+C и вставляет её в чат. JSON вручную писать не нужно.
    """
    try:
        report_rows = parse_inventory_report_text_impl(report_text)
        if not report_rows:
            raise ValueError("Не удалось распознать строки отчета. Скопируйте таблицу с колонками Номенклатура, Склад, Количество, Сумма.")
        inventory = odata.get_inventory_auto(warehouse=warehouse, item=item, limit=limit, entity_name=entity_name)
        mcp_rows = inventory.get("data") or []
        cfg = InventoryValidationConfig(
            key_fields=tuple(key_fields or ["item", "warehouse"]),
            tolerance_quantity=Decimal(str(tolerance_quantity)),
            tolerance_amount=Decimal(str(tolerance_amount)),
            compare_amount=compare_amount,
        )
        validation = validate_inventory_rows(mcp_rows=mcp_rows, report_rows=report_rows, config=cfg)
        validation["parsed_report"] = {"row_count": len(report_rows), "sample": report_rows[:5]}
        validation["mcp_source"] = inventory.get("source")
        validation["mcp_filters"] = inventory.get("filters_applied_in_python")
        validation["mcp_warnings"] = inventory.get("warnings")
        return _ok(validation, tool="validate_inventory_report_text")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def validate_inventory_against_1c_report(
    report_rows: list[dict[str, Any]],
    warehouse: str | None = None,
    item: str | None = None,
    entity_name: str | None = None,
    limit: int = 500,
    tolerance_quantity: str = "0.001",
    tolerance_amount: str = "1.00",
    compare_amount: bool = True,
    key_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Сверить авто-остатки MCP с данными официального отчета 1С.

    report_rows — строки отчета 1С, вставленные вручную/из экспорта в формате JSON.
    Поддерживаются поля: item/warehouse/quantity/amount или русские аналоги
    Номенклатура/Склад/Количество/Сумма.
    """
    try:
        if not isinstance(report_rows, list):
            raise ValueError("report_rows должен быть списком строк отчета 1С")
        inventory = odata.get_inventory_auto(warehouse=warehouse, item=item, limit=limit, entity_name=entity_name)
        mcp_rows = inventory.get("data") or []
        cfg = InventoryValidationConfig(
            key_fields=tuple(key_fields or ["item", "warehouse"]),
            tolerance_quantity=Decimal(str(tolerance_quantity)),
            tolerance_amount=Decimal(str(tolerance_amount)),
            compare_amount=compare_amount,
        )
        validation = validate_inventory_rows(mcp_rows=mcp_rows, report_rows=report_rows, config=cfg)
        validation["mcp_source"] = inventory.get("source")
        validation["mcp_filters"] = inventory.get("filters_applied_in_python")
        validation["mcp_warnings"] = inventory.get("warnings")
        return _ok(validation)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def compare_inventory_rows(
    mcp_rows: list[dict[str, Any]],
    report_rows: list[dict[str, Any]],
    tolerance_quantity: str = "0.001",
    tolerance_amount: str = "1.00",
    compare_amount: bool = True,
    key_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Сравнить два набора строк остатков без обращения к OData.

    Используйте, когда пользователь вставил результат MCP и результат отчета 1С вручную или из файла.
    Удобно для тестов, сверки и поиска расхождений без повторного чтения 1С.
    """
    try:
        cfg = InventoryValidationConfig(
            key_fields=tuple(key_fields or ["item", "warehouse"]),
            tolerance_quantity=Decimal(str(tolerance_quantity)),
            tolerance_amount=Decimal(str(tolerance_amount)),
            compare_amount=compare_amount,
        )
        return _ok(validate_inventory_rows(mcp_rows=mcp_rows, report_rows=report_rows, config=cfg))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def save_recipe(
    name: str,
    description: str,
    entity: str,
    query: dict[str, Any],
    verified: bool = False,
) -> dict[str, Any]:
    """Сохранить повторно используемый рецепт получения бизнес-данных из 1С.

    Сохраняйте как verified=false, пока результат не сверен с официальным отчетом 1С.
    """
    try:
        allowed = {"top", "select", "filter_expr", "orderby", "skip"}
        unknown = set(query) - allowed
        if unknown:
            raise ValueError(f"В query есть неподдерживаемые параметры: {sorted(unknown)}")
        return _ok(store.save_recipe(Recipe(name, description, entity, query, verified)))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_recipes() -> dict[str, Any]:
    """Показать сохранённые рецепты запросов к 1С: проверенные и candidate-рецепты."""
    try:
        return _ok(store.list_recipes())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def run_recipe(name: str, top_override: int | None = None) -> dict[str, Any]:
    """Запустить ранее сохранённый read-only рецепт.

    Используйте, когда пользователь просит повторить уже найденный сценарий: "запусти рецепт остатков", "покажи сохранённый отчет".
    """
    try:
        recipe = store.get_recipe(name)
        if recipe is None:
            raise ValueError(f"Рецепт не найден: {name}")
        q = dict(recipe.query)
        if top_override is not None:
            q["top"] = top_override
        result = odata.query_entity(
            entity_name=recipe.entity,
            top=q.get("top", 50),
            select=q.get("select"),
            filter_expr=q.get("filter_expr"),
            orderby=q.get("orderby"),
            skip=q.get("skip", 0),
        )
        store.log_recipe_run(name, True, "ok")
        return _ok({"recipe": recipe.__dict__, "result": result})
    except Exception as exc:
        try:
            store.log_recipe_run(name, False, str(exc))
        except Exception:
            pass
        return _err(exc)



# ---------------------------------------------------------------------------
# Restored/added platform layer: capabilities, AI normalization, resources,
# prompts and safe validate-before-post helpers. These tools are intentionally
# appended to the original v0.8 server so old OData discovery, validation,
# recipes and explain trace stay intact.
# ---------------------------------------------------------------------------

@mcp.tool()
def list_capabilities() -> dict[str, Any]:
    """Показать business capabilities сервера: чтение, валидация, нормализация, документы."""
    try:
        from .capabilities import list_capabilities as _list
        return _ok(_list(), tool="list_capabilities")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_capability(name: str) -> dict[str, Any]:
    """Показать описание одной capability по имени, например stock.read или input.normalize_sales_invoice."""
    try:
        from .capabilities import get_capability as _get
        return _ok(_get(name), tool="get_capability")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def buh_inspect(check_live_entities: bool = False, live_limit: int = 30) -> dict[str, Any]:
    """Единая диагностическая команда: OData, metadata, источники остатков, паспорт базы."""
    try:
        result = {
            "setup": odata.setup_wizard(check_live_entities=check_live_entities, live_limit=live_limit),
            "profile": odata.generate_database_profile(check_inventory_data=True, live_limit=0),
        }
        return _ok(result, tool="buh_inspect")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def parse_sales_invoice_text(text: str) -> dict[str, Any]:
    """Разобрать свободный текст реализации в черновую структуру без записи в 1С."""
    try:
        from .normalization.legacy_sales_invoice import parse_sales_invoice_text as _parse
        return _ok(_parse(text), tool="parse_sales_invoice_text")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def find_buh_entity(kind: str, query: str, limit: int = 10) -> dict[str, Any]:
    """Найти кандидатов в 1С по тексту: kind=counterparty|item|warehouse. Только чтение."""
    try:
        from .normalization.legacy_sales_invoice import find_entity_candidates
        return _ok(find_entity_candidates(odata, kind=kind, query=query, limit=limit), tool="find_buh_entity")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def normalize_sales_invoice(payload: dict[str, Any] | None = None, text: str | None = None, confidence: float = 0.78) -> dict[str, Any]:
    """Нормализовать реализацию: текст/JSON -> refs кандидатов 1С + issues. Не создает документ."""
    try:
        from .normalization.legacy_sales_invoice import normalize_sales_invoice_draft
        return _ok(normalize_sales_invoice_draft(odata, payload=payload, text=text, confidence=confidence), tool="normalize_sales_invoice")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def validate_sales_invoice(payload: dict[str, Any]) -> dict[str, Any]:
    """Проверить структуру реализации перед созданием/проведением: контрагент, строки, количества, цены."""
    try:
        from .validation_rules.document_validator import validate_sales_invoice as _validate
        return _ok(_validate(payload), tool="validate_sales_invoice")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def post_document_validated(document_ref: str, validation_result: dict[str, Any]) -> dict[str, Any]:
    """Guardrail для проведения: не проводит документ, если validation_result.valid != true.

    В v0.8 сервер остаётся read-only по умолчанию; реальный RPC post_document подключается отдельно.
    """
    try:
        if not validation_result or validation_result.get("valid") is not True:
            raise ValueError("post_document заблокирован: сначала нужен успешный validate_sales_invoice / validate_document.")
        return _ok({
            "document_ref": document_ref,
            "status": "validated_but_not_posted",
            "message": "RPC-проведение не выполнено в read-only v0.8 ядре. Подключите RPC adapter для записи в 1С.",
        }, tool="post_document_validated")
    except Exception as exc:
        return _err(exc)


# MCP Resources: stable read-only context for compatible clients.
try:
    @mcp.resource("buh://health")
    def buh_health() -> str:
        import json
        return json.dumps({
            "odata_url_configured": bool(settings.odata_url),
            "db_path": str(settings.db_path),
            "mode": "read-only-with-guardrails",
        }, ensure_ascii=False, indent=2)

    @mcp.resource("buh://capabilities")
    def buh_capabilities() -> str:
        import json
        from .capabilities import list_capabilities as _list
        return json.dumps({"capabilities": _list()}, ensure_ascii=False, indent=2)

    @mcp.resource("buh://entities")
    def buh_entities() -> str:
        import json
        entities = [{"name": e.name, "entity_type": e.entity_type, "field_count": len(e.fields or [])} for e in odata.list_entities(refresh=False)]
        return json.dumps({"entities": entities}, ensure_ascii=False, indent=2)

    @mcp.resource("buh://normalization/sales-invoice-template")
    def sales_invoice_template() -> str:
        import json
        return json.dumps({
            "counterparty": "ТОО Ромашка",
            "warehouse": "Основной склад",
            "items": [{"name": "Цемент", "quantity": 20, "unit": "мешок", "price": 2500}],
            "workflow": ["parse_sales_invoice_text", "normalize_sales_invoice", "validate_sales_invoice", "create via RPC only after confirmation"],
        }, ensure_ascii=False, indent=2)
except Exception as exc:
    log.warning("MCP resources were not registered: %s", exc)


# MCP Prompts for compatible clients.
try:
    @mcp.prompt()
    def buh_reviewer() -> str:
        return """Ты ревьюер 1С/бухгалтерии. Перед записью проверь контрагента, номенклатуру, склад, количество, цену, остатки и последствия проведения. Никогда не разрешай post_document без успешной валидации."""

    @mcp.prompt()
    def buh_tester() -> str:
        return """Ты тестировщик 1С. Проверь крайние случаи: пустые строки, отрицательные количества, неоднозначные контрагенты, несколько похожих товаров, большие документы, отсутствие прав и недоступность OData/RPC."""

    @mcp.prompt()
    def buh_analyst() -> str:
        return """Ты аналитик 1С Бухгалтерии Казахстан. Сначала выясни бизнес-сценарий, затем используй inspect/metadata, затем нормализацию, затем валидацию. Не угадывай имена объектов 1С."""
except Exception as exc:
    log.warning("MCP prompts were not registered: %s", exc)


def main() -> None:
    # FastMCP.run uses stdio by default. Do not print to stdout.
    mcp.run()


if __name__ == "__main__":
    main()
