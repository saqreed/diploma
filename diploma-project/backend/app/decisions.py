"""Decision creation, idempotency, snapshots and state transitions."""
from datetime import timedelta
import json
import logging

from sqlalchemy import and_, false, func, or_, select, text

from app.models import Application, Decision, Event, Rule, Source, Transition, Watchlist
from app.rules import RuleError, evaluate, number
from app.sources import read_source

TERMINAL = {"REJECTED", "CANCELLED", "EXPIRED"}


class DomainError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status


async def db_time(session):
    return await session.scalar(select(func.clock_timestamp()))


async def lock_key(session, value):
    # Transaction-scoped locks serialize requests even before a unique row exists.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:value, 0))"), {"value": value})


def transition(session, decision, state, actor, comment=""):
    before = decision.state
    decision.state = state
    session.add(Transition(decision_id=decision.id, before=before, after=state, actor=actor, comment=comment))


async def expire(session, decision):
    if decision.state not in TERMINAL and decision.executed_at is None and await db_time(session) >= decision.expires_at:
        transition(session, decision, "EXPIRED", "system", "Истёк первоначальный срок действия")


def view(decision):
    remaining = []
    if decision.needs_review and not decision.review_done:
        remaining.append("REVIEW")
    if decision.needs_confirmation and not decision.confirmation_done:
        remaining.append("CONFIRM")
    return {"id": decision.id, "application_id": decision.application_id, "operation_id": decision.operation_id,
            "action": decision.action, "initiator": decision.initiator, "record_key": decision.record_key,
            "checked_values": decision.checked_values, "state": decision.state, "remaining_steps": remaining,
            "created_at": decision.created_at.isoformat(), "expires_at": decision.expires_at.isoformat(),
            "executed_at": decision.executed_at.isoformat() if decision.executed_at else None, "reasons": decision.reasons}


def typed_fields(values, config, require=True):
    normalized = {}
    for name, spec in config.items():
        if name not in values or values[name] is None:
            if require and spec.get("required", False):
                raise RuleError(f"Обязательное поле {name} отсутствует")
            continue
        value = values[name]
        kind = spec["type"]
        if kind == "number":
            value = format(number(value).normalize(), "f")
        elif kind == "string" and not isinstance(value, str):
            raise RuleError(f"Поле {name} должно быть строкой")
        elif kind == "boolean" and not isinstance(value, bool):
            raise RuleError(f"Поле {name} должно быть логическим")
        normalized[name] = value
    return normalized


async def resolve_values(session, application, request):
    if request.action not in application.catalog:
        raise RuleError("Тип действия не зарегистрирован")
    config = application.catalog[request.action]["fields"]
    unknown = set(request.fields) - set(config)
    if unknown:
        raise RuleError("Переданы незарегистрированные поля: " + ", ".join(sorted(unknown)))
    values = {name: value for name, value in request.fields.items() if config[name].get("source", "API") == "API"}
    db_names = [name for name, spec in config.items() if spec.get("source") == "DB"]
    if db_names:
        source = await session.get(Source, application.id)
        if source is None:
            raise RuleError("Источник БД не настроен")
        db_values = await read_source(source, request.record_key)
        values.update({name: db_values[name] for name in db_names if name in db_values})
    return typed_fields(values, config)


def history_nodes(node):
    if not node:
        return []
    kind = node["kind"]
    if kind in {"all", "any"}:
        return [leaf for child in node["children"] for leaf in history_nodes(child)]
    if kind == "not":
        return history_nodes(node["child"])
    if kind == "field" or (kind == "related" and node.get("relation") == "current"):
        return []
    return [node]


async def load_history(session, application, rules, values, at):
    predicates = []
    seen = set()
    for rule in rules:
        for node in history_nodes(rule.expression) + history_nodes(rule.exception):
            if any(name not in values for name in node.get("group_by", [])):
                continue  # The evaluator still reports the missing field and blocks the decision.
            lower = max(application.history_from, at - timedelta(seconds=node["period_seconds"])) if node.get("period_seconds") else application.history_from
            signature = (tuple(sorted(node["event_types"])), tuple(sorted(node["statuses"])), lower, tuple(sorted(node.get("group_by", []))))
            if signature in seen:
                continue
            seen.add(signature)
            conditions = [Event.action.in_(node["event_types"]), Event.status.in_(node["statuses"]), Event.event_at >= lower]
            for name in node.get("group_by", []):
                column = Event.fields[name]
                conditions.append(column.as_boolean() == values[name] if isinstance(values[name], bool) else column.as_string() == str(values[name]))
            predicates.append(and_(*conditions))
    if not predicates:
        return []
    # Read only the union of eligible windows/groups, and only columns the evaluator uses.
    # Individual rule filters remain in the deterministic evaluator, preserving traces and boundaries.
    query = select(Event.event_id, Event.event_at, Event.action, Event.status, Event.fields, Event.operation_id).where(
        Event.application_id == application.id, Event.event_at <= at, or_(*predicates) if predicates else false())
    return [dict(row) for row in (await session.execute(query)).mappings()]


async def make_check(session, request, request_id=None):
    await lock_key(session, "check:" + request.application_id + ":" + request.operation_id)
    application = await session.get(Application, request.application_id)
    existing = await session.scalar(select(Decision).where(Decision.application_id == request.application_id, Decision.operation_id == request.operation_id).with_for_update())
    payload = request.model_dump(mode="json")
    if existing and existing.request != payload:
        raise DomainError("operation_changed", "Данные этой операции изменились. Создайте новую операцию")
    try:
        values = await resolve_values(session, application, request)
    except Exception as exc:
        logging.getLogger("antifraud").warning("check_failed %s", json.dumps({"request_id": request_id, "application_id": request.application_id, "operation_id": request.operation_id, "stage": "resolve_fields", "error_type": type(exc).__name__}))
        # The caller returns a persisted non-allowing decision; secret-bearing driver errors never escape.
        if existing:
            if existing.state not in TERMINAL and existing.executed_at is None:
                transition(session, existing, "CANCELLED", "system", "Источник недоступен или данные некорректны")
            return view(existing)
        values = {}
        failure = str(exc) if isinstance(exc, RuleError) else "Не удалось прочитать настроенный источник данных"
    else:
        failure = None
    if existing:
        await expire(session, existing)
        if existing.checked_values != values:
            if existing.state not in TERMINAL and existing.executed_at is None:
                transition(session, existing, "CANCELLED", "system", "Изменились проверенные данные источника")
        return view(existing)
    at = await db_time(session)
    rules = (await session.scalars(select(Rule).where(Rule.application_id == application.id, Rule.action == request.action, Rule.enabled.is_(True)).order_by(Rule.id))).all()
    history = await load_history(session, application, rules, values, at) if failure is None else []
    lists = {w.id: w.values for w in (await session.scalars(select(Watchlist).where(Watchlist.application_id == application.id))).all()}
    reasons, reactions = [], set()
    if failure:
        reasons.append({"error": "source_or_field_error", "message": failure})
        reactions.add("BLOCK")
    else:
        for rule in rules:
            try:
                excluded, exception_trace = evaluate(rule.exception, values, history, at, lists, request.operation_id) if rule.exception else (False, None)
                matched, trace = evaluate(rule.expression, values, history, at, lists, request.operation_id) if not excluded else (False, {"excluded": True})
                reasons.append({"rule_id": rule.id, "name": rule.name, "version": rule.version, "reaction": rule.reaction,
                                "expression": rule.expression, "exception": rule.exception, "exception_trace": exception_trace, "matched": matched, "trace": trace})
                if matched:
                    reactions.add(rule.reaction)
            except RuleError as exc:
                reactions.add("BLOCK")
                reasons.append({"rule_id": rule.id, "error": "evaluation_error", "message": str(exc)})
    state = "REJECTED" if "BLOCK" in reactions else "PENDING_REVIEW" if "REVIEW" in reactions else "PENDING_CONFIRMATION" if "CONFIRM" in reactions else "APPROVED"
    decision = Decision(application_id=application.id, operation_id=request.operation_id, action=request.action,
                        initiator=request.initiator, record_key=request.record_key, request=payload, checked_values=values,
                        reasons=reasons, state=state, needs_review="REVIEW" in reactions, needs_confirmation="CONFIRM" in reactions,
                        created_at=at, expires_at=at + timedelta(seconds=application.ttl_seconds))
    session.add(decision)
    await session.flush()
    session.add(Transition(decision_id=decision.id, before=None, after=state, actor="engine", comment="Первоначальное решение"))
    await expire(session, decision)
    return view(decision)


async def record_event(session, event):
    await lock_key(session, "event:" + event.application_id + ":" + event.event_id)
    payload = event.model_dump(mode="json")
    existing = await session.scalar(select(Event).where(Event.application_id == event.application_id, Event.event_id == event.event_id))
    if existing:
        if existing.payload != payload:
            raise DomainError("event_changed", "Идентификатор события уже использован с другими данными")
        return {"id": existing.id, "duplicate": True}
    application = await session.get(Application, event.application_id)
    if event.action not in application.catalog:
        raise RuleError("Неизвестный тип события")
    fields = typed_fields(event.fields, application.catalog[event.action]["fields"])
    if event.decision_id:
        decision = await session.get(Decision, event.decision_id)
        if not decision or (decision.application_id, decision.operation_id, decision.action, decision.initiator) != (event.application_id, event.operation_id, event.action, event.actor):
            raise DomainError("event_binding", "Событие не соответствует проверенной операции")
    row = Event(application_id=event.application_id, event_id=event.event_id, event_at=event.event_at,
                action=event.action, actor=event.actor, status=event.status, fields=fields, operation_id=event.operation_id,
                decision_id=event.decision_id, payload=payload)
    session.add(row)
    await session.flush()
    return {"id": row.id, "duplicate": False}
