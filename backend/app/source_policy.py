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


def policy():
    path = os.getenv("DIPLOMA_SOURCE_POLICY")
    if path:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if not isinstance(data.get("endpoints"), list) or len(data["endpoints"]) > 64:
                raise ValueError()
            return data
        except (OSError, ValueError, TypeError):
            raise RuleError("Не удалось прочитать серверную политику источников") from None
    return {"name": "Серверный список PostgreSQL", "endpoints": [
        {"id": host, "kind": "postgresql", "host": host, "port": 5432,
         "databases": {"*": {name: {} for name in os.getenv("DIPLOMA_SOURCE_TABLES", "demo.requests").split(",")}}}
        for host in os.getenv("DIPLOMA_SOURCE_HOSTS", "postgres,127.0.0.1").split(",")
    ]}


def connection_policy(value):
    try:
        url = make_url(value)
        kind = next(k for k, driver in DRIVERS.items() if driver == url.drivername)
        if url.query or not url.host or not url.database or not url.username or not url.password:
            raise ValueError()
        port = url.port or PORTS[kind]
    except Exception:
        raise RuleError("Укажите тип БД, сервер, базу, пользователя и пароль. Параметры URL не поддерживаются") from None
    endpoint = next((e for e in policy()["endpoints"] if
                     (e["kind"], e["host"], e["port"]) == (kind, url.host, port)), None)
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
    if inventory_path:
        try:
            inventory = json.loads(Path(inventory_path).read_text(encoding="utf-8-sig"))
            inventory_at = inventory["updated_at"]
            age = (now - datetime.fromisoformat(inventory_at.replace("Z", "+00:00"))).total_seconds()
            if age > 60:
                warnings.append("Инвентарь старше минуты. Запустите помощник обновления Compose")
            rows = inventory["sources"][:64]
            warnings.extend(inventory.get("warnings", []))
        except (OSError, ValueError, KeyError, TypeError):
            rows = []
            warnings.append("Инвентарь недоступен. Доступна ручная настройка по серверной политике")
    else:
        rows = [{"id": e["id"], "kind": e["kind"], "host": e["host"], "port": e["port"],
                 "origin": "Объявлен в серверной политике"} for e in config["endpoints"]]
    semaphore = asyncio.Semaphore(4)

    async def probe(row):
        endpoint = next((e for e in config["endpoints"] if
                         (e["kind"], e["host"], e["port"]) == (row.get("kind"), row.get("host"), row.get("port"))), None)
        result = {k: row.get(k) for k in ("id", "kind", "host", "port", "origin")}
        result.update(state="detected", databases=[], selectable=endpoint is not None)
        if endpoint:
            result["databases"] = [d for d in endpoint["databases"] if d != "*"]
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
    return {"sources": sources, "scope": config.get("name", "Серверная политика"),
            "updated_at": now.isoformat(), "inventory_at": inventory_at, "warnings": warnings}
