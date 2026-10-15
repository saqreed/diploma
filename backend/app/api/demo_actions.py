"""Explicit demo actions and bounded role-specific queues. No business auto-approval."""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.orm import defer

from app.access import require, user
from app.contracts import DemoCheck, ExecuteInput, OperationInput
from app.decisions import DomainError, TERMINAL, db_time, view
from app.demo import expense_view
from app.models import Decision, Execution, Expense
from app.runtime import demo_sessions

router = APIRouter(prefix="/api/demo")


def effective_state():
    return case((Decision.executed_at.is_(None) & Decision.state.not_in(TERMINAL)
                 & (Decision.expires_at <= func.clock_timestamp()), "EXPIRED"), else_=Decision.state)


def decision_summary(row, now):
    state = "EXPIRED" if not row.executed_at and row.state not in TERMINAL and now >= row.expires_at else row.state
    return {"id": row.id, "action": row.action, "state": state, "executed_at": row.executed_at.isoformat() if row.executed_at else None,
            "reasons": [reason.get("message") or reason.get("name") for reason in row.reasons if reason.get("matched") or reason.get("message")]}


@router.get("/requests/page")
async def page(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), search: str = Query("", max_length=200),
               status: Literal["", "DRAFT", "SUBMITTED", "APPROVED", "PAID", "REJECTED"] = "",
               queue: Literal["all", "business", "payment", "confirmation", "review"] = "all", account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    conditions = []
    if account.role == "employee":
        conditions.append(Expense.author == account.id)
    if status:
        conditions.append(Expense.status == status)
    if search:
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(*(column.ilike(pattern, escape="\\") for column in (Expense.id, Expense.title, Expense.recipient, Expense.author, Expense.receipt))))
    if queue == "business":
        require(account, "manager")
        conditions.extend((Expense.status == "SUBMITTED", Expense.author != account.id))
    elif queue == "payment":
        require(account, "accountant")
        conditions.extend((Expense.status == "APPROVED", Expense.approved_version == Expense.version))
    elif queue in {"confirmation", "review"}:
        # EXISTS over ALL decisions, rather than the last 50 attempts of this user.
        conditions.append(select(Decision.id).where(Decision.application_id == "demo", Decision.record_key == Expense.id,
                          Decision.initiator == account.id, Decision.checked_values["version"].as_string() == cast(Expense.version, String),
                          effective_state() == ("PENDING_CONFIRMATION" if queue == "confirmation" else "PENDING_REVIEW")).exists())
    async with demo_sessions()() as session:
        total = await session.scalar(select(func.count()).select_from(Expense).where(*conditions))
        rows = (await session.scalars(select(Expense).where(*conditions).options(defer(Expense.history))
                                     .order_by(Expense.created_at.desc(), Expense.id).limit(limit).offset(offset))).all()
        ids = [row.id for row in rows]
        # Bounded to the visible page; no history or condition traces in the list response.
        latest = {}
        if ids:
            decisions = (await session.scalars(select(Decision).where(Decision.application_id == "demo", Decision.initiator == account.id,
                         Decision.record_key.in_(ids)).distinct(Decision.record_key).order_by(Decision.record_key, Decision.created_at.desc(), Decision.id.desc()))).all()
            latest = {d.record_key: d for d in decisions}
        now = await db_time(session)
        return {"items": [{**expense_view(row, False), "decision": decision_summary(latest[row.id], now) if row.id in latest else None} for row in rows],
                "total": total, "limit": limit, "offset": offset}


@router.get("/requests/{expense_id}")
async def detail(expense_id: str, account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    async with demo_sessions()() as session:
        row = await session.get(Expense, expense_id)
        if not row or account.role == "employee" and row.author != account.id:
            raise DomainError("request_missing", "Заявка не найдена", 404)
        decision = await session.scalar(select(Decision).where(Decision.application_id == "demo", Decision.initiator == account.id,
                         Decision.record_key == row.id).order_by(Decision.created_at.desc(), Decision.id.desc()).limit(1))
        return {**expense_view(row), "decision": decision_summary(decision, await db_time(session)) if decision else None}


@router.post("/requests/{expense_id}/action")
async def action(expense_id: str, payload: DemoCheck, account=Depends(user)):
    require(account, "employee", "manager", "accountant")
    # A lost HTTP response must replay the stored action, including approval which changes approver.
    async with demo_sessions()() as session:
        existing = await session.get(Execution, payload.operation_id)
        if existing:
            if (existing.request_id, existing.action, existing.initiator) != (expense_id, payload.action, account.id):
                raise DomainError("execution_conflict", "Попытка связана с другой заявкой, действием или инициатором", 403)
            if payload.version is not None and existing.result["request"]["version"] != payload.version:
                raise DomainError("execution_conflict", "Попытка связана с другой версией заявки")
            decision_id = existing.decision_id
        else:
            decision_id = None
    from app.api.antifraud import demo_check, demo_execute, decision_detail
    if not decision_id:
        decision = await demo_check(expense_id, payload, account)
        decision_id = decision["id"]
        if decision["state"] != "APPROVED":
            return {"decision": decision, "execution": None}
    execution = await demo_execute(ExecuteInput(operation_id=payload.operation_id, decision_id=decision_id), account)
    return {"decision": await decision_detail(decision_id, account), "execution": execution}


@router.post("/export/action")
async def export_action(payload: OperationInput, account=Depends(user)):
    require(account, "accountant")
    from app.api.antifraud import demo_execute, export_check, decision_detail
    async with demo_sessions()() as session:
        existing = await session.get(Execution, payload.operation_id)
        if existing and (existing.action != "export" or existing.initiator != account.id):
            raise DomainError("execution_conflict", "Попытка связана с другим действием", 403)
        decision_id = existing.decision_id if existing else None
    if not decision_id:
        decision = await export_check(payload, account)
        if decision["state"] != "APPROVED":
            return {"decision": decision, "execution": None}
        decision_id = decision["id"]
    execution = await demo_execute(ExecuteInput(operation_id=payload.operation_id, decision_id=decision_id), account)
    return {"decision": await decision_detail(decision_id, account), "execution": execution}
