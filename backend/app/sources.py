"""Allowlisted read-only field sources. Existing encrypted PostgreSQL URLs remain valid."""
import asyncio
import os
import re
from cryptography.fernet import Fernet
from sqlalchemy.engine import URL
from app.rules import RuleError
from app.source_policy import DRIVERS, connection_policy, public_connection
from app.source_adapters import adapter, normalize


def cipher():
    return Fernet(os.environ["DIPLOMA_SOURCE_ENCRYPTION_KEY"].encode())


def resolve_connection(payload, saved=None):
    old = cipher().decrypt(saved.encrypted_url.encode()).decode() if saved else None
    if "connection" not in payload:
        value = payload.get("url")
        if value == "" and old:
            return old
        if not isinstance(value, str):
            raise RuleError("Укажите параметры подключения")
        return value
    config = payload["connection"]
    if not isinstance(config, dict) or set(config) != {"kind", "host", "port", "database", "user", "password"}:
        raise RuleError("Неверный формат подключения")
    try:
        kind = config["kind"]
        port = int(config["port"])
        if kind not in DRIVERS or not 1 <= port <= 65535 or any(not isinstance(config[k], str) for k in ("host", "database", "user", "password")):
            raise ValueError()
        password = config["password"]
        identity = {k: config[k] for k in ("kind", "host", "database", "user")}
        identity["port"] = str(port)
        if not password and old and identity == public_connection(old):
            return old
        if not password:
            raise RuleError("Для нового адреса, типа, базы или пользователя введите пароль заново")
        return URL.create(DRIVERS[kind], username=config["user"], password=password,
                          host=config["host"], port=port, database=config["database"]).render_as_string(hide_password=False)
    except (ValueError, TypeError, KeyError):
        raise RuleError("Проверьте параметры подключения. Для нового адреса, типа, базы или пользователя нужен пароль") from None


def validate_source(settings):
    if not isinstance(settings.get("url"), str) or not isinstance(settings.get("table_name"), str) or not isinstance(settings.get("allowed_fields"), list) or not isinstance(settings.get("mapping"), dict):
        raise RuleError("Неверный формат подключения или сопоставления")
    _, _, _, resources = connection_policy(settings["url"])
    if settings["table_name"] not in resources:
        raise RuleError("Таблица или коллекция отсутствует в серверном списке разрешённых ресурсов")
    names = [settings.get("key_field"), *settings["allowed_fields"], *settings["mapping"].values()]
    if any(not isinstance(n, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}", n) for n in names):
        raise RuleError("Неверное имя поля источника")
    if not settings["mapping"] or not set(settings["mapping"].values()).issubset(settings["allowed_fields"]) or len(settings["allowed_fields"]) > 100:
        raise RuleError("Сопоставление использует неразрешённое поле")
    allowed = resources[settings["table_name"]].get("fields")
    if allowed and not set(names).issubset(allowed):
        raise RuleError("Поле отсутствует в серверном списке разрешённых полей")


async def inspect_source(value):
    url, kind, endpoint, resources = connection_policy(value)
    try:
        async with asyncio.timeout(8):
            async with adapter(url, kind, endpoint, resources) as current:
                metadata = await current.metadata()
        return {"connection": public_connection(value), "resources": metadata,
                "databases": [d for d in endpoint["databases"] if d != "*"],
                "message": "Доступ и права чтения проверены. Выберите ресурс и сопоставление. Настройки не изменены."}
    except RuleError:
        raise
    except Exception:
        raise RuleError("Не удалось проверить доступ. Проверьте адрес, базу, пароль, права чтения и доступность сервиса") from None


def validate_mapping(settings, metadata, catalog):
    resource = next((r for r in metadata if r["name"] == settings["table_name"]), None)
    if resource is None:
        raise RuleError("Выбранный ресурс недоступен")
    fields = resource["fields"]
    if any(n not in fields or fields[n]["type"] == "unsupported" for n in [settings["key_field"], *settings["allowed_fields"]]):
        raise RuleError("Поле отсутствует или имеет неподдерживаемый тип")
    for target, column in settings["mapping"].items():
        specs = [c["fields"][target] for c in catalog.values() if target in c["fields"]]
        if not specs:
            raise RuleError("Сопоставление использует незарегистрированное поле приложения")
        actual = fields[column]["type"]
        compatible = "number" if actual == "integer" else "string" if actual == "objectid" else actual
        if any(s["type"] != compatible for s in specs):
            raise RuleError(f"Тип поля {target} несовместим с полем источника {column}")


async def read_source(source, record_key):
    if record_key is None:
        raise RuleError("Для полей БД нужен ключ записи")
    value = cipher().decrypt(source.encrypted_url.encode()).decode()
    settings = {k: getattr(source, k) for k in ("table_name", "key_field", "allowed_fields", "mapping")}
    validate_source({**settings, "url": value})
    url, kind, endpoint, resources = connection_policy(value)
    try:
        async with asyncio.timeout(8):
            async with adapter(url, kind, endpoint, {source.table_name: resources[source.table_name]}) as current:
                metadata = (await current.metadata())[0]["fields"]
                if any(n not in metadata or metadata[n]["type"] == "unsupported" for n in [source.key_field, *source.allowed_fields]):
                    raise RuleError("Поле отсутствует или имеет неподдерживаемый тип")
                record = await current.read_one(source.table_name, source.key_field, record_key, source.allowed_fields, metadata)
                return {target: normalize(record[column], metadata[column]["type"]) for target, column in source.mapping.items() if column in record}
    except RuleError:
        raise
    except Exception:
        raise RuleError("Источник недоступен. Проверьте подключение, пароль и права чтения. Действие не разрешено") from None
