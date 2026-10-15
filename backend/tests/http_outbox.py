"""Run against an ephemeral backend replica with unavailable delivery URL on port 8101."""
from uuid import uuid4
import os

import httpx2 as httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values('../.env')
    clients = {}
    def call(client, path, payload=None, method='POST'):
        response = client.request(method, '/api' + path, json=payload)
        assert response.status_code == 200, f'{path}: {response.status_code}'
        return response.json()
    def attempt(row, action, client):
        return call(client, '/demo/requests/' + row['id'] + '/check', {'action': action, 'operation_id': str(uuid4())})
    def perform(d, client):
        return call(client, '/demo/execute', {'operation_id': d['operation_id'], 'decision_id': d['id']})
    try:
        normal = os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000')
        outage = os.environ.get('DIPLOMA_TEST_OUTAGE_URL', 'http://127.0.0.1:8101')
        for name, role, base in (('employee', 'employee', normal), ('manager', 'manager', normal), ('accountant', 'accountant', normal), ('outage', 'accountant', outage)):
            clients[name] = httpx.Client(trust_env=False, base_url=base, timeout=20, headers={'X-Requested-With': 'antifraud-ui'})
            call(clients[name], '/auth/login', {'username': role, 'password': env['DIPLOMA_SEED_PASSWORD']})
        row = call(clients['employee'], '/demo/requests', {'amount': '500', 'recipient': 'Учебный получатель', 'receipt': 'qa-outbox-' + str(uuid4())[:8], 'vendor': 'QA', 'purchase_date': '2026-10-05', 'title': 'QA: потеря сообщения'})
        perform(attempt(row, 'submit', clients['employee']), clients['employee'])
        perform(attempt(row, 'approve', clients['manager']), clients['manager'])
        decision = attempt(row, 'pay', clients['accountant'])
        saved = perform(decision, clients['outage'])
        assert saved['request']['status'] == 'PAID' and saved['event_delivery']['pending']
        detail = call(clients['accountant'], '/decisions/' + decision['id'], method='GET')
        assert detail['executed_at'] and detail['events'] == []
        repeated = perform(decision, clients['outage'])
        assert repeated['executed_at'] == saved['executed_at'] and repeated['event_delivery']['pending']
        delivered = call(clients['accountant'], '/demo/outbox/deliver')
        assert delivered['delivered'] >= 1
        detail = call(clients['accountant'], '/decisions/' + decision['id'], method='GET')
        assert len(detail['events']) == 1
        assert call(clients['accountant'], '/demo/outbox/deliver')['delivered'] == 0
        print('PASS: lost delivery preserves action/outbox; repeated execution does not pay twice; redelivery creates one event')
    finally:
        for client in clients.values(): client.close()


if __name__ == '__main__':
    main()
