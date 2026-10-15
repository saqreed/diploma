"""Explicit, idempotent administrative migration and educational seed (no data reset)."""
import asyncio
import os
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Account, Application, Base, Expense, Migration, Rule
from app.security import digest, hash_password
from app.demo_seed import DEMO_CATALOG, DEMO_FIELDS, seed_data


async def bootstrap():
    engine = create_async_engine(os.environ["DIPLOMA_ADMIN_DATABASE_URL"], hide_parameters=True)
    try:
        async with engine.begin() as connection:
            for name, env in (("diploma_antifraud", "DIPLOMA_AF_PASSWORD"), ("diploma_demo", "DIPLOMA_DEMO_PASSWORD"), ("diploma_reader", "DIPLOMA_READER_PASSWORD")):
                exists = await connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:name"), {"name": name})
                quoted_password = await connection.scalar(text("SELECT quote_literal(:password)"), {"password": os.environ[env]})
                await connection.execute(text(f"{'ALTER' if exists else 'CREATE'} ROLE {name} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {quoted_password}"))
            for schema in ("antifraud", "demo"):
                await connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            await connection.execute(text("ALTER TABLE IF EXISTS antifraud.applications ADD COLUMN IF NOT EXISTS history_from timestamptz NOT NULL DEFAULT '1970-01-01T00:00:00Z'"))
            await connection.run_sync(Base.metadata.create_all)
            for statement in (
                "ALTER TABLE demo.requests ADD COLUMN IF NOT EXISTS category varchar NOT NULL DEFAULT 'other'",
                "ALTER TABLE demo.requests ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT clock_timestamp()",
                "CREATE INDEX IF NOT EXISTS ix_expense_page ON demo.requests (created_at DESC, id)",
                "CREATE INDEX IF NOT EXISTS ix_expense_owner_status ON demo.requests (author, status)",
            ):
                await connection.execute(text(statement))
            statements = [
                "GRANT USAGE ON SCHEMA antifraud TO diploma_antifraud, diploma_demo",
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA antifraud TO diploma_antifraud",
                "GRANT USAGE ON SCHEMA demo TO diploma_demo, diploma_reader",
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA demo TO diploma_demo",
                "GRANT SELECT ON antifraud.decisions TO diploma_demo",
                "GRANT UPDATE (executed_at) ON antifraud.decisions TO diploma_demo",
                "GRANT SELECT ON demo.requests TO diploma_reader",
                "REVOKE ALL ON SCHEMA demo FROM diploma_antifraud",
                "REVOKE ALL ON ALL TABLES IN SCHEMA demo FROM diploma_antifraud",
            ]
            for statement in statements:
                await connection.execute(text(statement))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            if await session.get(Migration, 1) is None:
                session.add(Migration(version=1))
            for username, role, name in (("admin", "admin", "Администратор"), ("specialist", "specialist", "Специалист по проверке"),
                                          ("employee", "employee", "Сотрудник"), ("employee2", "employee", "Второй сотрудник"),
                                          ("manager", "manager", "Руководитель"), ("accountant", "accountant", "Бухгалтер")):
                if await session.get(Account, username) is None:
                    session.add(Account(id=username, username=username, role=role, name=name, password_hash=hash_password(os.environ["DIPLOMA_SEED_PASSWORD"])))
            if await session.get(Application, "demo") is None:
                session.add(Application(id="demo", name="Возмещение расходов", api_key_hash=digest(os.environ["DIPLOMA_DEMO_API_KEY"]), catalog=DEMO_CATALOG, ttl_seconds=600))
            elif await session.get(Migration, 2) is None:
                application = await session.get(Application, "demo")
                catalog = dict(application.catalog)
                export = dict(catalog["export"])
                export["fields"] = {**export["fields"], "registry_snapshot": DEMO_CATALOG["export"]["fields"]["registry_snapshot"]}
                catalog["export"] = export
                application.catalog = catalog
            if await session.get(Migration, 2) is None:
                session.add(Migration(version=2))
            if await session.get(Migration, 3) is None:
                session.add(Migration(version=3))
            if await session.get(Migration, 5) is None:
                session.add(Migration(version=5))
            if await session.get(Rule, "demo-amount-review") is None:
                session.add(Rule(id="demo-amount-review", application_id="demo", name="Большая сумма: ручная проверка", action="pay",
                                 expression={"kind": "field", "field": "amount", "op": "gt", "value": 10000}, reaction="REVIEW", enabled=True))
            if await session.get(Migration, 4) is None:
                for name, data in zip(("seed-normal", "seed-large", "seed-duplicate"), seed_data()):
                    if await session.get(Expense, name) is None:
                        session.add(Expense(id=name, **data))
                session.add(Migration(version=4))
            if await session.get(Migration, 6) is None:
                for name, data in zip(("seed-split-1", "seed-split-2"), seed_data()[3:]):
                    if await session.get(Expense, name) is None:
                        session.add(Expense(id=name, **data))
                session.add(Migration(version=6))
            if await session.get(Migration, 7) is None:
                application = await session.get(Application, "demo")
                catalog = dict(application.catalog)
                for action in ("submit", "approve", "reject", "pay"):
                    catalog[action] = {**catalog[action], "fields": {**catalog[action]["fields"], "category": DEMO_FIELDS["category"]}}
                application.catalog = catalog
                session.add(Migration(version=7))
        print("Migrations and missing educational seed applied. Existing records and credentials preserved; no secrets displayed.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(bootstrap())
    except Exception as error:
        message = str(error)
        for key, value in os.environ.items():
            if value and any(word in key for word in ("PASSWORD", "KEY", "DATABASE_URL")):
                message = message.replace(value, "[secret]")
        print(f"Migration failed: {type(error).__name__}: {message}", file=sys.stderr)
        sys.exit(1)
