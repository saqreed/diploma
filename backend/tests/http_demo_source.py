"""Demo binds API + DB fields and protects its required execution snapshot."""
from copy import deepcopy
from uuid import uuid4
import os
import httpx2 as httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values('../.env')
    clients = {role: httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=20,
              headers={'X-Requested-With': 'antifraud-ui'}) for role in ('admin', 'employee')}
    original = None
    def call(role, path, payload=None, method='POST', expected=200):
        response = clients[role].request(method, '/api' + path, json=payload)
        assert response.status_code == expected, path + ': HTTP ' + str(response.status_code)
        return response.json()
    try:
        for role in clients:
            call(role, '/auth/login', {'username': role, 'password': env['DIPLOMA_SEED_PASSWORD']})
        original = next(a for a in call('admin', '/admin/applications', method='GET') if a['id'] == 'demo')
        weakened = deepcopy(original)
        del weakened['catalog']['pay']['fields']['version']
        call('admin', '/admin/applications/demo', weakened, 'PUT', expected=422)
        settings = {'url': 'postgresql+asyncpg://diploma_reader:' + env['DIPLOMA_READER_PASSWORD'] + '@postgres:5432/' + env.get('POSTGRES_DB', 'diploma'),
                    'table_name': 'demo.requests', 'key_field': 'id', 'allowed_fields': ['amount'], 'mapping': {'amount': 'amount'}}
        call('admin', '/admin/sources/demo', settings, 'PUT')
        sourced = deepcopy(original)
        sourced['catalog']['submit']['fields']['amount']['source'] = 'DB'
        call('admin', '/admin/applications/demo', sourced, 'PUT')
        data = {'amount': '500', 'recipient': 'Учебный получатель', 'receipt': 'qa-mixed-' + str(uuid4())[:8], 'vendor': 'QA', 'purchase_date': '2026-10-05', 'title': 'QA API + DB snapshot'}
        row = call('employee', '/demo/requests', data)
        attempt = lambda: call('employee', '/demo/requests/' + row['id'] + '/check', {'action': 'submit', 'operation_id': str(uuid4())})
        d = attempt()
        assert d['state'] == 'APPROVED' and d['checked_values']['amount'] == '500'
        call('employee', '/demo/requests/' + row['id'], {**data, 'amount': '600'}, 'PUT')
        call('employee', '/demo/execute', {'operation_id': d['operation_id'], 'decision_id': d['id']}, expected=409)
        assert call('employee', '/decisions/' + d['id'], method='GET')['state'] == 'CANCELLED'
        current = attempt()
        result = call('employee', '/demo/execute', {'operation_id': current['operation_id'], 'decision_id': current['id']})
        assert result['request']['amount'] == '600.00'
        assert len(call('employee', '/decisions/' + current['id'], method='GET')['events']) == 1
        print('PASS: mixed API/DB demo snapshot, edit invalidates decision, atomic execution and separate event; catalog cannot weaken bindings')
    finally:
        if original: call('admin', '/admin/applications/demo', original, 'PUT')
        for client in clients.values(): client.close()


if __name__ == '__main__':
    main()
