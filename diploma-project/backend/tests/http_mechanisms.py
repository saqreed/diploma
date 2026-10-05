"""All rule mechanisms through real HTTP and persisted event history; educational fixtures only."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx2 as httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values('../.env')
    prefix = 'qa-rules-' + str(uuid4())[:8]
    client = httpx.Client(trust_env=False, base_url='http://127.0.0.1:8000', timeout=20, headers={'X-Requested-With': 'antifraud-ui'})
    def request(path, body=None, method='POST', headers=None, expected=200):
        response = client.request(method, '/api' + path, json=body, headers=headers)
        assert response.status_code == expected, f'{path}: {response.status_code}'
        return response.json()
    request('/auth/login', {'username': 'admin', 'password': env['DIPLOMA_SEED_PASSWORD']})
    fields = {n: {'type': 'number' if n == 'amount' else 'string', 'required': True, 'source': 'API'} for n in ('object', 'amount', 'recipient')}
    catalog = {action: {'fields': fields} for action in ('create', 'approve', 'pay')}
    def history(kind, **extra):
        return {'kind': kind, 'period_seconds': 120, 'group_by': ['object'], 'event_types': ['pay'], 'statuses': ['SUCCESS'], **extra}
    cases = [
        ('field', {'kind': 'field', 'field': 'amount', 'op': 'gt', 'value': 100}, [], {'amount': 101}, {'amount': 100}),
        ('duplicate', history('duplicate', match_fields=['amount', 'recipient']), [('pay', 100, 'Alice')], {}, {'amount': 200}),
        ('count', history('count', include_current=True, op='ge', value=2), [('pay', 100, 'Alice')], {}, {'object': 'o2'}),
        ('sum', history('aggregate', field='amount', aggregate='sum', include_current=True, op='ge', value=150), [('pay', 100, 'Alice')], {}, {'amount': 49}),
        ('unique', history('aggregate', field='recipient', aggregate='unique', include_current=True, op='ge', value=2), [('pay', 100, 'Alice')], {'recipient': 'Bob'}, {}),
        ('sequence', history('sequence', event_types=['create', 'approve'], sequence=['create', 'approve']), [('create', 100, 'Alice'), ('approve', 100, 'Alice')], {}, {'object': 'o2'}),
        ('previous', history('previous', event_types=['approve'], match_fields=['amount', 'recipient']), [('approve', 100, 'Alice')], {'amount': 101}, {}),
        ('related', history('related', field='amount', right_field='amount', op='gt'), [('pay', 100, 'Alice')], {'amount': 101}, {'amount': 100}),
        ('novelty', history('novelty', field='recipient'), [('pay', 100, 'Alice')], {'recipient': 'Bob'}, {}),
    ]
    apps = []
    try:
        for index, (name, expression, events, yes, no) in enumerate(cases):
            app_id = prefix + '-' + str(index)
            app = request('/admin/applications', {'id': app_id, 'name': 'QA ' + name, 'ttl_seconds': 600, 'catalog': catalog})
            key = {'X-Application-Key': app['api_key']}
            apps.append(app_id)
            for i, (action, amount, recipient) in enumerate(events):
                request('/events', {'application_id': app_id, 'event_id': str(i), 'event_at': (datetime.now(timezone.utc) - timedelta(seconds=30 - i)).isoformat(),
                                  'action': action, 'actor': 'actor', 'status': 'SUCCESS', 'fields': {'object': 'o1', 'amount': amount, 'recipient': recipient}}, headers=key)
            rule = request('/admin/rules', {'application_id': app_id, 'name': name, 'action': 'pay', 'expression': expression, 'reaction': 'BLOCK'})
            for override, expected in ((yes, 'REJECTED'), (no, 'APPROVED')):
                d = request('/checks', {'application_id': app_id, 'operation_id': str(uuid4()), 'action': 'pay', 'initiator': 'actor', 'fields': {'object': 'o1', 'amount': 100, 'recipient': 'Alice', **override}}, headers=key)
                assert d['state'] == expected, name + ': ' + d['state']
                assert d['reasons'][0]['trace'] and d['reasons'][0]['expression']
            # Editing the rule does not overwrite earlier explanations.
            saved = d['reasons']
            request('/admin/rules/' + rule['id'], {**{k: v for k, v in rule.items() if k not in {'id', 'version'}}, 'enabled': False}, 'PUT')
            assert request('/checks/' + d['id'], method='GET', headers=key)['reasons'] == saved
            print('PASS:', name, 'trigger/non-trigger, persisted explanation')

        app_id = prefix + '-priority'
        app = request('/admin/applications', {'id': app_id, 'name': 'QA reactions', 'ttl_seconds': 600, 'catalog': catalog})
        key = {'X-Application-Key': app['api_key']}
        expression = {'kind': 'field', 'field': 'amount', 'op': 'ge', 'value': 100}
        rule_ids = []
        for reaction in ('LOG', 'CONFIRM', 'REVIEW', 'BLOCK'):
            rule_ids.append(request('/admin/rules', {'application_id': app_id, 'name': reaction, 'action': 'pay', 'expression': expression, 'reaction': reaction}))
        payload = {'application_id': app_id, 'operation_id': str(uuid4()), 'action': 'pay', 'initiator': 'actor', 'fields': {'object': 'o1', 'amount': 100, 'recipient': 'Alice'}}
        d = request('/checks', payload, headers=key)
        assert d['state'] == 'REJECTED' and sum(r['matched'] for r in d['reasons']) == 4
        with httpx.Client(trust_env=False, base_url='http://127.0.0.1:8000', headers={'X-Requested-With': 'antifraud-ui'}) as specialist:
            specialist.post('/api/auth/login', json={'username': 'specialist', 'password': env['DIPLOMA_SEED_PASSWORD']}).raise_for_status()
            assert specialist.post('/api/decisions/' + d['id'] + '/review', json={'approve': True}).status_code == 409
        for mask in range(16):
            active = {rule['reaction'] for i, rule in enumerate(rule_ids) if mask & (1 << i)}
            for rule in rule_ids:
                request('/admin/rules/' + rule['id'], {**{k: v for k, v in rule.items() if k not in {'id', 'version'}}, 'enabled': rule['reaction'] in active}, 'PUT')
            combination = request('/checks', {**payload, 'operation_id': str(uuid4())}, headers=key)
            expected = 'REJECTED' if 'BLOCK' in active else 'PENDING_REVIEW' if 'REVIEW' in active else 'PENDING_CONFIRMATION' if 'CONFIRM' in active else 'APPROVED'
            assert combination['state'] == expected
            assert {r['reaction'] for r in combination['reasons'] if r['matched']} == active
            assert combination['remaining_steps'] == [step for step in ('REVIEW', 'CONFIRM') if step in active]
        print('PASS: all 16 reaction combinations; specialist cannot override rule prohibition')
        for rule in rule_ids:
            request('/admin/rules/' + rule['id'], {**{k: v for k, v in rule.items() if k not in {'id', 'version'}}, 'enabled': rule['reaction'] == 'CONFIRM'}, 'PUT')
        d = request('/checks', {**payload, 'operation_id': str(uuid4())}, headers=key)
        assert d['state'] == 'PENDING_CONFIRMATION'
        confirmation = {'approve': False, 'initiator': 'actor', 'operation_id': d['operation_id'], 'checked_values': d['checked_values']}
        result = request('/checks/' + d['id'] + '/confirmation', confirmation, headers=key)
        assert result['state'] == 'CANCELLED'
        print('PASS: BLOCK priority, all reasons retained, initiator refusal')

        watch = request('/admin/watchlists', {'application_id': app_id, 'name': 'QA recipients', 'values': ['Alice']})
        exception = {'kind': 'field', 'field': 'object', 'op': 'eq', 'value': 'skip'}
        r = request('/admin/rules', {'application_id': app_id, 'name': 'QA list+exception', 'action': 'pay', 'reaction': 'BLOCK', 'expression': {'kind': 'field', 'field': 'recipient', 'op': 'in', 'list_id': watch['id']}, 'exception': exception})
        excluded = request('/checks', {**payload, 'operation_id': str(uuid4()), 'fields': {**payload['fields'], 'object': 'skip', 'amount': 0}}, headers=key)
        assert excluded['state'] == 'APPROVED' and next(x for x in excluded['reasons'] if x['rule_id'] == r['id'])['exception_trace']['matched']
        request('/admin/watchlists/' + watch['id'], {'name': 'QA updated', 'values': ['Bob']}, 'PUT')
        request('/admin/watchlists/' + watch['id'], method='DELETE', expected=422)
        print('PASS: watchlist create/edit, exception explanation, referenced-list guard')
        # Related objects can be supplied through an allowed field source, without historical events.
        related = {'kind': 'related', 'relation': 'current', 'field': 'object', 'right_field': 'recipient', 'op': 'eq'}
        request('/admin/rules', {'application_id': app_id, 'name': 'QA related object', 'action': 'pay', 'reaction': 'BLOCK', 'expression': related})
        result = request('/checks', {**payload, 'operation_id': str(uuid4()), 'fields': {'object': 'Same', 'recipient': 'Same', 'amount': 0}}, headers=key)
        assert result['state'] == 'REJECTED'
        print('PASS: related object fields comparison')
    finally:
        client.close()
    print('All persisted mechanism checks passed:', prefix)


if __name__ == '__main__':
    main()
