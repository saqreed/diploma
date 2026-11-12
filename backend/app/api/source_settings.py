"""Administrative connection probes never mutate the saved profile."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from app.access import require, user
from app.models import Application, Source
from app.runtime import antifraud_sessions
from app.rules import RuleError
from app.sources import cipher, inspect_source, read_source, resolve_connection, validate_mapping, validate_source
from app.source_policy import discover, public_connection, policy

router = APIRouter(prefix="/api/admin")


@router.get("/source-options")
async def source_options(account=Depends(user)):
    require(account, "admin")
    return [{"kind": e["kind"], "host": e["host"], "port": str(e["port"]),
             "databases": [d for d in e["databases"] if d != "*"]} for e in policy()["endpoints"]]


def source_view(row):
    return {"application_id": row.application_id, "table_name": row.table_name, "key_field": row.key_field,
            "allowed_fields": row.allowed_fields, "mapping": row.mapping, "credentials_saved": True,
            "connection": public_connection(cipher().decrypt(row.encrypted_url.encode()).decode())}


@router.get("/source-discovery")
async def discovery(account=Depends(user)):
    require(account, "admin")
    return await discover()


@router.get("/sources")
async def all_sources(account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions()() as session:
        return [source_view(row) for row in (await session.scalars(select(Source))).all()]


@router.get("/sources/{application_id}")
async def get_source(application_id: str, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions()() as session:
        row = await session.get(Source, application_id)
        return source_view(row) if row else None


@router.post("/sources/{application_id}/inspect")
async def inspect(application_id: str, payload: dict, account=Depends(user)):
    require(account, "admin")
    if set(payload) not in ({"url"}, {"connection"}):
        raise RuleError("Передайте параметры подключения")
    async with antifraud_sessions()() as session:
        if not await session.get(Application, application_id):
            raise RuleError("Приложение не найдено")
        value = resolve_connection(payload, await session.get(Source, application_id))
    return await inspect_source(value)


async def candidate(session, application_id, payload):
    keys = set(payload) - {"record_key", "field_sources"}
    base = {"table_name", "key_field", "allowed_fields", "mapping"}
    if keys not in (base | {"url"}, base | {"connection"}):
        raise RuleError("Укажите подключение, ресурс, ключ, разрешённые поля и сопоставление")
    application = await session.get(Application, application_id)
    if not application:
        raise RuleError("Приложение не найдено")
    saved = await session.get(Source, application_id)
    config = {k: payload[k] for k in base}
    config["url"] = resolve_connection(payload, saved)
    validate_source(config)
    metadata = await inspect_source(config["url"])
    validate_mapping(config, metadata["resources"], application.catalog)
    row = Source(application_id=application_id, encrypted_url=cipher().encrypt(config["url"].encode()).decode(),
                 **{k: config[k] for k in base})
    return application, saved, row


@router.post("/sources/{application_id}/test")
async def test(application_id: str, payload: dict, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions()() as session:
        application, _, row = await candidate(session, application_id, payload)
        values = await read_source(row, payload.get("record_key"))
        from app.decisions import typed_fields
        for config in application.catalog.values():
            relevant = {k: v for k, v in config["fields"].items() if k in row.mapping}
            typed_fields(values, relevant)
    return {"message": "Подключение и права чтения проверены. Найдена одна запись; настройки не изменены.",
            "fields": list(values)}


@router.put("/sources/{application_id}")
async def save(application_id: str, payload: dict, account=Depends(user)):
    require(account, "admin")
    async with antifraud_sessions().begin() as session:
        application, saved, row = await candidate(session, application_id, payload)
        field_sources = payload.get("field_sources")
        if field_sources is not None:
            if not isinstance(field_sources, dict) or any(v not in {"API", "DB"} for v in field_sources.values()):
                raise RuleError("Полю нужен ровно один источник: API или БД")
            known = {name for config in application.catalog.values() for name in config["fields"]}
            if set(field_sources) != known or {k for k, v in field_sources.items() if v == "DB"} != set(row.mapping):
                raise RuleError("Сопоставьте все выбранные поля БД и укажите источник каждого поля")
            # Existing generic catalogue validation and demo invariants also apply here.
            catalog = {a: {**c, "fields": {n: {**f, "source": field_sources[n]} for n, f in c["fields"].items()}} for a, c in application.catalog.items()}
            from app.rules import validate_catalog
            validate_catalog(catalog)
            if application_id == "demo":
                from app.demo import validate_demo_catalog
                validate_demo_catalog(catalog)
            application.catalog = catalog
        if "record_key" in payload:
            values = await read_source(row, payload["record_key"])
            from app.decisions import typed_fields
            for config in application.catalog.values():
                typed_fields(values, {n: f for n, f in config["fields"].items() if n in row.mapping})
        if saved is None:
            session.add(row)
        else:
            for key in ("encrypted_url", "table_name", "key_field", "allowed_fields", "mapping"):
                setattr(saved, key, getattr(row, key))
    return {"message": "Источник сохранён. Пароль больше не отображается"}
