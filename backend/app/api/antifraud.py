"""HTTP adapters. Business checks and execution live in their own modules."""
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import case, delete, select, func

from app.access import application_access, require, user
from app.contracts import ApplicationInput, ApplicationConfirmation, ApplicationCancellation, CheckInput, ConfirmInput, CreateWatchlistInput, DemoCheck, EventInput, ExecuteInput, ExpenseInput, LoginInput, OperationInput, ResetInput, RuleInput, TransitionInput, WatchlistInput
from app.decisions import DomainError, TERMINAL, db_time, expire, lock_key, make_check, record_event, transition, view
from app.demo import antifraud_call, authorize_action, deliver_outbox, execute, expense_view, fields, registry_fields, validate_demo_catalog
from app.models import Account, Application, Decision, Event, Execution, Expense, LoginSession, Outbox, ResetArchive, Rule, Source, Template, Transition, Watchlist
from app.rules import RuleError, field_names, validate_catalog, validate_expression
from app.runtime import antifraud_sessions, demo_sessions
from app.security import digest, verify_password
from app.sources import cipher, read_source, validate_source
from app.demo_seed import seed_data

router = APIRouter(prefix="/api")


def account_view(account):
    return {"id": account.id, "username": account.username, "name": account.name, "role": account.role}


def rule_view(rule):
    return {key: getattr(rule, key) for key in ("id", "application_id", "name", "action", "expression", "reaction", "enabled", "exception", "version")}


def referenced_event_ids(value):
    if isinstance(value, list):
        return {event_id for child in value for event_id in referenced_event_ids(child)}
    if isinstance(value, dict):
        return set(value.get("event_ids", [])) | {event_id for key, child in value.items() if key != "event_ids" for event_id in referenced_event_ids(child)}
    return set()


async def save_rule(session, payload, rule_id=None):
    application = await session.get(Application, payload.application_id)
    if not application or payload.action not in application.catalog:
        raise RuleError("Приложение или тип действия не найден")
    lists = {w.id: w.values for w in (await session.scalars(select(Watchlist).where(Watchlist.application_id == application.id))).all()}
    config = application.catalog[payload.action]["fields"]
    validate_expression(payload.expression, config, application.catalog, lists=lists)
    if payload.exception:
        validate_expression(payload.exception, config, application.catalog, lists=lists)
    required = field_names(payload.expression) | (field_names(payload.exception) if payload.exception else set())
    db_fields = {name for name in required if config[name].get("source") == "DB"}
    if db_fields:
        source = await session.get(Source, application.id)
        if not source or not db_fields.issubset(source.mapping):
            raise RuleError("Для полей правила не настроено сопоставление источника БД")
    if rule_id:
        rule = await session.get(Rule, rule_id)
        if not rule:
            raise DomainError("rule_missing", "Правило не найдено", 404)
        for key, value in payload.model_dump().items():
            setattr(rule, key, value)
        rule.version += 1
    else:
        rule = Rule(**payload.model_dump())
        session.add(rule)
    await session.flush()
    return rule_view(rule)


@router.post("/auth/login")
async def login(payload: LoginInput, response: Response):
    async with antifraud_sessions().begin() as session:
        account = await session.scalar(select(Account).where(Account.username == payload.username))
        if not account or not verify_password(payload.password, account.password_hash):
            raise DomainError("invalid_credentials", "Неверный логин или пароль", 401)
        token = secrets.token_urlsafe(32)
        session.add(LoginSession(token_hash=digest(token), account_id=account.id, expires_at=await db_time(session) + timedelta(hours=8)))
        response.set_cookie("antifraud_session", token, httponly=True, samesite="strict", max_age=28800,
                            secure=os.environ.get("DIPLOMA_SECURE_COOKIES") == "true", path="/api")
        return account_view(account)


@router.get("/auth/me")
async def me(account=Depends(user)):
    return account_view(account)


@router.post("/auth/logout")
async def logout(request: Request, response: Response, account=Depends(user)):
    async with antifraud_sessions().begin() as session:
        await session.execute(delete(LoginSession).where(LoginSession.token_hash == request.state.session_token_hash))
    response.delete_cookie("antifraud_session", path="/api")
    return {"message": "Сеанс завершён"}


@router.get("/admin/applications")
async def applications(account=Depends(user)):
    require(account, "admin", "specialist")
    async with antifraud_sessions()() as session:
        rows = (await session.scalars(select(Application).order_by(Application.id))).all()
        return [{"id": row.id, "name": row.name, "catalog": row.catalog, "ttl_seconds": row.ttl_seconds} for row in rows]


@router.post("/admin/applications")
async def create_application(payload: ApplicationInput, account=Depends(user)):
    require(account, "admin")
    validate_catalog(payload.catalog)
    if payload.id == "demo":
        validate_demo_catalog(payload.catalog)
    async with antifraud_sessions().begin() as session:
        if await session.get(Application, payload.id):
            raise DomainError("application_exists", "Идентификатор приложения уже используется")
        key = secrets.token_urlsafe(32)
        session.add(Application(**payload.model_dump(), api_key_hash=digest(key)))
    return {"id": payload.id, "api_key": key, "message": "Сохраните ключ: повторно он не отображается"}


@router.put("/admin/applications/{application_id}")
async def update_application(application_id: str, payload: ApplicationInput, account=Depends(user)):
    require(account, "admin")
    if payload.id != application_id:
        raise RuleError("Идентификатор приложения изменять нельзя")
    validate_catalog(payload.catalog)
    if application_id == "demo":
        validate_demo_catalog(payload.catalog)
    async with antifraud_sessions().begin() as session:
        application = await session.get(Application, application_id)
        if not application:
            raise DomainError("application_missing", "Приложение не найдено", 404)
        # Retained rules and templates must stay editable, including disabled ones.
        lists = {w.id: w.values for w in (await session.scalars(select(Watchlist).where(Watchlist.application_id == application_id))).all()}
        retained = []
        for model in (Rule, Template):
            retained.extend((await session.scalars(select(model).where(model.application_id == application_id))).all())
        for rule in retained:
            if rule.action not in payload.catalog:
                raise RuleError("Сначала удалите или перенастройте правила и шаблоны этого типа события, включая отключённые")
            validate_expression(rule.expression, payload.catalog[rule.action]["fields"], payload.catalog, lists=lists)
            if rule.exception:
                validate_expression(rule.exception, payload.catalog[rule.action]["fields"], payload.catalog, lists=lists)
        application.name, application.catalog, application.ttl_seconds = payload.name, payload.catalog, payload.ttl_seconds
    return {"id": application_id}


@router.get("/admin/rules")
async def rules(application_id: str = "demo", account=Depends(user)):
    require(account, "admin", "specialist")
    async with antifraud_sessions()() as session:
        return [rule_view(row) for row in (await session.scalars(select(Rule).where(Rule.application_id == application_id).order_by(Rule.name))).all()]


@router.post("/admin/rules")
async def create_rule(payload: RuleInput, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as session:
        return await save_rule(session, payload)


@router.put("/admin/rules/{rule_id}")
async def update_rule(rule_id: str, payload: RuleInput, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as session:
        return await save_rule(session, payload, rule_id)


@router.get("/admin/templates")
async def templates(application_id: str = "demo", account=Depends(user)):
    require(account, "admin")
    builtin = [{"id": kind, "kind": kind, "builtin": True, "name": name} for kind, name in (
        ("field", "Условие по полю"), ("duplicate", "Повтор операции"), ("count", "Количество событий"),
        ("aggregate", "Сумма или уникальные значения"), ("sequence", "Последовательность"),
        ("previous", "Обязательное предыдущее событие"), ("related", "Связанные данные"), ("novelty", "Новизна значения"))]
    async with antifraud_sessions()() as session:
        saved = [{"id": t.id, "builtin": False, "kind": t.expression["kind"], "application_id": t.application_id, "name": t.name,
                  "action": t.action, "expression": t.expression, "reaction": t.reaction, "exception": t.exception, "version": t.version}
                 for t in (await session.scalars(select(Template).where(Template.application_id == application_id).order_by(Template.name))).all()]
    return builtin + saved


@router.post("/admin/templates")
@router.put("/admin/templates/{template_id}")
async def save_template(payload: RuleInput, template_id: str | None = None, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as session:
        application = await session.get(Application, payload.application_id)
        if not application or payload.action not in application.catalog:
            raise RuleError("Выберите приложение и тип события")
        lists = {w.id: w.values for w in (await session.scalars(select(Watchlist).where(Watchlist.application_id == application.id))).all()}
        config = application.catalog[payload.action]["fields"]
        validate_expression(payload.expression, config, application.catalog, lists=lists)
        if payload.exception:
            validate_expression(payload.exception, config, application.catalog, lists=lists)
        required = field_names(payload.expression) | (field_names(payload.exception) if payload.exception else set())
        db_fields = {name for name in required if config[name].get("source") == "DB"}
        if db_fields:
            source = await session.get(Source, application.id)
            if not source or not db_fields.issubset(source.mapping):
                raise RuleError("Для полей шаблона не настроено сопоставление источника БД")
        values = payload.model_dump(exclude={"enabled"})
        if template_id:
            row = await session.get(Template, template_id)
            if not row:
                raise RuleError("Сохранённый шаблон не найден")
            for key, value in values.items():
                setattr(row, key, value)
            row.version += 1
        else:
            row = Template(**values)
            session.add(row)
        await session.flush()
        return {"id": row.id, "version": row.version}


@router.delete("/admin/templates/{template_id}")
async def remove_template(template_id: str, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as session:
        row = await session.get(Template, template_id)
        if not row:
            raise RuleError("Сохранённый шаблон не найден")
        await session.delete(row)
    return {"deleted": True}


@router.get("/admin/watchlists")
async def lists(application_id: str = "demo", account=Depends(user)):
    require(account, "admin", "specialist")
    async with antifraud_sessions()() as session:
        return [{"id": w.id, "name": w.name, "values": w.values, "application_id": w.application_id} for w in (await session.scalars(select(Watchlist).where(Watchlist.application_id == application_id))).all()]


@router.post("/admin/watchlists")
async def create_list(payload: CreateWatchlistInput, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as session:
        if not await session.get(Application, payload.application_id):
            raise RuleError("Приложение не найдено")
        row = Watchlist(**payload.model_dump())
        session.add(row)
        await session.flush()
        return {"id": row.id}


@router.put("/admin/watchlists/{list_id}")
async def update_list(list_id: str, payload: WatchlistInput, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as session:
        row = await session.get(Watchlist, list_id)
        if row is None:
            raise RuleError("Список не найден")
        values = {w.id: w.values for w in (await session.scalars(select(Watchlist).where(Watchlist.application_id == row.application_id))).all()}
        values[list_id] = payload.values
        application = await session.get(Application, row.application_id)
        for model in (Rule, Template):
            for item in (await session.scalars(select(model).where(model.application_id == row.application_id))).all():
                if item.action not in application.catalog:
                    raise RuleError("Перенастройте правило или шаблон: его тип события удалён из каталога")
                config = application.catalog[item.action]["fields"]
                validate_expression(item.expression, config, application.catalog, lists=values)
                if item.exception:
                    validate_expression(item.exception, config, application.catalog, lists=values)
        row.name, row.values = payload.name, payload.values
    return {"id": list_id}


@router.delete("/admin/watchlists/{list_id}")
async def delete_list(list_id: str, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as session:
        row = await session.get(Watchlist, list_id)
        if row is None:
            raise RuleError("Список не найден")
        for model in (Rule, Template):
            if any(list_id in str(item.expression) or list_id in str(item.exception) for item in (await session.scalars(select(model).where(model.application_id == row.application_id))).all()):
                raise RuleError("Список используется правилом или шаблоном. Сначала измените настройку")
        await session.delete(row)
    return {"deleted": True}


@router.get("/admin/sources/{application_id}")
async def source_view(application_id: str, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions()() as session:
        row = await session.get(Source, application_id)
        if not row:
            return None
        return {"application_id": row.application_id, "table_name": row.table_name, "key_field": row.key_field,
                "allowed_fields": row.allowed_fields, "mapping": row.mapping, "credentials_saved": True}


@router.put("/admin/sources/{application_id}")
async def save_source(application_id: str, payload: dict, account=Depends(user)):
    require(account, "admin")
    if set(payload) != {"url", "table_name", "key_field", "allowed_fields", "mapping"}:
        raise RuleError("Укажите подключение, таблицу, ключ, разрешённые поля и сопоставление")
    validate_source(payload)
    async with antifraud_sessions().begin() as session:
        application = await session.get(Application, application_id)
        if not application:
            raise RuleError("Приложение не найдено")
        known = {name for config in application.catalog.values() for name in config["fields"]}
        if not set(payload["mapping"]).issubset(known):
            raise RuleError("Сопоставление использует незарегистрированное поле приложения")
        row = await session.get(Source, application_id)
        if row is None:
            row = Source(application_id=application_id)
            session.add(row)
        row.encrypted_url = cipher().encrypt(payload["url"].encode()).decode()
        for key in ("table_name", "key_field", "allowed_fields", "mapping"):
            setattr(row, key, payload[key])
    return {"message": "Источник сохранён. Пароль больше не отображается"}


@router.post("/checks")
async def checks(payload: CheckInput, request: Request, x_application_key: str = Header(default="")):
    request.state.stage = "check"
    async with antifraud_sessions().begin() as session:
        await application_access(session, payload.application_id, x_application_key)
        return await make_check(session, payload, request.state.request_id)


@router.post("/events")
async def events(payload: EventInput, x_application_key: str = Header(default="")):
    async with antifraud_sessions().begin() as session:
        await application_access(session, payload.application_id, x_application_key)
        return await record_event(session, payload)


@router.get("/journal")
async def journal(application_id: str | None = None, action: str | None = None, initiator: str | None = None,
                  state: str | None = None, operation_id: str | None = None, start: datetime | None = None,
                  end: datetime | None = None, limit: int = 100, offset: int = 0, account=Depends(user)):
    require(account, "admin", "specialist")
    if any(value and value.tzinfo is None for value in (start, end)) or (start and end and start > end):
        raise RuleError("Укажите часовой пояс и корректный период журнала")
    query = select(Decision)
    for field, value in ((Decision.application_id, application_id), (Decision.action, action), (Decision.initiator, initiator), (Decision.operation_id, operation_id)):
        if value is not None:
            query = query.where(field == value)
    if start:
        query = query.where(Decision.created_at >= start)
    if end:
        query = query.where(Decision.created_at <= end)
    if state:
        effective = case((Decision.executed_at.is_(None) & Decision.state.not_in(TERMINAL) & (Decision.expires_at <= func.clock_timestamp()), "EXPIRED"), else_=Decision.state)
        query = query.where(effective == state)
    if not 1 <= limit <= 200 or offset < 0:
        raise RuleError("Лимит должен быть 1–200, смещение — неотрицательным")
    async with antifraud_sessions().begin() as session:
        rows = (await session.scalars(query.order_by(Decision.created_at.desc()).limit(limit).offset(offset).with_for_update())).all()
        for row in rows:
            await expire(session, row)
        return [view(row) for row in rows]


@router.get("/decisions/{decision_id}")
async def decision_detail(decision_id: str, account=Depends(user)):
    async with antifraud_sessions().begin() as session:
        row = await session.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
        if row is None:
            raise DomainError("decision_missing", "Решение не найдено", 404)
        if account.role not in {"admin", "specialist"} and (row.application_id != "demo" or row.initiator != account.id):
            raise DomainError("not_initiator", "Решение недоступно этому пользователю", 403)
        await expire(session, row)
        result = view(row)
        await session.flush()
        result["transitions"] = [{"before": t.before, "after": t.after, "actor": t.actor, "comment": t.comment, "at": t.created_at.isoformat()} for t in (await session.scalars(select(Transition).where(Transition.decision_id == row.id).order_by(Transition.created_at))).all()]
        result["events"] = [e.payload for e in (await session.scalars(select(Event).where(Event.decision_id == row.id))).all()]
        ids = referenced_event_ids(row.reasons)
        result["related_events_count"] = len(ids)
        result["related_events"] = [e.payload for e in (await session.scalars(select(Event).where(Event.application_id == row.application_id, Event.event_id.in_(ids)).order_by(Event.event_at, Event.event_id).limit(100))).all()] if ids else []
        return result


@router.get("/decisions/{decision_id}/related-events")
async def related_events(decision_id: str, offset: int = 0, account=Depends(user)):
    if offset < 0:
        raise RuleError("Смещение должно быть неотрицательным")
    async with antifraud_sessions()() as session:
        row = await session.get(Decision, decision_id)
        if row is None:
            raise DomainError("decision_missing", "Решение не найдено", 404)
        if account.role not in {"admin", "specialist"} and (row.application_id != "demo" or row.initiator != account.id):
            raise DomainError("not_initiator", "События недоступны этому пользователю", 403)
        ids = referenced_event_ids(row.reasons)
        return [e.payload for e in (await session.scalars(select(Event).where(Event.application_id == row.application_id, Event.event_id.in_(ids)).order_by(Event.event_at, Event.event_id).limit(100).offset(offset))).all()] if ids else []


@router.post("/decisions/{decision_id}/review")
async def review(decision_id: str, payload: TransitionInput, account=Depends(user)):
    require(account, "specialist")
    error = None
    async with antifraud_sessions().begin() as session:
        row = await session.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
        if not row:
            raise DomainError("decision_missing", "Решение не найдено", 404)
        await expire(session, row)
        if row.state != "PENDING_REVIEW":
            error = DomainError("review_not_pending", "Эта проверка уже не ожидает рассмотрения")
        else:
            row.review_done = payload.approve
            state = "REJECTED" if not payload.approve else "PENDING_CONFIRMATION" if row.needs_confirmation else "APPROVED"
            transition(session, row, state, account.id, payload.comment)
        result = view(row)
    if error:
        raise error
    return result


@router.post("/demo/decisions/{decision_id}/confirm")
async def confirm(decision_id: str, payload: ConfirmInput, account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    error = None
    async with antifraud_sessions().begin() as session:
        row = await session.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
        if not row or row.application_id != "demo" or row.initiator != account.id or row.operation_id != payload.operation_id:
            raise DomainError("confirmation_binding", "Подтверждать может только инициатор своей операции", 403)
        await expire(session, row)
        if row.state != "PENDING_CONFIRMATION":
            error = DomainError("confirmation_not_pending", "Подтверждение сейчас недоступно")
        elif row.checked_values != payload.checked_values:
            error = DomainError("confirmation_values", "Подтверждаемые значения не совпадают с проверенными")
        else:
            application = await session.get(Application, "demo")
            async with demo_sessions()() as demo_session:
                if row.action == "export":
                    records = (await demo_session.scalars(select(Expense).order_by(Expense.id))).all()
                    actual = registry_fields(records, account.id)
                else:
                    record = await demo_session.get(Expense, row.record_key)
                    actual = fields(record, account.id) if record else {}
            from app.decisions import typed_fields
            try:
                actual = typed_fields(actual, application.catalog[row.action]["fields"])
            except RuleError:
                actual = None
            if payload.approve and actual != row.checked_values:
                transition(session, row, "CANCELLED", "demo", "Данные изменились до подтверждения; нужна новая попытка")
                error = DomainError("data_changed", "Данные изменились. Создайте новую попытку")
            else:
                await expire(session, row)
                if row.state != "PENDING_CONFIRMATION":
                    error = DomainError("confirmation_not_pending", "Срок подтверждения истёк")
                else:
                    row.confirmation_done = payload.approve
                    transition(session, row, "APPROVED" if payload.approve else "CANCELLED", account.id, payload.comment)
        result = view(row)
    if error:
        raise error
    return result


@router.get("/demo/decisions")
async def own_decisions(account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    async with antifraud_sessions().begin() as session:
        rows = (await session.scalars(select(Decision).where(Decision.application_id == "demo", Decision.initiator == account.id).order_by(Decision.created_at.desc()).limit(50).with_for_update())).all()
        for row in rows:
            await expire(session, row)
        return [view(row) for row in rows]


@router.post("/demo/decisions/{decision_id}/cancel")
async def cancel(decision_id: str, account=Depends(user)):
    error = None
    async with antifraud_sessions().begin() as session:
        row = await session.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
        if not row or row.application_id != "demo" or row.initiator != account.id:
            raise DomainError("cancellation_binding", "Отменить может только инициатор своей попытки", 403)
        await expire(session, row)
        if row.executed_at or row.state in TERMINAL:
            error = DomainError("cannot_cancel", "Эта попытка уже выполнена или завершена")
        else:
            transition(session, row, "CANCELLED", account.id, "Отменено инициатором")
        result = view(row)
    if error:
        raise error
    return result


@router.get("/demo/requests")
async def demo_requests(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    async with demo_sessions()() as session:
        query = select(Expense).order_by(Expense.created_at.desc(), Expense.id).limit(limit).offset(offset)
        if account.role == "employee":
            query = query.where(Expense.author == account.id)
        return [expense_view(row) for row in (await session.scalars(query)).all()]


@router.post("/demo/requests")
async def create_expense(payload: ExpenseInput, account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    async with demo_sessions().begin() as session:
        await lock_key(session, "demo:records")
        row = Expense(author=account.id, **payload.model_dump(), history=[{"action": "created", "actor": account.id, "version": 1}])
        session.add(row)
        await session.flush()
        return expense_view(row)


@router.put("/demo/requests/{expense_id}")
async def edit_expense(expense_id: str, payload: ExpenseInput, account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    async with demo_sessions().begin() as session:
        await lock_key(session, "demo:records")
        row = await session.scalar(select(Expense).where(Expense.id == expense_id).with_for_update())
        if row is None or row.author != account.id:
            raise DomainError("not_author", "Редактировать можно только свою заявку", 403)
        if row.status == "PAID":
            raise DomainError("already_paid", "Выплаченная заявка не редактируется")
        before = {key: value for key, value in expense_view(row).items() if key != "history"}
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
        row.version += 1
        row.status, row.approver, row.approved_version = "DRAFT", None, None
        row.history = [*row.history, {"action": "edited", "actor": account.id, "at": (await db_time(session)).isoformat(), "before": before, "version": row.version}]
        result = expense_view(row)
    # Release the expense lock before acquiring decision locks (execution takes them in that order).
    # Any concurrent execution after the edit must independently reject the changed snapshot.
    async with antifraud_sessions().begin() as session:
        decisions = (await session.scalars(select(Decision).where(Decision.application_id == "demo", Decision.record_key == expense_id,
                     Decision.executed_at.is_(None), Decision.state.not_in(TERMINAL)).order_by(Decision.id).with_for_update())).all()
        for decision in decisions:
            await expire(session, decision)
            if decision.state not in TERMINAL:
                transition(session, decision, "CANCELLED", account.id, "Заявка изменена; требуется новая проверка актуальной версии")
    return result


@router.post("/demo/requests/{expense_id}/check")
async def demo_check(expense_id: str, payload: DemoCheck, account=Depends(user)):
    async with demo_sessions()() as session:
        row = await session.get(Expense, expense_id)
        if row is None:
            raise DomainError("request_missing", "Заявка не найдена", 404)
        authorize_action(account, row, payload.action)
        if payload.version is not None and row.version != payload.version:
            raise DomainError("data_changed", "Заявка изменена. Откройте актуальные значения перед действием")
        values = fields(row, account.id)
    return await antifraud_call("/api/checks", {"application_id": "demo", "operation_id": payload.operation_id, "action": payload.action,
                                              "initiator": account.id, "record_key": expense_id, "fields": values})


@router.post("/demo/export/check")
async def export_check(payload: OperationInput, account=Depends(user)):
    require(account, "accountant")
    async with demo_sessions()() as session:
        rows = (await session.scalars(select(Expense).order_by(Expense.id))).all()
        values = registry_fields(rows, account.id)
    return await antifraud_call("/api/checks", {"application_id": "demo", "operation_id": payload.operation_id, "action": "export", "initiator": account.id, "fields": values})


@router.post("/demo/execute")
async def demo_execute(payload: ExecuteInput, account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    async with antifraud_sessions()() as session:
        application = await session.get(Application, "demo")
        catalog = application.catalog
    try:
        result = await execute(account, payload.operation_id, payload.decision_id, catalog)
    except DomainError as error:
        if error.code in {"data_changed", "decision_expired"}:
            async with antifraud_sessions().begin() as session:
                row = await session.scalar(select(Decision).where(Decision.id == payload.decision_id).with_for_update())
                if row and not row.executed_at and row.state not in TERMINAL:
                    transition(session, row, "CANCELLED" if error.code == "data_changed" else "EXPIRED", "demo", error.message)
        raise
    try:
        delivery = await deliver_outbox()
        result = {**result, "event_delivery": delivery}
    except DomainError:
        result = {**result, "event_delivery": {"pending": True, "message": "Действие сохранено. Событие ожидает повторной доставки"}}
    return result


@router.post("/demo/outbox/deliver")
async def outbox_delivery(account=Depends(user)):
    require(account, "accountant", "admin")
    return await deliver_outbox()


@router.post("/demo/reset")
async def reset_demo(payload: ResetInput, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as af_session:
        await lock_key(af_session, "check:demo:reset")
        decisions = (await af_session.scalars(select(Decision).where(Decision.application_id == "demo").order_by(Decision.id).with_for_update())).all()
        application = await af_session.get(Application, "demo")
        async with demo_sessions().begin() as session:
            await lock_key(session, "demo:records")
            rows = (await session.scalars(select(Expense).order_by(Expense.id).with_for_update())).all()
            archive = ResetArchive(actor=account.id, snapshot={"requests": [expense_view(row) for row in rows]})
            session.add(archive)
            await session.flush()
            await session.execute(delete(Expense))
            for data in seed_data():
                session.add(Expense(**data))
            at = await db_time(session)
            for decision in decisions:
                if decision.executed_at is None and decision.state not in TERMINAL:
                    transition(af_session, decision, "CANCELLED", account.id, "Возврат учебного демо; заявки сохранены в архиве")
            application.history_from = at
        return {"archive_id": archive.id, "archived_requests": len(rows), "message": "Учебные заявки восстановлены; прежние данные и журнал сохранены"}


@router.get("/checks/{decision_id}")
async def application_decision(decision_id: str, x_application_key: str = Header(default="")):
    async with antifraud_sessions().begin() as session:
        row = await session.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
        if row is None:
            raise DomainError("decision_missing", "Решение не найдено", 404)
        await application_access(session, row.application_id, x_application_key)
        await expire(session, row)
        return view(row)


@router.post("/checks/{decision_id}/confirmation")
async def application_confirmation(decision_id: str, payload: ApplicationConfirmation, x_application_key: str = Header(default="")):
    # The integrating application authenticates its initiator's session. Demo must use its session endpoint.
    error = None
    async with antifraud_sessions().begin() as session:
        row = await session.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
        if row is None:
            raise DomainError("decision_missing", "Решение не найдено", 404)
        await application_access(session, row.application_id, x_application_key)
        if row.application_id == "demo" or (row.operation_id, row.initiator) != (payload.operation_id, payload.initiator):
            raise DomainError("confirmation_binding", "Подтверждение не соответствует инициатору приложения", 403)
        await expire(session, row)
        if row.state != "PENDING_CONFIRMATION" or row.checked_values != payload.checked_values:
            error = DomainError("confirmation_values", "Попытка не ожидает подтверждения этих значений")
        else:
            row.confirmation_done = payload.approve
            transition(session, row, "APPROVED" if payload.approve else "CANCELLED", payload.initiator, payload.comment)
        result = view(row)
    if error:
        raise error
    return result


@router.post("/checks/{decision_id}/cancel")
async def application_cancel(decision_id: str, payload: ApplicationCancellation, x_application_key: str = Header(default="")):
    error = None
    async with antifraud_sessions().begin() as session:
        row = await session.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
        if row is None:
            raise DomainError("decision_missing", "Решение не найдено", 404)
        await application_access(session, row.application_id, x_application_key)
        if row.application_id == "demo" or (row.operation_id, row.initiator) != (payload.operation_id, payload.initiator):
            raise DomainError("cancellation_binding", "Отмена не соответствует инициатору приложения", 403)
        await expire(session, row)
        if row.executed_at or row.state in TERMINAL:
            error = DomainError("cannot_cancel", "Попытка уже завершена")
        else:
            transition(session, row, "CANCELLED", payload.initiator, "Отмена инициатором подключённого приложения")
        result = view(row)
    if error:
        raise error
    return result
