"""Eight domain-independent mechanisms, pure deterministic evaluation."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

OPS = {"eq", "ne", "gt", "lt", "ge", "le", "in"}
MECHANISMS = {"field", "duplicate", "count", "aggregate", "sequence", "previous", "related", "novelty"}
ORDERED = {"gt", "lt", "ge", "le"}


class RuleError(ValueError):
    pass


def number(value):
    if isinstance(value, bool):
        raise RuleError("Ожидается число, не логическое значение")
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise RuleError("Число должно быть конечным")
        return result
    except (InvalidOperation, TypeError):
        raise RuleError("Ожидается числовое значение") from None


def compare(actual, op, expected, numeric=False):
    if op not in OPS:
        raise RuleError("Неизвестный тип сравнения")
    if op == "in":
        return number(actual) in [number(v) for v in expected] if numeric else actual in expected
    if numeric or op in ORDERED:
        actual, expected = number(actual), number(expected)
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "gt":
        return actual > expected
    if op == "lt":
        return actual < expected
    if op == "ge":
        return actual >= expected
    return actual <= expected


def validate_catalog(catalog):
    if not catalog or len(catalog) > 50:
        raise RuleError("Задайте от 1 до 50 типов событий")
    for action, config in catalog.items():
        if not action or not isinstance(config, dict) or not isinstance(config.get("fields"), dict) or not config["fields"] or len(config["fields"]) > 100:
            raise RuleError("Каждому типу событий нужны поля")
        for name, field in config["fields"].items():
            if not name or not isinstance(field, dict) or field.get("type") not in {"string", "number", "boolean"}:
                raise RuleError("У поля должен быть тип string, number или boolean")
            if field.get("source", "API") not in {"API", "DB"}:
                raise RuleError("Полю нужен ровно один источник: API или DB")
            if not isinstance(field.get("required", False), bool):
                raise RuleError("Обязательность поля должна быть логическим значением")


def field_names(node):
    if not isinstance(node, dict):
        raise RuleError("Условие должно быть объектом")
    names = set(node.get("group_by", [])) | set(node.get("match_fields", []))
    for key in ("field", "right_field"):
        if node.get(key):
            names.add(node[key])
    for child in node.get("children", []):
        names |= field_names(child)
    if node.get("child"):
        names |= field_names(node["child"])
    if node.get("filter"):
        names |= field_names(node["filter"])
    return names


def validate_expression(node, fields, catalog, depth=0, lists=None):
    if depth > 8 or not isinstance(node, dict):
        raise RuleError("Условие слишком глубоко вложено или имеет неверный формат")
    kind = node.get("kind")
    if not isinstance(kind, str):
        raise RuleError("Укажите механизм проверки")
    for key in ("field", "right_field", "op", "list_id"):
        if key in node and not isinstance(node[key], str):
            raise RuleError("Имена полей, сравнение и идентификатор списка должны быть строками")
    for key in ("group_by", "match_fields", "event_types", "statuses", "sequence"):
        if key in node and (not isinstance(node[key], list) or any(not isinstance(v, str) for v in node[key])):
            raise RuleError("Поля группировки, типы и статусы должны быть списками строк")
    for key in ("include_current", "on_empty"):
        if key in node and not isinstance(node[key], bool):
            raise RuleError("Переключатели механизма должны быть логическими")
    if kind in {"all", "any"}:
        children = node.get("children")
        if not isinstance(children, list) or not 1 <= len(children) <= 20:
            raise RuleError("Для И/ИЛИ нужны 1–20 условий")
        for child in children:
            validate_expression(child, fields, catalog, depth + 1, lists)
        return
    if kind == "not":
        validate_expression(node.get("child"), fields, catalog, depth + 1, lists)
        return
    if kind not in MECHANISMS:
        raise RuleError("Выберите один из восьми механизмов")
    for name in field_names(node):
        if name not in fields:
            raise RuleError(f"Поле {name} не зарегистрировано для этого типа действия")
    if kind in {"field", "aggregate", "related", "novelty"} and not node.get("field"):
        raise RuleError("Укажите поле")
    if kind in {"field", "count", "aggregate", "related"}:
        if node.get("op") not in OPS:
            raise RuleError("Укажите допустимое сравнение")
        if kind != "related" and "value" not in node and not node.get("list_id"):
            raise RuleError("Укажите порог или список")
        if node.get("list_id") and (lists is None or node["list_id"] not in lists):
            raise RuleError("Список не найден в этом приложении")
        if node.get("op") == "in" and not node.get("list_id") and not isinstance(node.get("value"), list):
            raise RuleError("Для сравнения со списком нужен список значений")
        if kind == "field" and node.get("op") in ORDERED and fields[node["field"]]["type"] != "number":
            raise RuleError("Сравнение больше/меньше допускается только для числа")
        if kind in {"count", "aggregate"} or node.get("op") in ORDERED:
            if kind != "related":
                number(node.get("value"))
    if kind == "field":
        node["value_type"] = fields[node["field"]]["type"]
        if node.get("list_id"):
            values = lists[node["list_id"]]
            if node["op"] != "in":
                raise RuleError("Список наблюдения используется только с условием наличия в списке")
            if node["value_type"] == "number":
                for value in values:
                    number(value)
            else:
                expected_type = str if node["value_type"] == "string" else bool
                if any(not isinstance(value, expected_type) for value in values):
                    raise RuleError("Значения списка не соответствуют типу поля")
        if node["value_type"] == "number" and not node.get("list_id"):
            for value in node["value"] if node["op"] == "in" else [node["value"]]:
                number(value)
        elif not node.get("list_id"):
            values = node["value"] if node["op"] == "in" else [node["value"]]
            expected_type = str if node["value_type"] == "string" else bool
            if any(not isinstance(v, expected_type) for v in values):
                raise RuleError("Значение условия не соответствует типу поля")
        return
    if kind == "related":
        if node["op"] == "in":
            raise RuleError("Связанные скалярные поля сравниваются без условия наличия в списке")
        if not node.get("right_field"):
            raise RuleError("Укажите поле связанного объекта или события")
        if fields[node["field"]]["type"] != fields[node["right_field"]]["type"] or (node["op"] in ORDERED and fields[node["field"]]["type"] != "number"):
            raise RuleError("Сравниваемые связанные поля должны иметь совместимые типы")
        node["value_type"] = fields[node["field"]]["type"]
        if node.get("relation", "history") not in {"current", "history"}:
            raise RuleError("Выберите связанный объект или событие истории")
        if node.get("relation") == "current":
            return
    period = node.get("period_seconds")
    if period is not None and (isinstance(period, bool) or not isinstance(period, int) or not 1 <= period <= 31_536_000):
        raise RuleError("Период должен быть целым числом секунд от 1 до 31536000")
    if kind != "previous" and period is None:
        raise RuleError("Укажите период анализа")
    if not isinstance(node.get("event_types"), list) or not isinstance(node.get("statuses"), list) or not node["event_types"] or not node["statuses"] or any(not isinstance(s, str) or not s for s in node["statuses"]):
        raise RuleError("Для истории нужны типы событий и учитываемые статусы")
    if any(action not in catalog for action in node["event_types"]):
        raise RuleError("Неизвестный тип события истории")
    if not isinstance(node.get("group_by", []), list):
        raise RuleError("Группировка должна быть списком полей")
    if kind == "duplicate" and not node.get("match_fields"):
        raise RuleError("Укажите поля совпадения")
    if kind == "aggregate":
        if node.get("aggregate") not in {"sum", "unique"}:
            raise RuleError("Выберите сумму или уникальные значения")
        if node["aggregate"] == "sum" and fields[node["field"]]["type"] != "number":
            raise RuleError("Суммировать можно только числовое поле")
    if kind == "sequence" and (len(node.get("sequence", [])) < 2 or any(t not in catalog for t in node["sequence"])):
        raise RuleError("Последовательности нужны минимум два зарегистрированных типа событий")
    if kind == "previous" and (not node.get("group_by") or not node.get("match_fields")):
        raise RuleError("Предыдущему событию нужны связь с объектом и поля актуальных данных")
    if kind in {"sequence", "related", "novelty"} and not node.get("group_by"):
        raise RuleError("Для связанной истории укажите поля сущности или объекта")
    if kind == "sequence" and not set(node["sequence"]).issubset(node["event_types"]):
        raise RuleError("Типы последовательности должны входить в учитываемую историю")
    if node.get("filter"):
        validate_expression(node["filter"], fields, catalog, depth + 1, lists)
        if any(k != "field" for k in leaf_kinds(node["filter"])):
            raise RuleError("Фильтр истории допускает только условия по полям")
    historical_fields = set(node.get("group_by", [])) | set(node.get("match_fields", []))
    if kind in {"aggregate", "novelty"}:
        historical_fields.add(node["field"])
    if kind == "related":
        historical_fields.add(node["right_field"])
    if node.get("filter"):
        historical_fields |= field_names(node["filter"])
    for action in node["event_types"]:
        historical_config = catalog[action]["fields"]
        if any(name not in historical_config or historical_config[name]["type"] != fields[name]["type"] for name in historical_fields):
            raise RuleError(f"Поля истории типа {action} отсутствуют или имеют несовместимый тип")


def leaf_kinds(node):
    if node.get("kind") in {"all", "any"}:
        return [kind for child in node["children"] for kind in leaf_kinds(child)]
    if node.get("kind") == "not":
        return leaf_kinds(node["child"])
    return [node.get("kind")]


def evaluate(node: dict, current: dict, history: list[dict], at: datetime, lists: dict | None = None, operation_id=None):
    lists = lists or {}
    kind = node["kind"]
    if kind in {"all", "any", "not"}:
        children = node.get("children", [node.get("child")])
        results = [evaluate(child, current, history, at, lists, operation_id) for child in children]
        flags = [result[0] for result in results]
        triggered = all(flags) if kind == "all" else any(flags) if kind == "any" else not flags[0]
        return triggered, {"kind": kind, "matched": triggered, "children": [r[1] for r in results]}
    if kind == "field":
        if node["field"] not in current:
            raise RuleError(f"Отсутствует поле {node['field']}")
        actual = current[node["field"]]
        expected = lists[node["list_id"]] if node.get("list_id") else node["value"]
        matched = compare(actual, node["op"], expected, node.get("value_type") == "number")
        return matched, {"kind": kind, "field": node["field"], "actual": actual, "op": node["op"], "expected": expected, "matched": matched}
    if kind == "related" and node.get("relation") == "current":
        if node["field"] not in current or node["right_field"] not in current:
            raise RuleError("Отсутствует поле связанного объекта")
        actual, expected = current[node["field"]], current[node["right_field"]]
        matched = compare(actual, node["op"], expected, node.get("value_type") == "number")
        return matched, {"kind": kind, "relation": "current", "field": node["field"], "right_field": node["right_field"], "actual": actual, "expected": expected, "matched": matched}
    lower = at - timedelta(seconds=node["period_seconds"]) if node.get("period_seconds") else None
    if any(name not in current for name in set(node.get("group_by", [])) | set(node.get("match_fields", [])) | ({node["field"]} if node.get("field") else set())):
        raise RuleError("Отсутствует поле механизма или группировки")
    events = []
    for event in history:
        if event["action"] not in node["event_types"] or event["status"] not in node["statuses"]:
            continue
        if event["event_at"] > at or (lower and event["event_at"] < lower):
            continue
        if not all(name in current and name in event["fields"] and event["fields"][name] == current[name] for name in node.get("group_by", [])):
            continue
        if node.get("filter") and not evaluate(node["filter"], event["fields"], [], at, lists)[0]:
            continue
        events.append(event)
    events.sort(key=lambda e: (e["event_at"], e["event_id"]))
    actual: Any = None
    extra = {}
    if kind == "duplicate":
        matches = [e for e in events if all(name in e["fields"] and e["fields"][name] == current.get(name) for name in node["match_fields"])]
        actual, matched = len(matches), bool(matches)
    elif kind == "count":
        actual = len(events) + int(node.get("include_current", False) and not (operation_id and any(e.get("operation_id") == operation_id for e in events)))
        matched = compare(actual, node["op"], node["value"], True)
    elif kind == "aggregate":
        values = [e["fields"][node["field"]] for e in events if node["field"] in e["fields"]]
        if node.get("include_current") and not (operation_id and any(e.get("operation_id") == operation_id for e in events)):
            values.append(current[node["field"]])
        actual = str(sum((number(v) for v in values), Decimal(0))) if node["aggregate"] == "sum" else len({str(v) for v in values})
        matched = compare(actual, node["op"], node["value"], True)
    elif kind == "sequence":
        sequence = node["sequence"]
        progress = 0
        previous_at = None
        for event in events:
            if event["action"] == sequence[progress] and (previous_at is None or event["event_at"] > previous_at):
                previous_at = event["event_at"]
                progress += 1
                if progress == len(sequence):
                    break
        actual, matched = progress, progress == len(sequence)
    elif kind == "previous":
        matches = [e for e in events if all(name in current and name in e["fields"] and current[name] == e["fields"][name] for name in node["match_fields"])]
        actual = len(matches)
        matched = not bool(matches)
        extra["missing_required_event"] = matched
    elif kind == "related":
        if not events or node["right_field"] not in events[-1]["fields"]:
            raise RuleError("Связанное событие или его поле не найдено")
        actual = current[node["field"]]
        expected = events[-1]["fields"][node["right_field"]]
        matched = compare(actual, node["op"], expected, node.get("value_type") == "number")
        extra["expected"] = expected
    else:
        actual = current[node["field"]]
        known = any(e["fields"].get(node["field"]) == actual for e in events)
        extra["history_state"] = "EMPTY" if not events else "KNOWN" if known else "NEW"
        matched = bool(node.get("on_empty", False)) if not events else not known
    return matched, {"kind": kind, "actual": actual, "matched": matched, "op": node.get("op"), "threshold": node.get("value"), "history_count": len(events), "include_current": node.get("include_current", False), "event_ids": [e["event_id"] for e in events], "period_seconds": node.get("period_seconds"), "group_by": node.get("group_by", []), "statuses": node["statuses"], **extra}
