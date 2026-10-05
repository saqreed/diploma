"""Persistent antifraud and demo records. The schemas have separate runtime owners."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid4())


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = {"schema": "antifraud"}
    id = Column(String, primary_key=True, default=new_id)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String, nullable=False)
    name = Column(String, nullable=False)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    __table_args__ = {"schema": "antifraud"}
    token_hash = Column(String, primary_key=True)
    account_id = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = {"schema": "antifraud"}
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    api_key_hash = Column(String, nullable=False)
    catalog = Column(JSON, nullable=False)
    ttl_seconds = Column(Integer, nullable=False, default=600)
    history_from = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = {"schema": "antifraud"}
    id = Column(String, primary_key=True, default=new_id)
    application_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    action = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    expression = Column(JSON, nullable=False)
    reaction = Column(String, nullable=False)
    exception = Column(JSON)
    version = Column(Integer, nullable=False, default=1)


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = {"schema": "antifraud"}
    id = Column(String, primary_key=True, default=new_id)
    application_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    values = Column(JSON, nullable=False)


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = {"schema": "antifraud"}
    id = Column(String, primary_key=True, default=new_id)
    application_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    action = Column(String, nullable=False)
    expression = Column(JSON, nullable=False)
    reaction = Column(String, nullable=False)
    exception = Column(JSON)
    version = Column(Integer, nullable=False, default=1)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = {"schema": "antifraud"}
    application_id = Column(String, primary_key=True)
    encrypted_url = Column(Text, nullable=False)
    table_name = Column(String, nullable=False)
    key_field = Column(String, nullable=False)
    allowed_fields = Column(JSON, nullable=False)
    mapping = Column(JSON, nullable=False)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("application_id", "operation_id"), {"schema": "antifraud"})
    id = Column(String, primary_key=True, default=new_id)
    application_id = Column(String, nullable=False, index=True)
    operation_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    initiator = Column(String, nullable=False, index=True)
    record_key = Column(String)
    request = Column(JSON, nullable=False)
    checked_values = Column(JSON, nullable=False)
    reasons = Column(JSON, nullable=False)
    state = Column(String, nullable=False)
    needs_review = Column(Boolean, nullable=False)
    needs_confirmation = Column(Boolean, nullable=False)
    review_done = Column(Boolean, nullable=False, default=False)
    confirmation_done = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    executed_at = Column(DateTime(timezone=True))


class Transition(Base):
    __tablename__ = "transitions"
    __table_args__ = {"schema": "antifraud"}
    id = Column(String, primary_key=True, default=new_id)
    decision_id = Column(String, nullable=False, index=True)
    before = Column(String)
    after = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    comment = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("application_id", "event_id"),
                      Index("ix_event_history", "application_id", "event_at", "action", "status"),
                      {"schema": "antifraud"})
    id = Column(String, primary_key=True, default=new_id)
    application_id = Column(String, nullable=False)
    event_id = Column(String, nullable=False)
    event_at = Column(DateTime(timezone=True), nullable=False)
    action = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    status = Column(String, nullable=False)
    fields = Column(JSON, nullable=False)
    operation_id = Column(String)
    decision_id = Column(String)
    payload = Column(JSON, nullable=False)


class Expense(Base):
    __tablename__ = "requests"
    __table_args__ = {"schema": "demo"}
    id = Column(String, primary_key=True, default=new_id)
    author = Column(String, nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    recipient = Column(String, nullable=False)
    receipt = Column(String, nullable=False)
    vendor = Column(String, nullable=False)
    purchase_date = Column(String, nullable=False)
    title = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="DRAFT")
    approver = Column(String)
    approved_version = Column(Integer)
    history = Column(JSON, nullable=False, default=list)


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (UniqueConstraint("decision_id"), {"schema": "demo"})
    operation_id = Column(String, primary_key=True)
    decision_id = Column(String, nullable=False)
    request_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    initiator = Column(String, nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = {"schema": "demo"}
    id = Column(String, primary_key=True, default=new_id)
    payload = Column(JSON, nullable=False)
    delivered_at = Column(DateTime(timezone=True))


class ResetArchive(Base):
    __tablename__ = "reset_archives"
    __table_args__ = {"schema": "demo"}
    id = Column(String, primary_key=True, default=new_id)
    actor = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    snapshot = Column(JSON, nullable=False)


class Migration(Base):
    __tablename__ = "schema_versions"
    __table_args__ = {"schema": "antifraud"}
    version = Column(Integer, primary_key=True)
    applied_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
