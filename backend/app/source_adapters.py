"""Read-only adapter contract: metadata and one record, never arbitrary queries."""
import re
import ssl
from contextlib import asynccontextmanager
from decimal import Decimal
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from app.rules import RuleError


def scalar_type(column):
    try:
        return {str: "string", int: "integer", Decimal: "number", float: "number", bool: "boolean"}.get(column.type.python_type, "unsupported")
    except NotImplementedError:
        return "unsupported"


def typed_key(value, kind):
    if value is None or isinstance(value, (dict, list, bool)):
        raise RuleError("Ключ записи имеет неверный тип")
    if kind == "string":
        if not isinstance(value, str):
            raise RuleError("Строковому ключу нужна строка")
        return value
    if kind == "integer" and re.fullmatch(r"-?\d+", str(value)):
        return int(value)
    if kind == "number":
        try:
            result = Decimal(str(value))
            if result.is_finite():
                return result
        except Exception:
            pass
    if kind == "objectid":
        from bson import ObjectId
        if isinstance(value, str) and ObjectId.is_valid(value):
            return ObjectId(value)
    raise RuleError("Ключ записи имеет неверный или неподдерживаемый тип")


def normalize(value, kind):
    from bson import ObjectId, Decimal128
    if value is None:
        return None
    if isinstance(value, Decimal128):
        value = value.to_decimal()
    valid = ((kind == "string" and isinstance(value, str)) or
             (kind == "boolean" and isinstance(value, bool)) or
             (kind == "integer" and isinstance(value, int) and not isinstance(value, bool)) or
             (kind == "number" and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)) or
             (kind == "objectid" and isinstance(value, ObjectId)))
    if not valid:
        raise RuleError("Тип значения источника не соответствует разрешённым метаданным")
    if kind in {"number", "integer"}:
        result = Decimal(str(value))
        if not result.is_finite():
            raise RuleError("Число источника должно быть конечным")
        return format(result, "f")
    return str(value) if kind == "objectid" else value


class SQLAdapter:
    def __init__(self, connection, kind, resources):
        self.connection, self.kind, self.resources = connection, kind, resources
        self.tables = {}

    async def metadata(self):
        result = []
        if self.kind == "postgresql":
            await self.connection.execute(text("SET TRANSACTION READ ONLY"))
            await self.connection.execute(text("SET LOCAL statement_timeout = '3000ms'"))
            if await self.connection.scalar(text("SELECT rolsuper OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname = current_user")):
                raise RuleError("Источник должен использовать отдельную роль только чтения")
        else:
            await self.connection.execute(text("SET SESSION MAX_EXECUTION_TIME=3000"))
            grants = (await self.connection.execute(text("SHOW GRANTS FOR CURRENT_USER"))).scalars().all()
            for grant in grants:
                match = re.fullmatch(r"GRANT (.+) ON .+ TO .+", grant)
                if not match or "WITH GRANT OPTION" in grant or any(p.strip() not in {"SELECT", "USAGE", "SHOW VIEW"} for p in match[1].split(",")):
                    raise RuleError("Для MySQL нужен пользователь с прямыми правами SELECT без ролей и прав записи")
            if await self.connection.scalar(text("SELECT CURRENT_ROLE()")) != "NONE":
                raise RuleError("Для MySQL используйте пользователя без активных ролей")
            await self.connection.rollback()
            await self.connection.execute(text("START TRANSACTION READ ONLY"))
        for resource, spec in self.resources.items():
            schema, name = resource.split(".", 1)
            if self.kind == "postgresql":
                for permission in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "REFERENCES"):
                    if await self.connection.scalar(text("SELECT has_table_privilege(current_user, :table_name, :permission)"), {"table_name": resource, "permission": permission}):
                        raise RuleError("Роль источника имеет права записи; используйте роль только чтения")
                for permission in ("INSERT", "UPDATE"):
                    if await self.connection.scalar(text("SELECT has_any_column_privilege(current_user, :table_name, :permission)"), {"table_name": resource, "permission": permission}):
                        raise RuleError("Роль источника имеет права записи в столбцы")
                if not await self.connection.scalar(text("SELECT has_table_privilege(current_user, :table_name, 'SELECT')"), {"table_name": resource}):
                    raise RuleError("Нет права SELECT на разрешённую таблицу")
            table = await self.connection.run_sync(lambda sync: Table(name, MetaData(), schema=schema, autoload_with=sync))
            self.tables[resource] = table
            fields = {c.name: {"type": scalar_type(c), "nullable": c.nullable} for c in table.c
                      if not spec.get("fields") or c.name in spec["fields"]}
            if self.kind == "mysql":
                for name, declared in spec.get("fields", {}).items():
                    if declared == "boolean" and name in fields and str(table.c[name].type).upper() == "TINYINT" and getattr(table.c[name].type, "display_width", None) == 1:
                        fields[name]["type"] = "boolean"
            await self.connection.execute(select(*[table.c[n] for n in fields]).limit(0))
            result.append({"name": resource, "fields": fields})
        return result

    async def read_one(self, resource, key_field, key, fields, metadata):
        table = self.tables[resource]
        rows = (await self.connection.execute(select(*[table.c[n] for n in fields]).where(table.c[key_field] == typed_key(key, metadata[key_field]["type"])).limit(2))).mappings().all()
        if len(rows) != 1:
            raise RuleError("По ключу нужна ровно одна запись")
        record = dict(rows[0])
        if self.kind == "mysql":
            for name in fields:
                if metadata[name]["type"] == "boolean" and type(record[name]) is int and record[name] in (0, 1):
                    record[name] = bool(record[name])
        return record


class MongoAdapter:
    def __init__(self, client, database, resources):
        self.client, self.database, self.resources = client, client[database], resources

    async def metadata(self):
        info = (await self.database.command({"connectionStatus": 1, "showPrivileges": True}))["authInfo"]
        permissions = info.get("authenticatedUserPrivileges", [])
        safe = {"find", "listCollections", "listIndexes", "listSearchIndexes", "planCacheRead", "collStats", "dbStats", "dbHash", "killCursors", "changeStream"}
        if not info.get("authenticatedUsers") or not permissions or any(set(p["actions"]) - safe for p in permissions):
            raise RuleError("Для MongoDB нужна отдельная роль только чтения; права записи или неизвестные права недопустимы")
        names = await self.database.list_collection_names(authorizedCollections=True, nameOnly=True)
        result = []
        for resource, spec in self.resources.items():
            if resource not in names:
                raise RuleError("Разрешённая коллекция отсутствует или недоступна пользователю")
            can_read = any("find" in p["actions"] and p["resource"].get("db") in ("", self.database.name) and
                           p["resource"].get("collection") in ("", resource) for p in permissions)
            if not can_read:
                raise RuleError("Нет права find на коллекцию")
            result.append({"name": resource, "fields": {n: {"type": t, "nullable": True} for n, t in spec["fields"].items()},
                           "note": "Поля объявлены оператором. Документы могут отличаться; типы проверяются при чтении. Коллекция не сканируется."})
        return result

    async def read_one(self, resource, key_field, key, fields, metadata):
        projection = {n: 1 for n in fields}
        if "_id" not in fields:
            projection["_id"] = 0
        rows = await self.database[resource].find({key_field: typed_key(key, metadata[key_field]["type"])}, projection).limit(2).max_time_ms(3000).to_list(length=2)
        if len(rows) != 1:
            raise RuleError("По ключу нужна ровно одна запись")
        return rows[0]


@asynccontextmanager
async def adapter(url, kind, endpoint, resources):
    if kind == "mongodb":
        from pymongo import AsyncMongoClient
        client = AsyncMongoClient(url.render_as_string(hide_password=False), directConnection=True,
                                  serverSelectionTimeoutMS=3000, connectTimeoutMS=3000, socketTimeoutMS=3000,
                                  timeoutMS=5000, tls=endpoint.get("tls", False))
        try:
            yield MongoAdapter(client, url.database, resources)
        finally:
            await client.close()
    else:
        options = {"timeout": 3, "command_timeout": 3} if kind == "postgresql" else {"connect_timeout": 3}
        if endpoint.get("tls"):
            options["ssl"] = ssl.create_default_context()
        engine = create_async_engine(url, hide_parameters=True, connect_args=options)
        try:
            async with engine.connect() as connection:
                yield SQLAdapter(connection, kind, resources)
        finally:
            await engine.dispose()
