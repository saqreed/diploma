"""Source boundary regressions. Live database paths: scripts/test-source-integrations.mjs."""
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet
from app.rules import RuleError, validate_catalog
from app.sources import cipher, resolve_connection, validate_source
from app.source_adapters import typed_key, normalize
from app.source_policy import connection_policy, discover


@pytest.fixture
def source_env(monkeypatch):
    monkeypatch.delenv('DIPLOMA_SOURCE_POLICY', raising=False)
    monkeypatch.delenv('DIPLOMA_SOURCE_EXTRA_POLICY', raising=False)
    monkeypatch.delenv('DIPLOMA_SOURCE_INVENTORY', raising=False)
    monkeypatch.setenv('DIPLOMA_SOURCE_HOSTS', 'postgres')
    monkeypatch.setenv('DIPLOMA_SOURCE_TABLES', 'demo.requests')
    monkeypatch.setenv('DIPLOMA_SOURCE_ENCRYPTION_KEY', Fernet.generate_key().decode())


def test_legacy_encrypted_secret_and_same_identity_only(source_env):
    url='postgresql+asyncpg://reader:secret@postgres:5432/diploma'
    saved=SimpleNamespace(encrypted_url=cipher().encrypt(url.encode()).decode())
    config=dict(kind='postgresql',host='postgres',port='5432',database='diploma',user='reader',password='')
    assert resolve_connection({'url':''},saved)==url
    assert resolve_connection({'connection':config},saved)==url
    for key,value in [('kind','mysql'),('host','other'),('port','5433'),('database','other'),('user','other')]:
        with pytest.raises(RuleError):
            resolve_connection({'connection':{**config,key:value}},saved)


@pytest.mark.parametrize('url',[
    'postgresql+asyncpg://reader:secret@postgres:5433/diploma',
    'postgresql+asyncpg://reader:secret@elsewhere/diploma',
    'postgresql+asyncpg://reader:secret@postgres/diploma?ssl=false',
    'mysql+asyncmy://reader:secret@postgres/diploma',
    'mongodb://reader:secret@postgres/diploma?authSource=admin',
])
def test_endpoint_and_driver_options_rejected(source_env,url):
    with pytest.raises(RuleError): connection_policy(url)


def test_only_allowed_resource_and_fields(source_env):
    config=dict(url='postgresql+asyncpg://reader:secret@postgres/diploma',table_name='demo.requests',key_field='id',allowed_fields=['amount'],mapping={'amount':'amount'})
    validate_source(config)
    for change in [{'table_name':'demo.secret'},{'key_field':'id; DROP TABLE x'},{'mapping':{'amount':'secret'}}]:
        with pytest.raises(RuleError): validate_source({**config,**change})


def test_exact_money_and_keys():
    from bson import Decimal128, ObjectId
    assert normalize(Decimal('1234567890123456.1250'),'number')=='1234567890123456.1250'
    assert normalize(Decimal128('1234567890123456.1250'),'number')=='1234567890123456.1250'
    assert typed_key('001','string')=='001'
    assert typed_key('001','integer')==1
    oid='000000000000000000000001'
    assert typed_key(oid,'objectid')==ObjectId(oid)
    assert normalize(ObjectId(oid),'objectid')==oid
    for value,kind in [('1.2','integer'),(True,'integer'),('true','boolean'),({},'string'),('invalid','objectid')]:
        with pytest.raises(RuleError): typed_key(value,kind)
    for value,kind in [(True,'number'),('12','number'),(1,'boolean'),({},'string'),(Decimal('NaN'),'number')]:
        with pytest.raises(RuleError): normalize(value,kind)


def test_custom_catalog_statuses_and_suggestions():
    validate_catalog({'transfer':{'statuses':['POSTED','REVERSED'],'fields':{'amount':{'type':'number','values':['0.125'],'label':'Сумма'}}}})
    for statuses in ['POSTED', [''], [True]]:
        with pytest.raises(RuleError): validate_catalog({'transfer':{'statuses':statuses,'fields':{'id':{'type':'string'}}}})


def test_discovery_empty_unknown_and_partial(source_env,monkeypatch,tmp_path):
    file=tmp_path/'inventory.json'
    monkeypatch.setenv('DIPLOMA_SOURCE_INVENTORY',str(file))
    data={'updated_at':'2099-01-01T00:00:00Z','sources':[]}
    file.write_text(json.dumps(data))
    assert asyncio.run(discover())['sources']==[]
    calls=[]
    async def connect(host,port):
        calls.append((host,port))
        raise OSError('offline')
    monkeypatch.setattr(asyncio,'open_connection',connect)
    data['sources']=[{'id':'pg','kind':'postgresql','host':'postgres','port':5432}, {'id':'unknown','kind':'unknown','host':'outside','port':1234}]
    file.write_text(json.dumps(data))
    result=asyncio.run(discover())
    assert calls==[('postgres',5432)]
    assert [r['state'] for r in result['sources']]==['unavailable','detected']
    assert result['warnings']


def test_external_policy_extends_defaults_and_discovery_does_not_probe_it(source_env, monkeypatch, tmp_path):
    path = tmp_path / "extra.json"
    inventory = tmp_path / "inventory.json"
    windows = {"id": "windows-pg", "kind": "postgresql", "host": "host.docker.internal", "port": 5432}
    cloud = {"id": "cloud-mongo", "kind": "mongodb", "host": "192.0.2.10", "port": 37017}
    path.write_text(json.dumps({"endpoints": [
        {**windows, "databases": {"expenses": {"public.operations": {}}}},
        {**cloud, "auth_database": "admin", "databases": {"expenses": {"operations": {}}}},
    ]}))
    inventory.write_text(json.dumps({"updated_at": "2099-01-01T00:00:00Z", "scope": "Windows",
                                    "sources": [{**windows, "origin": "Windows"}]}))
    monkeypatch.setenv("DIPLOMA_SOURCE_EXTRA_POLICY", str(path))
    monkeypatch.setenv("DIPLOMA_SOURCE_INVENTORY", str(inventory))

    async def unexpected_probe(*args):
        pytest.fail("Opening the source list must not probe a host or external database")

    monkeypatch.setattr(asyncio, "open_connection", unexpected_probe)
    result = asyncio.run(discover())
    assert "Windows" in result["scope"]
    assert [(row["id"], row["state"], row["origin"]) for row in result["sources"]] == [
        ("windows-pg", "configured", "Windows"),
        ("cloud-mongo", "configured", "Объявлен в серверной политике"),
    ]
    assert all(row["selectable"] and row["databases"] == ["expenses"] for row in result["sources"])
    _, _, endpoint, _ = connection_policy("mongodb://reader:secret@192.0.2.10:37017/expenses")
    assert endpoint["tls"] is True and endpoint["auth_database"] == "admin"
    assert connection_policy("postgresql+asyncpg://reader:secret@postgres/diploma")[1] == "postgresql"
    with pytest.raises(RuleError):
        connection_policy("mongodb://reader:secret@192.0.2.10/expenses")
    with pytest.raises(RuleError):
        connection_policy("mongodb://reader:secret@192.0.2.10:37017/private")
