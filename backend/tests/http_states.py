"""Decision state boundaries and concurrent business updates over real HTTP."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import os
import httpx2 as httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values('../.env')
    prefix = 'qa-state-' + str(uuid4())[:8]
    clients = {}
    def call(role, path, payload=None, method='POST', expected=200):
        response = clients[role].request(method, '/api' + path, json=payload)
        assert response.status_code == expected, f'{path}: {response.status_code}'
        return response.json()
    def new():
        payload = {'amount': '500', 'recipient': 'Учебный получатель', 'receipt': prefix, 'vendor': 'QA', 'purchase_date': '2026-10-05', 'title': prefix}
        return call('employee', '/demo/requests', payload), payload
    def attempt(row, action, role):
        return call(role, '/demo/requests/' + row['id'] + '/check', {'operation_id': str(uuid4()), 'action': action})
    def perform(d, role, expected=200):
        return call(role, '/demo/execute', {'operation_id': d['operation_id'], 'decision_id': d['id']}, expected=expected)
    def business(row):
        perform(attempt(row, 'submit', 'employee'), 'employee')
        perform(attempt(row, 'approve', 'manager'), 'manager')
    def race(first, second):
        barrier = Barrier(2)
        def run(task):
            barrier.wait()
            return task()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, task) for task in (first, second)]
            return [f.result() for f in futures]
    rules = []
    original_app = None
    try:
        for role in ('admin', 'employee', 'manager', 'accountant', 'specialist'):
            clients[role] = httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=20, headers={'X-Requested-With': 'antifraud-ui'})
            call(role, '/auth/login', {'username': role, 'password': env['DIPLOMA_SEED_PASSWORD']})
        for _ in range(8):
            row, data = new(); business(row)
            d = attempt(row, 'pay', 'accountant')
            payment = {'operation_id': d['operation_id'], 'decision_id': d['id']}
            edit, pay = race(lambda: clients['employee'].put('/api/demo/requests/' + row['id'], json={**data, 'amount': '600'}),
                             lambda: clients['accountant'].post('/api/demo/execute', json=payment))
            assert (edit.status_code, pay.status_code) in {(200, 409), (409, 200)}
            current = next(r for r in call('employee', '/demo/requests', method='GET') if r['id'] == row['id'])
            if pay.status_code == 200:
                assert current['status'] == 'PAID' and current['amount'] == '500.00'
            else:
                assert current['status'] == 'DRAFT' and current['amount'] == '600.00'
        print('PASS: 8 edit/execution races; compare and write share record lock')
        for _ in range(8):
            row, _ = new(); d = attempt(row, 'submit', 'employee')
            execute_response, cancel_response = race(lambda: clients['employee'].post('/api/demo/execute', json={'operation_id': d['operation_id'], 'decision_id': d['id']}),
                                                     lambda: clients['employee'].post('/api/demo/decisions/' + d['id'] + '/cancel'))
            assert (execute_response.status_code, cancel_response.status_code) in {(200, 409), (409, 200)}
            current = call('employee', '/decisions/' + d['id'], method='GET')
            assert (current['state'] == 'CANCELLED' and not current['executed_at']) or (current['state'] == 'APPROVED' and current['executed_at'])
        print('PASS: 8 cancel/execution races; one committed outcome')
        row, _ = new(); business(row)
        first, second = attempt(row, 'pay', 'accountant'), attempt(row, 'pay', 'accountant')
        results = race(lambda: clients['accountant'].post('/api/demo/execute', json={'operation_id': first['operation_id'], 'decision_id': first['id']}),
                       lambda: clients['accountant'].post('/api/demo/execute', json={'operation_id': second['operation_id'], 'decision_id': second['id']}))
        assert sorted(r.status_code for r in results) == [200, 409]
        print('PASS: competing approved attempts cannot pay the same request twice')

        expression = {'kind': 'field', 'field': 'receipt', 'op': 'eq', 'value': prefix}
        review_rule = call('admin', '/admin/rules', {'application_id': 'demo', 'name': prefix + '-review', 'action': 'submit', 'reaction': 'REVIEW', 'expression': expression})
        rules.append(review_rule)
        row, _ = new(); d = attempt(row, 'submit', 'employee')
        rejected = call('specialist', '/decisions/' + d['id'] + '/review', {'approve': False, 'comment': 'Учебный отказ'})
        assert rejected['state'] == 'REJECTED'
        perform(d, 'employee', 409)
        for r in rules:
            call('admin', '/admin/rules/' + r['id'], {**{k: v for k, v in r.items() if k not in {'id', 'version'}}, 'enabled': False}, 'PUT')
        confirmation_rule = call('admin', '/admin/rules', {'application_id': 'demo', 'name': prefix + '-confirm', 'action': 'submit', 'reaction': 'CONFIRM', 'expression': expression})
        rules.append(confirmation_rule)
        row, _ = new(); d = attempt(row, 'submit', 'employee')
        refused = call('employee', '/demo/decisions/' + d['id'] + '/confirm', {'approve': False, 'operation_id': d['operation_id'], 'checked_values': d['checked_values']})
        assert refused['state'] == 'CANCELLED'
        row, data = new(); d = attempt(row, 'submit', 'employee')
        call('employee', '/demo/requests/' + row['id'], {**data, 'amount': '600'}, 'PUT')
        call('employee', '/demo/decisions/' + d['id'] + '/confirm', {'approve': True, 'operation_id': d['operation_id'], 'checked_values': d['checked_values']}, expected=409)
        assert call('employee', '/decisions/' + d['id'], method='GET')['state'] == 'CANCELLED'
        print('PASS: specialist rejection, initiator refusal, data changed before confirmation')

        original_app = next(a for a in call('admin', '/admin/applications', method='GET') if a['id'] == 'demo')
        call('admin', '/admin/applications/demo', {**original_app, 'ttl_seconds': 1}, 'PUT')
        row, _ = new(); d = attempt(row, 'submit', 'employee')
        assert d['state'] == 'PENDING_CONFIRMATION'
        # Docker Desktop's wall clock can be resynchronized independently of the
        # host's sleep. Observe expiry against the server's authoritative clock.
        wait_until = monotonic() + 15
        while call('employee', '/decisions/' + d['id'], method='GET')['state'] != 'EXPIRED':
            assert monotonic() < wait_until, 'Server deadline did not expire within the clock-drift allowance'
            sleep(.2)
        call('employee', '/demo/decisions/' + d['id'] + '/confirm', {'approve': True, 'operation_id': d['operation_id'], 'checked_values': d['checked_values']}, expected=409)
        expired = call('employee', '/decisions/' + d['id'], method='GET')
        assert expired['state'] == 'EXPIRED'
        perform(d, 'employee', 409)
        print('PASS: expiry during confirmation and final execution admission')
    finally:
        if original_app:
            call('admin', '/admin/applications/demo', original_app, 'PUT')
        for r in rules:
            call('admin', '/admin/rules/' + r['id'], {**{k: v for k, v in r.items() if k not in {'id', 'version'}}, 'enabled': False}, 'PUT')
        for client in clients.values(): client.close()


if __name__ == '__main__':
    main()
