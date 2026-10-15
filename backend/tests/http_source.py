"""Read-only PostgreSQL connector, source snapshots and safe errors through real HTTP."""
from time import perf_counter
from uuid import uuid4

import os
import httpx2 as httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values('../.env')
    prefix = 'qa-db-' + str(uuid4())[:8]
    admin = httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=20, headers={'X-Requested-With': 'antifraud-ui'})
    employee = httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=20, headers={'X-Requested-With': 'antifraud-ui'})
    def call(client, path, payload=None, method='POST', headers=None, expected=200):
        response = client.request(method, '/api' + path, json=payload, headers=headers)
        assert response.status_code == expected, f'{path}: {response.status_code}'
        result = response.json()
        if path != '/admin/applications':
            for name in ('DIPLOMA_READER_PASSWORD', 'DIPLOMA_DEMO_PASSWORD', 'DIPLOMA_SOURCE_ENCRYPTION_KEY'):
                assert env[name] not in response.text, 'Secret leaked'
        return result
    try:
        for client, username in ((admin, 'admin'), (employee, 'employee')):
            call(client, '/auth/login', {'username': username, 'password': env['DIPLOMA_SEED_PASSWORD']})
        expense_data = {'amount': '500', 'recipient': 'DB получатель', 'receipt': prefix, 'vendor': 'QA', 'purchase_date': '2026-10-05', 'title': prefix}
        row = call(employee, '/demo/requests', expense_data)
        catalog = {'transfer': {'fields': {'amount': {'type': 'number', 'required': True, 'source': 'DB'}, 'recipient': {'type': 'string', 'required': True, 'source': 'DB'}}}}
        created = call(admin, '/admin/applications', {'id': prefix, 'name': 'QA источник', 'ttl_seconds': 600, 'catalog': catalog})
        key = {'X-Application-Key': created['api_key']}
        settings = {'url': 'postgresql+asyncpg://diploma_reader:' + env['DIPLOMA_READER_PASSWORD'] + '@postgres:5432/' + env.get('POSTGRES_DB', 'diploma'),
                    'table_name': 'demo.requests', 'key_field': 'id', 'allowed_fields': ['amount', 'recipient'], 'mapping': {'amount': 'amount', 'recipient': 'recipient'}}
        call(admin, '/admin/sources/' + prefix, settings, 'PUT')
        saved = call(admin, '/admin/sources/' + prefix, method='GET')
        assert 'url' not in saved and saved['credentials_saved']
        call(admin, '/admin/rules', {'application_id': prefix, 'name': 'QA DB сумма', 'action': 'transfer', 'reaction': 'BLOCK', 'expression': {'kind': 'field', 'field': 'amount', 'op': 'gt', 'value': 1000}})
        payload = {'application_id': prefix, 'operation_id': str(uuid4()), 'action': 'transfer', 'initiator': 'actor', 'record_key': row['id'], 'fields': {'amount': 99999, 'recipient': 'Подмена API'}}
        start = perf_counter()
        allowed = call(admin, '/checks', payload, headers=key)
        elapsed = perf_counter() - start
        assert allowed['state'] == 'APPROVED' and allowed['checked_values'] == {'amount': '500', 'recipient': 'DB получатель'}
        call(employee, '/demo/requests/' + row['id'], {**expense_data, 'amount': '1500'}, 'PUT')
        repeated = call(admin, '/checks', payload, headers=key)
        assert repeated['state'] == 'CANCELLED' and repeated['expires_at'] == allowed['expires_at']
        denied = call(admin, '/checks', {**payload, 'operation_id': str(uuid4())}, headers=key)
        assert denied['state'] == 'REJECTED' and denied['checked_values']['amount'] == '1500'
        print('PASS: read-only source, one source per field, DB snapshot/recheck; first read seconds:', round(elapsed, 4))
        missing = call(admin, '/checks', {**payload, 'operation_id': str(uuid4()), 'record_key': 'missing'}, headers=key)
        assert missing['state'] == 'REJECTED'
        call(admin, '/admin/sources/' + prefix, {**settings, 'table_name': 'demo.requests; DROP TABLE demo.requests'}, 'PUT', expected=422)
        call(admin, '/admin/sources/' + prefix, {**settings, 'mapping': {'amount': 'password'}}, 'PUT', expected=422)
        print('PASS: missing row, SQL/table injection and unapproved field denied')
        writer = {**settings, 'url': 'postgresql+asyncpg://diploma_demo:' + env['DIPLOMA_DEMO_PASSWORD'] + '@postgres:5432/' + env.get('POSTGRES_DB', 'diploma')}
        call(admin, '/admin/sources/' + prefix, writer, 'PUT')
        unsafe = call(admin, '/checks', {**payload, 'operation_id': str(uuid4())}, headers=key)
        assert unsafe['state'] == 'REJECTED' and unsafe['reasons'][0]['error'] == 'source_or_field_error'
        call(admin, '/admin/sources/' + prefix, {**settings, 'url': settings['url'].replace(':5432/', ':5433/')}, 'PUT')
        failed = call(admin, '/checks', {**payload, 'operation_id': str(uuid4())}, headers=key)
        assert failed['state'] == 'REJECTED'
        print('PASS: writable credentials and unreachable DB fail closed without secret disclosure')
        call(admin, '/admin/sources/' + prefix, settings, 'PUT')
    finally:
        admin.close(); employee.close()


if __name__ == '__main__':
    main()
