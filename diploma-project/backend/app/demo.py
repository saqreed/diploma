"""Demo owns all writes to its records; check and execution share one transaction."""
import hashlib
import json
import os

import httpx2 as httpx
from sqlalchemy import select

from app.access import require
from app.decisions import DomainError, db_time, typed_fields
from app.models import Application, Decision, Execution, Expense, Outbox
from app.runtime import demo_sessions
from app.demo_seed import DEMO_CATALOG
from app.rules import RuleError


def validate_demo_catalog(catalog):
    # These are the demo application's execution bindings, not engine fields.
    # Administrators may choose API/DB sources but cannot weaken its snapshot.
    for action, expected in DEMO_CATALOG.items():
        config = catalog.get(action, {}).get("fields", {})
        for name, spec in expected["fields"].items():
            if name not in config or config[name]["type"] != spec["type"] or config[name].get("required", False) != spec["required"]:
                raise RuleError(f"Демо требует поле {name} типа {spec['type']} для действия {action}; его нельзя убрать или изменить")


def expense_view(row):
    return {"id": row.id, "author": row.author, "amount": str(row.amount), "recipient": row.recipient,
            "receipt": row.receipt, "vendor": row.vendor, "purchase_date": row.purchase_date, "title": row.title,
            "version": row.version, "status": row.status, "approver": row.approver,
            "approved_version": row.approved_version, "history": row.history}


def fields(row, actor):
    return {"request_id": row.id, "author": row.author, "amount": str(row.amount), "recipient": row.recipient,
            "receipt": row.receipt, "vendor": row.vendor, "purchase_date": row.purchase_date, "title": row.title,
            "version": row.version, "initiator": actor, **({"approver": row.approver} if row.approver else {})}


def authorize_action(account, row, action):
    if action == "submit":
        require(account, "employee", "manager", "accountant")
        if row.author != account.id:
            raise DomainError("not_author", "Отправить можно только свою заявку", 403)
    elif action in {"approve", "reject"}:
        require(account, "manager")
        if row.author == account.id:
            raise DomainError("self_approval", "Автор не может согласовать собственную заявку", 403)
    elif action in {"pay", "export"}:
        require(account, "accountant")
    else:
        raise DomainError("invalid_action", "Действие не поддерживается демо", 422)


def registry_fields(rows, actor):
    # The final transaction locks every exported record, then compares the exact dataset/version fingerprint.
    serialized = json.dumps([expense_view(row) for row in rows], ensure_ascii=False, sort_keys=True)
    return {"record_count": len(rows), "initiator": actor, "registry_version": hashlib.sha256(serialized.encode()).hexdigest(), "registry_snapshot": serialized}


async def antifraud_call(path, payload):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(os.environ.get("DIPLOMA_ANTIFRAUD_URL", "http://127.0.0.1:8000") + path,
                                         json=payload, headers={"X-Application-Key": os.environ["DIPLOMA_DEMO_API_KEY"]})
        except httpx.HTTPError:
            raise DomainError("antifraud_unavailable", "Антифрод недоступен. Действие не выполнено", 503) from None
        if response.is_error:
            raise DomainError("antifraud_error", "Антифрод не принял запрос. Действие не выполнено", 409)
        return response.json()


async def execute(account, operation_id, decision_id, catalog):
    async with demo_sessions().begin() as session:
        decision = await session.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
        if not decision or decision.application_id != "demo" or decision.operation_id != operation_id or decision.initiator != account.id:
            raise DomainError("decision_binding", "Решение не принадлежит этой операции и инициатору", 403)
        existing = await session.get(Execution, operation_id)
        if existing:
            if existing.decision_id != decision_id or existing.initiator != account.id:
                raise DomainError("execution_conflict", "Операция уже выполнена другим решением", 409)
            return existing.result
        row = None
        if decision.action == "export":
            require(account, "accountant")
            # Transaction advisory lock also excludes insertion/editing during registry materialization.
            from app.decisions import lock_key
            await lock_key(session, "demo:records")
            rows = (await session.scalars(select(Expense).order_by(Expense.id).with_for_update())).all()
            actual = registry_fields(rows, account.id)
        else:
            row = await session.scalar(select(Expense).where(Expense.id == decision.record_key).with_for_update())
            if row is None:
                raise DomainError("request_missing", "Заявка не найдена", 404)
            authorize_action(account, row, decision.action)
            actual = fields(row, account.id)
        actual = typed_fields(actual, catalog[decision.action]["fields"])
        if decision.checked_values != actual:
            raise DomainError("data_changed", "Проверенные значения изменились. Нужна новая попытка")
        if decision.state != "APPROVED" or (decision.needs_review and not decision.review_done) or (decision.needs_confirmation and not decision.confirmation_done):
            raise DomainError("not_approved", "Антифрод ещё не разрешил действие")
        if row:
            if decision.action == "pay" and (row.status != "APPROVED" or row.approved_version != row.version):
                raise DomainError("business_approval", "Для выплаты требуется согласование актуальной заявки")
            if decision.action in {"approve", "reject"} and row.status != "SUBMITTED":
                raise DomainError("not_submitted", "Заявку нужно отправить на согласование")
            if decision.action == "submit" and row.status not in {"DRAFT", "REJECTED"}:
                raise DomainError("already_submitted", "Заявка уже отправлена или исполнена")
        now = await db_time(session)
        if now >= decision.expires_at:
            raise DomainError("decision_expired", "Срок решения истёк. Требуется новая проверка")
        if decision.executed_at:
            raise DomainError("decision_used", "Решение уже использовано")
        if row:
            if decision.action == "submit":
                row.status = "SUBMITTED"
            elif decision.action == "approve":
                row.status, row.approver, row.approved_version = "APPROVED", account.id, row.version
            elif decision.action == "reject":
                row.status = "REJECTED"
            elif decision.action == "pay":
                row.status = "PAID"
            row.history = [*row.history, {"action": decision.action, "actor": account.id, "at": now.isoformat(), "version": row.version, "operation_id": operation_id}]
            result = {"operation_id": operation_id, "decision_id": decision_id, "request": expense_view(row), "executed_at": now.isoformat()}
        else:
            result = {"operation_id": operation_id, "decision_id": decision_id, "records": [expense_view(r) for r in rows], "executed_at": now.isoformat()}
        decision.executed_at = now
        session.add(Execution(operation_id=operation_id, decision_id=decision_id, request_id=decision.record_key or "registry",
                              action=decision.action, initiator=account.id, result=result, created_at=now))
        session.add(Outbox(payload={"application_id": "demo", "event_id": operation_id + ":result", "event_at": now.isoformat(),
                                   "action": decision.action, "actor": account.id, "status": "SUCCESS", "fields": typed_fields(fields(row, account.id), catalog[decision.action]["fields"]) if row else actual,
                                   "operation_id": operation_id, "decision_id": decision_id}))
        return result


async def deliver_outbox():
    delivered = 0
    async with demo_sessions().begin() as session:
        rows = (await session.scalars(select(Outbox).where(Outbox.delivered_at.is_(None)).limit(100).with_for_update(skip_locked=True))).all()
        for row in rows:
            await antifraud_call("/api/events", row.payload)
            row.delivered_at = await db_time(session)
            delivered += 1
    return {"delivered": delivered}
