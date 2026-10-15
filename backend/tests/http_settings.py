"""Persisted templates, field validation, journal filters and event pagination."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import os
import httpx2 as httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values('../.env')
    prefix = 'qa-settings-' + str(uuid4())[:8]
    with httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=20,
                      headers={'X-Requested-With': 'antifraud-ui'}) as admin:
        def call(path, body=None, method='POST', key=None, expected=200):
            response = admin.request(method, '/api' + path, json=body, headers={'X-Application-Key': key} if key else None)
            assert response.status_code == expected, f'{path}: HTTP {response.status_code}'
            return response.json()
        call('/auth/login', {'username': 'admin', 'password': env['DIPLOMA_SEED_PASSWORD']})
        fields = {'object': {'type': 'string', 'source': 'API', 'required': True}, 'amount': {'type': 'number', 'source': 'API', 'required': True}}
        catalog = {'transfer': {'fields': fields}}
        app = call('/admin/applications', {'id': prefix, 'name': 'QA настройки', 'ttl_seconds': 600, 'catalog': catalog})
        key = app['api_key']
        watch = call('/admin/watchlists', {'application_id': prefix, 'name': 'Суммы', 'values': [100]})
        base = {'application_id': prefix, 'name': 'QA template', 'action': 'transfer', 'reaction': 'LOG',
                'expression': {'kind': 'field', 'field': 'amount', 'op': 'in', 'list_id': watch['id']}}
        template = call('/admin/templates', base)
        copy = call('/admin/rules', {**base, 'name': 'Самостоятельная копия'})
        call('/admin/templates/' + template['id'], {**base, 'expression': {'kind': 'field', 'field': 'amount', 'op': 'gt', 'value': 1000}}, 'PUT')
        saved = call('/admin/rules?application_id=' + prefix, method='GET')
        assert saved[0]['expression'] == copy['expression']
        call('/admin/watchlists/' + watch['id'], {'name': 'Неверный тип', 'values': ['x']}, 'PUT', expected=422)
        call('/admin/watchlists/' + watch['id'], method='DELETE', expected=422)
        call('/admin/templates/' + template['id'], method='DELETE')
        assert all(t['builtin'] for t in call('/admin/templates?application_id=' + prefix, method='GET'))
        invalid = {**base, 'expression': {'kind': 'count', 'period_seconds': 0, 'event_types': ['transfer'], 'statuses': ['SUCCESS'], 'op': 'ge', 'value': 1}}
        call('/admin/rules', invalid, expected=422)
        call('/admin/rules', {**base, 'expression': {'kind': 'field', 'field': 'unknown', 'op': 'eq', 'value': 1}}, expected=422)
        print('PASS: template CRUD, independent copy, list type/reference checks, invalid rule settings')
        count = call('/admin/rules', {**base, 'name': 'История', 'expression': {'kind': 'count', 'period_seconds': 3600,
                     'group_by': ['object'], 'event_types': ['transfer'], 'statuses': ['SUCCESS'], 'op': 'ge', 'value': 150}})
        at = datetime.now(timezone.utc) - timedelta(seconds=300)
        for i in range(150):
            call('/events', {'application_id': prefix, 'event_id': str(i), 'event_at': (at + timedelta(seconds=i)).isoformat(),
                            'action': 'transfer', 'actor': 'actor', 'status': 'SUCCESS', 'fields': {'object': 'one', 'amount': 100}}, key=key)
        same_event = {'application_id': prefix, 'event_id': 'concurrent', 'event_at': at.isoformat(),
                      'action': 'transfer', 'actor': 'actor', 'status': 'SUCCESS', 'fields': {'object': 'parallel', 'amount': 100}}
        same_check = {'application_id': prefix, 'operation_id': str(uuid4()), 'action': 'transfer', 'initiator': 'actor',
                      'fields': {'object': 'parallel', 'amount': 100}}
        with ThreadPoolExecutor(max_workers=4) as pool:
            deliveries = list(pool.map(lambda _: call('/events', same_event, key=key), range(4)))
            checks = list(pool.map(lambda _: call('/checks', same_check, key=key), range(4)))
        assert sum(not event['duplicate'] for event in deliveries) == 1
        assert len({check['id'] for check in checks}) == 1 and len({check['expires_at'] for check in checks}) == 1
        assert next(r for r in checks[0]['reasons'] if r['rule_id'] == count['id'])['trace']['actual'] == 1
        print('PASS: concurrent event and check delivery creates one fact/decision without increasing count or deadline')
        d = call('/checks', {'application_id': prefix, 'operation_id': str(uuid4()), 'action': 'transfer', 'initiator': 'actor',
                            'fields': {'object': 'one', 'amount': 100}}, key=key)
        detail = call('/decisions/' + d['id'], method='GET')
        assert detail['related_events_count'] == 150 and len(detail['related_events']) == 100
        extra = call('/decisions/' + d['id'] + '/related-events?offset=100', method='GET')
        assert len(extra) == 50 and len({e['event_id'] for e in detail['related_events'] + extra}) == 150
        query = '/journal?application_id=' + prefix + '&action=transfer&initiator=actor&state=APPROVED&operation_id=' + d['operation_id']
        assert [r['id'] for r in call(query, method='GET')] == [d['id']]
        assert call(query + '&offset=1', method='GET') == []
        assert call('/journal?application_id=' + prefix + '&state=REJECTED', method='GET') == []
        call('/journal?limit=0', method='GET', expected=422)
        call('/journal?start=2026-10-05T10:00:00', method='GET', expected=422)
        print('PASS: journal combined filters, pagination, saved history events and input boundaries')
        assert count['enabled']


if __name__ == '__main__':
    main()
