"""Persisted rules, sessions, checks, facts and one-time execution across restart."""
import subprocess
from time import monotonic, sleep
from uuid import uuid4

import os
import httpx2 as httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values('../.env')
    prefix = 'qa-restart-' + str(uuid4())[:8]
    with httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=20,
                      headers={'X-Requested-With': 'antifraud-ui'}) as admin, \
         httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=20,
                      headers={'X-Requested-With': 'antifraud-ui'}) as employee:
        def call(client, path, body=None, method='POST'):
            response = client.request(method, '/api' + path, json=body)
            assert response.status_code == 200, path + ': HTTP ' + str(response.status_code)
            return response.json()
        for client, role in ((admin, 'admin'), (employee, 'employee')):
            call(client, '/auth/login', {'username': role, 'password': env['DIPLOMA_SEED_PASSWORD']})
        rule = call(admin, '/admin/rules', {'application_id': 'demo', 'name': prefix, 'action': 'submit', 'reaction': 'LOG',
                     'expression': {'kind': 'field', 'field': 'receipt', 'op': 'eq', 'value': prefix}})
        row = call(employee, '/demo/requests', {'amount': '500', 'recipient': 'QA', 'receipt': prefix, 'vendor': 'QA', 'purchase_date': '2026-10-05', 'title': prefix})
        d = call(employee, '/demo/requests/' + row['id'] + '/check', {'operation_id': str(uuid4()), 'action': 'submit'})
        execution = {'operation_id': d['operation_id'], 'decision_id': d['id']}
        result = call(employee, '/demo/execute', execution)
        before = call(employee, '/decisions/' + d['id'], method='GET')
        assert len(before['events']) == 1
        restarted = subprocess.run(['docker', 'compose', 'restart', 'postgres', 'backend'], capture_output=True, text=True)
        assert restarted.returncode == 0, 'Compose restart failed'
        until = monotonic() + 60
        while True:
            try:
                ready = admin.get('/health').status_code == 200
            except httpx.HTTPError:
                ready = False
            if ready: break
            assert monotonic() < until, 'Backend did not recover'
            sleep(.5)
        after = call(employee, '/decisions/' + d['id'], method='GET')
        assert before == after
        replay = call(employee, '/demo/execute', execution)
        assert replay['request'] == result['request'] and replay['executed_at'] == result['executed_at']
        saved = call(admin, '/admin/rules?application_id=demo', method='GET')
        assert next(r for r in saved if r['id'] == rule['id']) == rule
        assert len(call(employee, '/decisions/' + d['id'], method='GET')['events']) == 1
        call(admin, '/admin/rules/' + rule['id'], {**{k: v for k, v in rule.items() if k not in {'id', 'version'}}, 'enabled': False}, 'PUT')
        print('PASS: restart preserves rule, session, snapshot, transitions, factual event and idempotent execution')


if __name__ == '__main__':
    main()
