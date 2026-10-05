"""The single supported connector: allowlisted PostgreSQL, read-only transactions."""
import os
import re
from decimal import Decimal

from cryptography.fernet import Fernet
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.rules import RuleError


def cipher():
    return Fernet(os.environ["DIPLOMA_SOURCE_ENCRYPTION_KEY"].encode())


def validate_source(settings):
    if not isinstance(settings.get("url"), str) or not isinstance(settings.get("table_name"), str) or not isinstance(settings.get("allowed_fields"), list) or not isinstance(settings.get("mapping"), dict):
        raise RuleError("Неверный формат подключения или сопоставления")
    allowed_tables = os.environ.get("DIPLOMA_SOURCE_TABLES", "demo.requests").split(",")
    allowed_hosts = os.environ.get("DIPLOMA_SOURCE_HOSTS", "postgres,127.0.0.1").split(",")
    try:
        url = make_url(settings["url"])
    except Exception:
        raise RuleError("Неверный URL подключения") from None
    if url.query:
        raise RuleError("Дополнительные параметры URL источника не поддерживаются")
    if url.drivername != "postgresql+asyncpg" or url.host not in allowed_hosts:
        raise RuleError("Источник должен быть PostgreSQL на разрешённом сервере")
    if settings["table_name"] not in allowed_tables:
        raise RuleError("Таблица отсутствует в серверном списке разрешённых таблиц")
    names = [settings["key_field"], *settings["allowed_fields"], *settings["mapping"].values()]
    if any(not isinstance(n, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", n) for n in names):
        raise RuleError("Неверное имя столбца")
    if not settings["mapping"] or not set(settings["mapping"].values()).issubset(settings["allowed_fields"]):
        raise RuleError("Сопоставление использует неразрешённое поле")


async def read_source(source, record_key):
    if record_key is None:
        raise RuleError("Для полей БД нужен ключ записи")
    url = cipher().decrypt(source.encrypted_url.encode()).decode()
    engine = create_async_engine(url, hide_parameters=True, connect_args={"timeout": 3, "command_timeout": 3})
    schema, table_name = source.table_name.split(".", 1)
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                await connection.execute(text("SET LOCAL statement_timeout = '3000ms'"))
                unsafe = await connection.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
                if unsafe:
                    raise RuleError("Источник должен использовать отдельную роль только чтения")
                for permission in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER"):
                    if await connection.scalar(text("SELECT has_table_privilege(current_user, :table_name, :permission)"), {"table_name": source.table_name, "permission": permission}):
                        raise RuleError("Роль источника имеет права записи; используйте роль только чтения")
                for permission in ("INSERT", "UPDATE"):
                    if await connection.scalar(text("SELECT has_any_column_privilege(current_user, :table_name, :permission)"), {"table_name": source.table_name, "permission": permission}):
                        raise RuleError("Роль источника имеет права записи в столбцы")
                table = await connection.run_sync(lambda sync: Table(table_name, MetaData(), schema=schema, autoload_with=sync))
                columns = [table.c[name] for name in source.allowed_fields]
                key_column = table.c[source.key_field]
                try:
                    key = key_column.type.python_type(record_key)
                except (ValueError, TypeError):
                    raise RuleError("Ключ записи имеет неверный тип") from None
                records = (await connection.execute(select(*columns).where(key_column == key).limit(2))).mappings().all()
                if len(records) != 1:
                    raise RuleError("По ключу нужна ровно одна запись")
                record = records[0]
                return {target: str(record[column]) if isinstance(record[column], Decimal) else record[column] for target, column in source.mapping.items()}
    finally:
        await engine.dispose()
