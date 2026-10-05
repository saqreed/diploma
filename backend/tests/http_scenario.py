"""Real HTTP + PostgreSQL acceptance checks. Creates labeled educational records only.

Run from backend with --env-file ../.env; never prints credentials or session cookies.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import uuid4

import httpx2 as httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', default='../.env')
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    env = dotenv_values(Path(args.env_file))
    clients = {}
    run_id = 'qa-' + str(uuid4())[:8]
    checks = []

    def call(role, path, method='GET', body=None, status=200):
        response = clients[role].request(method, path, json=body)
        assert response.status_code == status, f'{method} {path}: expected {status}, got {response.status_code}; {response.json().get("code", "") if isinstance(response.json(), dict) else ""}'
        return response.json()

    def check(name):
        checks.append(name)
        print('PASS:', name)

    def new_expense(amount='500', role='employee'):
        return call(role, '/api/demo/requests', 'POST', {'amount': amount, 'recipient': 'Учебный получатель', 'receipt': run_id,
             'vendor': 'QA', 'purchase_date': '2026-10-05', 'title': run_id})

    def attempt(row, action, role):
        return call(role, '/api/demo/requests/' + row['id'] + '/check', 'POST', {'operation_id': str(uuid4()), 'action': action})

    def perform(decision, role, status=200):
        return call(role, '/api/demo/execute', 'POST', {'operation_id': decision['operation_id'], 'decision_id': decision['id']}, status)

    def approve_business(row):
        perform(attempt(row, 'submit', 'employee'), 'employee')
        perform(attempt(row, 'approve', 'manager'), 'manager')

    created_rules = []
    try:
        for role in ('admin', 'specialist', 'employee', 'employee2', 'manager', 'accountant'):
            clients[role] = httpx.Client(trust_env=False, base_url=args.url, timeout=20, headers={'X-Requested-With': 'antifraud-ui'})
            result = call(role, '/api/auth/login', 'POST', {'username': role, 'password': env['DIPLOMA_SEED_PASSWORD']})
            assert result['id'] == role
        check('Вход с шестью подготовленными аккаунтами')
        call('employee', '/api/admin/rules', status=403)
        call('admin', '/api/demo/requests', status=403)
        check('Роли проверяются сервером')
        row = new_expense()
        d = attempt(row, 'submit', 'employee')
        assert d['state'] == 'APPROVED'
        repeat = call('employee', '/api/demo/requests/' + row['id'] + '/check', 'POST', {'operation_id': d['operation_id'], 'action': 'submit'})
        assert repeat['id'] == d['id'] and repeat['expires_at'] == d['expires_at']
        assert not call('employee', '/api/decisions/' + d['id'])['events']
        result = perform(d, 'employee')
        assert result['request']['status'] == 'SUBMITTED'
        detail = call('employee', '/api/decisions/' + d['id'])
        assert len(detail['events']) == 1 and detail['executed_at']
        check('Проверка и фактическое событие раздельны; повтор не продлевает срок')
        perform(attempt(row, 'approve', 'manager'), 'manager')
        pay = attempt(row, 'pay', 'accountant')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: perform(pay, 'accountant'), range(4)))
        assert all(r['request']['status'] == 'PAID' and r['executed_at'] == results[0]['executed_at'] for r in results)
        assert len(call('accountant', '/api/decisions/' + pay['id'])['events']) == 1
        other = attempt(row, 'pay', 'accountant')
        perform(other, 'accountant', 409)
        check('Параллельные повторы дают одну выплату и одно событие')
        call('employee2', '/api/demo/execute', 'POST', {'operation_id': pay['operation_id'], 'decision_id': pay['id']}, 403)
        call('accountant', '/api/demo/execute', 'POST', {'operation_id': 'forged', 'decision_id': pay['id']}, 403)
        check('Чужое и подменённое решение не разрешает действие')

        # Every test rule is scoped to a unique receipt, preserving existing rules.
        for reaction in ('REVIEW', 'CONFIRM'):
            payload = {'application_id': 'demo', 'name': run_id + ':' + reaction, 'action': 'pay', 'enabled': True, 'reaction': reaction,
                       'expression': {'kind': 'all', 'children': [{'kind': 'field', 'field': 'receipt', 'op': 'eq', 'value': run_id}, {'kind': 'field', 'field': 'amount', 'op': 'gt', 'value': 1000}]}}
            created_rules.append(call('admin', '/api/admin/rules', 'POST', payload))
        large = new_expense('15000')
        approve_business(large)
        both = attempt(large, 'pay', 'accountant')
        assert both['state'] == 'PENDING_REVIEW' and set(both['remaining_steps']) == {'REVIEW', 'CONFIRM'}
        deadline = both['expires_at']
        call('accountant', '/api/decisions/' + both['id'] + '/review', 'POST', {'approve': True}, 403)
        after = call('specialist', '/api/decisions/' + both['id'] + '/review', 'POST', {'approve': True, 'comment': 'Учебная проверка'})
        assert after['state'] == 'PENDING_CONFIRMATION' and after['expires_at'] == deadline
        perform(after, 'accountant', 409)
        confirmation = {'operation_id': both['operation_id'], 'checked_values': both['checked_values'], 'approve': True}
        call('employee', '/api/demo/decisions/' + both['id'] + '/confirm', 'POST', confirmation, 403)
        call('accountant', '/api/demo/decisions/' + both['id'] + '/confirm', 'POST', {**confirmation, 'checked_values': {'amount': 1}}, 409)
        confirmed = call('accountant', '/api/demo/decisions/' + both['id'] + '/confirm', 'POST', confirmation)
        assert confirmed['state'] == 'APPROVED' and confirmed['expires_at'] == deadline
        perform(confirmed, 'accountant')
        check('REVIEW + CONFIRM: оба этапа, полномочия, значения и исходный срок')

        changed = new_expense()
        approve_business(changed)
        old = attempt(changed, 'pay', 'accountant')
        updated = call('employee', '/api/demo/requests/' + changed['id'], 'PUT', {'amount': '600', 'recipient': 'Другой получатель', 'receipt': run_id, 'vendor': 'QA', 'purchase_date': '2026-10-05', 'title': run_id})
        assert updated['status'] == 'DRAFT' and updated['approver'] is None
        perform(old, 'accountant', 409)
        assert call('accountant', '/api/decisions/' + old['id'])['state'] == 'CANCELLED'
        check('Изменение суммы/получателя отменяет разрешение и бизнес-согласование')

        cancel_row = new_expense()
        cancelled = attempt(cancel_row, 'submit', 'employee')
        call('employee', '/api/demo/decisions/' + cancelled['id'] + '/cancel', 'POST')
        perform(cancelled, 'employee', 409)
        check('Успешная отмена запрещает последующее выполнение')
        own = new_expense(role='manager')
        call('manager', '/api/demo/requests/' + own['id'] + '/check', 'POST', {'operation_id': str(uuid4()), 'action': 'approve'}, 403)
        check('Автор не согласует свою заявку')

        key_result = call('admin', '/api/admin/applications', 'POST', {'id': run_id, 'name': 'QA: независимая предметная область', 'ttl_seconds': 1,
                         'catalog': {'visit': {'fields': {'object': {'type': 'string', 'source': 'API', 'required': True}}}}})
        headers = {'X-Application-Key': key_result['api_key']}
        payload = {'application_id': run_id, 'operation_id': 'ttl', 'action': 'visit', 'initiator': 'visitor', 'fields': {'object': 'o1'}}
        api_client = clients['admin']
        expiry = api_client.post('/api/checks', json=payload, headers=headers).json()
        assert expiry['state'] == 'APPROVED'
        until = time.monotonic() + 15
        expired = expiry
        while expired['state'] != 'EXPIRED':
            assert time.monotonic() < until, 'Server deadline did not expire within the clock-drift allowance'
            time.sleep(.2)
            expired = api_client.post('/api/checks', json=payload, headers=headers).json()
            assert expired['expires_at'] == expiry['expires_at']
        assert expired['state'] == 'EXPIRED' and expired['expires_at'] == expiry['expires_at']
        missing = api_client.post('/api/checks', json={**payload, 'operation_id': 'missing', 'fields': {}}, headers=headers).json()
        assert missing['state'] == 'REJECTED'
        e = {'application_id': run_id, 'event_id': 'event-1', 'event_at': datetime.now(timezone.utc).isoformat(), 'action': 'visit', 'actor': 'visitor', 'status': 'SUCCESS', 'fields': {'object': 'o1'}}
        first = api_client.post('/api/events', json=e, headers=headers).json()
        duplicate = api_client.post('/api/events', json=e, headers=headers).json()
        assert first['id'] == duplicate['id'] and duplicate['duplicate']
        assert api_client.post('/api/events', json={**e, 'fields': {'object': 'o2'}}, headers=headers).status_code == 409
        check('Независимый каталог: срок, обязательное поле, повторная доставка событий')
        call('employee', '/api/auth/logout', 'POST')
        call('employee', '/api/demo/requests', status=401)
        check('Выход прекращает доступ к серверу')
    finally:
        for rule in created_rules:
            try:
                payload = {key: value for key, value in rule.items() if key not in {'id', 'version'}}
                payload['enabled'] = False
                call('admin', '/api/admin/rules/' + rule['id'], 'PUT', payload)
            except Exception:
                print('WARNING: QA rule needs disabling:', rule['id'])
        for client in clients.values():
            client.close()
    print(f'{len(checks)} acceptance groups passed. Educational records are retained with prefix {run_id}.')


if __name__ == '__main__':
    main()
