"""Registry snapshot binding, saved replay and explicit demo reset with durable archive."""
from uuid import uuid4

import os
import httpx2 as httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values('../.env')
    clients = {}
    def call(role, path, payload=None, method='POST', expected=200):
        r = clients[role].request(method, '/api' + path, json=payload)
        assert r.status_code == expected, f'{path}: {r.status_code}'
        return r.json()
    try:
        for role in ('admin', 'employee', 'accountant'):
            clients[role] = httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=20, headers={'X-Requested-With': 'antifraud-ui'})
            call(role, '/auth/login', {'username': role, 'password': env['DIPLOMA_SEED_PASSWORD']})
        def export():
            return call('accountant', '/demo/export/check', {'operation_id': str(uuid4())})
        def execute(d, expected=200):
            return call('accountant', '/demo/execute', {'operation_id': d['operation_id'], 'decision_id': d['id']}, expected=expected)
        d = export()
        assert d['state'] == 'APPROVED' and d['checked_values']['registry_snapshot']
        saved = execute(d)
        assert len(saved['records']) == int(d['checked_values']['record_count'])
        repeated = execute(d)
        assert repeated['records'] == saved['records'] and repeated['executed_at'] == saved['executed_at']
        changed = export()
        row = call('employee', '/demo/requests', {'amount': '500', 'recipient': 'QA реестр', 'receipt': 'QA-REGISTRY', 'vendor': 'QA', 'purchase_date': '2026-10-05', 'title': 'QA реестр'})
        execute(changed, 409)
        print('PASS: complete registry snapshot, record_count, persisted replay and insertion before execution')
        pending = call('employee', '/demo/requests/' + row['id'] + '/check', {'operation_id': str(uuid4()), 'action': 'submit'})
        call('employee', '/demo/reset', {'confirmation': 'Вернуть учебное демо'}, expected=403)
        call('admin', '/demo/reset', {'confirmation': 'wrong'}, expected=422)
        reset = call('admin', '/demo/reset', {'confirmation': 'Вернуть учебное демо'})
        assert reset['archived_requests'] == len(saved['records']) + 1 and reset['archive_id']
        new_rows = call('accountant', '/demo/requests', method='GET')
        assert len(new_rows) == 5 and all(r['status'] == 'DRAFT' for r in new_rows)
        assert sorted(r['amount'] for r in new_rows) == ['20000.00', '500.00', '500.00', '6000.00', '6000.00']
        assert call('employee', '/decisions/' + pending['id'], method='GET')['state'] == 'CANCELLED'
        assert execute(d)['records'] == saved['records']
        print('PASS: explicit admin reset, five initial fixtures including split amounts, old decisions/history/replays retained; archive id:', reset['archive_id'])
    finally:
        for client in clients.values(): client.close()


if __name__ == '__main__':
    main()
