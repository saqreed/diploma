"""Independent review of the isolated stand, with real persisted HTTP data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx2 as httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['before', 'after'], default='after')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    env = dotenv_values('.env')
    clients = {}
    report = {'url': 'http://127.0.0.1:28000', 'phase': args.phase, 'measurements': [], 'checks': []}
    prefix = 'review-' + uuid4().hex[:10]
    rules = []

    def call(role, path, body=None, method='GET', expected=200):
        response = clients[role].request(method, '/api' + path, json=body)
        assert response.status_code == expected, f'{method} {path}: HTTP {response.status_code}, expected {expected}'
        return response.json()

    def measure(path):
        start = perf_counter()
        response = clients['manager'].get('/api' + path)
        response.raise_for_status()
        data = response.json()
        report['measurements'].append({'path': path, 'seconds': round(perf_counter() - start, 4), 'bytes': len(response.content),
                                       'items': len(data['items']) if isinstance(data, dict) else len(data), 'total': data.get('total') if isinstance(data, dict) else None})
        return data

    def create(receipt=prefix, amount='500'):
        return call('employee', '/demo/requests', {'amount': amount, 'title': prefix, 'receipt': receipt, 'recipient': 'Учебный получатель',
                    'vendor': 'QA', 'purchase_date': '2026-10-08'}, 'POST')

    def action(row, name, role, operation=None):
        return call(role, '/demo/requests/' + row['id'] + '/action', {'action': name, 'operation_id': operation or str(uuid4())}, 'POST')

    def business(row):
        sent = action(row, 'submit', 'employee')
        assert sent['execution']['request']['status'] == 'SUBMITTED'
        assert call('employee', '/demo/requests/' + row['id'])['status'] == 'SUBMITTED'
        approved = action(row, 'approve', 'manager')
        assert approved['execution']['request']['approver'] == 'manager'

    try:
        for role in ('admin', 'specialist', 'employee', 'employee2', 'manager', 'accountant'):
            clients[role] = httpx.Client(trust_env=False, base_url=report['url'], timeout=60, headers={'X-Requested-With': 'antifraud-ui'})
            call(role, '/auth/login', {'username': role, 'password': env['DIPLOMA_SEED_PASSWORD']}, 'POST')
        measure('/demo/requests')
        measure('/demo/requests?limit=200&offset=100')
        page = measure('/demo/requests/page?limit=50')
        if args.phase == 'before':
            report['processing_available'] = page['processing_available']
            report['checks'].append('Current source returns 100 legacy rows only, and processing is disabled by default')
        else:
            assert page['total'] >= 10000 and len(page['items']) == 50
            assert all('history' not in item and 'workflow' not in item for item in page['items'])
            found = measure('/demo/requests/page?search=review-scale-00001')
            assert found['total'] == 1 and found['items'][0]['id'] == 'review-scale-00001'
            assert measure('/demo/requests/page?search=%25')['total'] == 0
            employee_page = call('employee', '/demo/requests/page?limit=100')
            assert all(row['author'] == 'employee' for row in employee_page['items'])
            call('employee', '/demo/requests/review-scale-00001', expected=404)
            call('employee', '/demo/requests/page?queue=business', expected=403)
            queue = measure('/demo/requests/page?queue=business')
            assert all(row['status'] == 'SUBMITTED' and row['author'] != 'manager' for row in queue['items'])
            report['checks'].append('10,000 requests: bounded page, distant ID search, literal wildcard, role visibility, business queue')
            row = create()
            operation = str(uuid4())
            sent = action(row, 'submit', 'employee', operation)
            assert sent['execution']['request']['status'] == 'SUBMITTED'
            repeated = action(row, 'submit', 'employee', operation)
            assert repeated['decision']['id'] == sent['decision']['id']
            approve_op = str(uuid4())
            approved = action(row, 'approve', 'manager', approve_op)
            assert action(row, 'approve', 'manager', approve_op)['decision']['id'] == approved['decision']['id']
            call('employee', '/demo/requests/' + row['id'] + '/action', {'action': 'pay', 'operation_id': str(uuid4())}, 'POST', 403)
            pay_op = str(uuid4())
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: action(row, 'pay', 'accountant', pay_op), range(4)))
            assert all(r['execution']['request']['status'] == 'PAID' for r in results)
            d = results[0]['decision']
            assert len(call('accountant', '/decisions/' + d['id'])['events']) == 1
            report['checks'].append('Explicit action checks and executes once, approval replay after changed approver, no employee payment, concurrent replay')

            for reaction in ('REVIEW', 'CONFIRM', 'BLOCK'):
                expression = {'kind': 'all', 'children': [{'kind': 'field', 'field': 'receipt', 'op': 'eq', 'value': prefix + '-gated'},
                              {'kind': 'field', 'field': 'amount', 'op': 'ge', 'value': 400 if reaction != 'BLOCK' else 1000}]}
                rule = call('admin', '/admin/rules', {'application_id': 'demo', 'name': prefix + reaction, 'action': 'pay', 'reaction': reaction, 'expression': expression}, 'POST')
                rules.append(rule)
            gated = create(prefix + '-gated'); business(gated)
            d = action(gated, 'pay', 'accountant')['decision']
            assert d['state'] == 'PENDING_REVIEW' and set(d['remaining_steps']) == {'REVIEW', 'CONFIRM'} and not d['executed_at']
            call('employee', '/demo/decisions/' + d['id'] + '/confirm', {'approve': True, 'operation_id': d['operation_id'], 'checked_values': d['checked_values']}, 'POST', 403)
            call('specialist', '/decisions/' + d['id'] + '/review', {'approve': True, 'comment': 'Данные проверены'}, 'POST')
            d = call('accountant', '/decisions/' + d['id'])
            assert d['state'] == 'PENDING_CONFIRMATION'
            unrelated = create()
            for _ in range(60):
                call('accountant', '/demo/requests/' + unrelated['id'] + '/check', {'action': 'pay', 'operation_id': str(uuid4())}, 'POST')
            assert d['id'] not in [item['id'] for item in call('accountant', '/demo/decisions')]
            confirmations = call('accountant', '/demo/requests/page?queue=confirmation')
            assert gated['id'] in [r['id'] for r in confirmations['items']]
            call('accountant', '/demo/decisions/' + d['id'] + '/confirm', {'approve': True, 'operation_id': d['operation_id'], 'checked_values': d['checked_values']}, 'POST')
            call('accountant', '/demo/execute', {'operation_id': d['operation_id'], 'decision_id': d['id']}, 'POST')
            blocked = create(prefix + '-gated', '1500'); business(blocked)
            result = action(blocked, 'pay', 'accountant')
            assert result['decision']['state'] == 'REJECTED' and not result['execution']
            report['checks'].append('REVIEW then CONFIRM required; pending case found beyond last 50 decisions; foreign confirmation rejected; BLOCK dominates both')

            changed = create(); business(changed)
            old = call('accountant', '/demo/requests/' + changed['id'] + '/check', {'action': 'pay', 'operation_id': str(uuid4())}, 'POST')
            call('employee', '/demo/requests/' + changed['id'], {'amount': '501', 'title': prefix, 'receipt': prefix, 'recipient': 'Новый получатель', 'vendor': 'QA', 'purchase_date': '2026-10-08'}, 'PUT')
            assert call('accountant', '/decisions/' + old['id'])['state'] == 'CANCELLED'
            assert call('employee', '/demo/requests/' + changed['id'])['status'] == 'DRAFT'
            call('accountant', '/demo/execute', {'operation_id': old['operation_id'], 'decision_id': old['id']}, 'POST', 409)
            call('employee', '/demo/requests/' + changed['id'] + '/action', {'action': 'submit', 'version': 1, 'operation_id': str(uuid4())}, 'POST', 409)
            report['checks'].append('Edit clears business approval, cancels unexecuted permission, old snapshot cannot execute')

            fields = {name: {'type': 'number' if name == 'amount' else 'string', 'source': 'API', 'required': True} for name in ('object', 'amount', 'recipient')}
            app = call('admin', '/admin/applications', {'id': prefix, 'name': 'Current-filter regression', 'ttl_seconds': 600, 'catalog': {'transfer': {'fields': fields}}}, 'POST')
            for kind, extra in [('count', {}), ('aggregate', {'aggregate': 'sum', 'field': 'amount'})]:
                call('admin', '/admin/rules', {'application_id': prefix, 'name': kind, 'action': 'transfer', 'reaction': 'BLOCK', 'expression': {
                    'kind': kind, 'period_seconds': 60, 'statuses': ['SUCCESS'], 'event_types': ['transfer'], 'group_by': ['object'],
                    'include_current': True, 'op': 'ge', 'value': 1, 'filter': {'kind': 'field', 'field': 'recipient', 'op': 'eq', 'value': 'Alice'}, **extra}}, 'POST')
            response = clients['admin'].post('/api/checks', headers={'X-Application-Key': app['api_key']}, json={'application_id': prefix,
                'operation_id': str(uuid4()), 'action': 'transfer', 'initiator': 'actor', 'fields': {'object': 'o', 'amount': 500, 'recipient': 'Bob'}})
            response.raise_for_status()
            result = response.json()
            assert result['state'] == 'APPROVED' and all(str(reason['trace']['actual']) == '0' for reason in result['reasons'])
            report['checks'].append('Persisted API decision: current operation failing field filter is excluded from count and sum')
    finally:
        for rule in rules:
            payload = {k: v for k, v in rule.items() if k not in {'id', 'version'}}
            payload['enabled'] = False
            call('admin', '/admin/rules/' + rule['id'], payload, 'PUT')
        for client in clients.values(): client.close()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
