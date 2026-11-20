"""Operator-owned endpoint/resource policy; never supplied by API clients."""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.engine import make_url
from app.rules import RuleError

DRIVERS = {"postgresql": "postgresql+asyncpg", "mysql": "mysql+asyncmy", "mongodb": "mongodb"}
PORTS = {"postgresql": 5432, "mysql": 3306, "mongodb": 27017}


def read_policy(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        endpoints = data["endpoints"]
        if not isinstance(endpoints, list) or len(endpoints) > 64:
            raise ValueError()
        for endpoint in endpoints:
            if (
                endpoint["kind"] not in DRIVERS
                or not isinstance(endpoint["id"], str)
                or not isinstance(endpoint["host"], str)
                or not endpoint["host"]
                or type(endpoint["port"]) is not int
                or not 1 <= endpoint["port"] <= 65535
                or not isinstance(endpoint["databases"], dict)
                or not all(isinstance(resources, dict) for resources in endpoint["databases"].values())
                or type(endpoint.get("tls", False)) is not bool
                or ("auth_database" in endpoint and (
                    endpoint["kind"] != "mongodb"
                    or not isinstance(endpoint["auth_database"], str)
                    or not endpoint["auth_database"]
                ))
            ):
                raise ValueError()
        return data
    except (OSError, ValueError, TypeError, KeyError):
        raise RuleError("Не удалось прочитать серверную политику источников") from None


def endpoint_key(endpoint):
    return endpoint.get("kind"), endpoint.get("host"), endpoint.get("port")


def policy():
    path = os.getenv("DIPLOMA_SOURCE_POLICY")
    if path:
        config = read_policy(path)
    else:
        config = {"name": "Серверный список PostgreSQL", "endpoints": [
            {"id": host, "kind": "postgresql", "host": host, "port": 5432,
             "databases": {"*": {name: {} for name in os.getenv("DIPLOMA_SOURCE_TABLES", "demo.requests").split(",")}}}
            for host in os.getenv("DIPLOMA_SOURCE_HOSTS", "postgres,127.0.0.1").split(",")
        ]}
    extra_path = os.getenv("DIPLOMA_SOURCE_EXTRA_POLICY")
    if extra_path and Path(extra_path).exists():
        extra = read_policy(extra_path)["endpoints"]
        endpoints = config["endpoints"] + [{"tls": True, **entry, "external": True} for entry in extra]
        if len(endpoints) > 64 or len({endpoint_key(e) for e in endpoints}) != len(endpoints):
            raise RuleError("В политике источников повторяется адрес БД или превышен лимит в 64 подключения")
        config["endpoints"] = endpoints
        config["name"] = f'{config.get("name", "Серверная политика")} · хост и внешние адреса'
    return config


def connection_policy(value):
    try:
        url = make_url(value)
        kind = next(k for k, driver in DRIVERS.items() if driver == url.drivername)
        if url.query or not url.host or not url.database or not url.username or not url.password:
            raise ValueError()
        port = url.port or PORTS[kind]
    except Exception:
        raise RuleError("Укажите тип БД, сервер, базу, пользователя и пароль. Параметры URL не поддерживаются") from None
    endpoint = next((e for e in policy()["endpoints"] if endpoint_key(e) == (kind, url.host, port)), None)
    if endpoint is None:
        raise RuleError("Адрес, порт или тип БД отсутствуют в серверном списке разрешённых источников")
    databases = endpoint["databases"]
    resources = databases.get(url.database, databases.get("*"))
    if resources is None:
        raise RuleError("База данных не разрешена серверной политикой")
    return url, kind, endpoint, resources


def public_connection(value):
    url = make_url(value)
    kind = next(k for k, driver in DRIVERS.items() if driver == url.drivername)
    return {"kind": kind, "host": url.host, "port": str(url.port or PORTS[kind]),
            "database": url.database, "user": url.username}


async def discover():
    config = policy()
    now = datetime.now(timezone.utc)
    warnings = []
    inventory_path = os.getenv("DIPLOMA_SOURCE_INVENTORY")
    inventory_at = None
    scope = config.get("name", "Серверная политика")
    permitted = {endpoint_key(e): e for e in config["endpoints"]}
    if inventory_path:
        try:
            inventory = json.loads(Path(inventory_path).read_text(encoding="utf-8-sig"))
            inventory_at = inventory["updated_at"]
            age = (now - datetime.fromisoformat(inventory_at.replace("Z", "+00:00"))).total_seconds()
            if age > 60:
                warnings.append("Инвентарь старше минуты. Запустите помощник обновления")
            rows = inventory["sources"][:64]
            if isinstance(inventory.get("scope"), str):
                scope = f'{inventory["scope"]} · {scope}'
            warnings.extend(inventory.get("warnings", []))
        except (OSError, ValueError, KeyError, TypeError):
            rows = []
            warnings.append("Инвентарь недоступен. Доступна ручная настройка по серверной политике")
    else:
        rows = []
    seen = {endpoint_key(row) for row in rows}
    for key, endpoint in permitted.items():
        if key not in seen and (not inventory_path or endpoint.get("external")):
            rows.append({**dict(zip(("kind", "host", "port"), key)), "id": endpoint["id"],
                         "origin": "Объявлен в серверной политике"})
    semaphore = asyncio.Semaphore(4)

    async def probe(row):
        endpoint = permitted.get(endpoint_key(row))
        result = {k: row.get(k) for k in ("id", "kind", "host", "port", "origin")}
        result.update(state="configured" if endpoint and endpoint.get("external") else "detected",
                      databases=[], selectable=endpoint is not None)
        if endpoint:
            result["databases"] = [d for d in endpoint["databases"] if d != "*"]
        # Remote profiles are checked explicitly with the existing authenticated
        # connection form, not by every visit to Settings.
        if endpoint and not endpoint.get("external"):
            async with semaphore:
                try:
                    _, writer = await asyncio.wait_for(asyncio.open_connection(endpoint["host"], endpoint["port"]), 1.5)
                    writer.close()
                    await writer.wait_closed()
                    result["state"] = "available"
                except (OSError, TimeoutError):
                    result["state"] = "unavailable"
        return result
    sources = await asyncio.gather(*(probe(row) for row in rows))
    if any(row["state"] == "unavailable" for row in sources):
        warnings.append("Часть объявленных сервисов недоступна. Проверки остальных завершены")
    return {"sources": sources, "scope": scope,
            "updated_at": now.isoformat(), "inventory_at": inventory_at, "warnings": warnings}
