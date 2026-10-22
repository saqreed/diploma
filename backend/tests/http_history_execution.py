"""Real PostgreSQL/HTTP regressions for final history admission across operations.

Run only on the isolated review or CI stand, with a second backend whose
DIPLOMA_ANTIFRAUD_URL=http://127.0.0.1:1 deliberately prevents outbox delivery.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import os
import subprocess
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import httpx2 as httpx
from dotenv import dotenv_values


def main():
    url = os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:28000')
    ci = os.environ.get('COMPOSE_PROJECT_NAME', '').startswith('diploma-ci-')
    assert url == 'http://127.0.0.1:28000' or ci and url == 'http://127.0.0.1:8000', 'Isolated review or CI only'
    outage = os.environ.get('DIPLOMA_TEST_OUTAGE_URL', 'http://127.0.0.1:28001')
    assert outage == 'http://127.0.0.1:28001', 'Local disposable outage replica only'
    container = os.environ.get('DIPLOMA_TEST_CONTAINER', 'diploma-review-20261008-backend-1')
    env = dotenv_values('../.env')
    prefix = 'qa-history-' + uuid4().hex[:10]
    clients, rules = {}, []
    original_app, holder = None, None

    def call(role, path, body=None, method=None, expected=200):
        response = clients[role].request(method or ('POST' if body is not None else 'GET'), '/api'+path, json=body)
        assert response.status_code == expected, (path, response.status_code, expected)
        return response.json()

    def attempt(row):
        return call('accountant', '/demo/requests/'+row['id']+'/check', dict(action='pay', operation_id=uuid4().hex))

    def perform(decision, role='accountant', expected=200):
        return call(role, '/demo/execute', dict(operation_id=decision['operation_id'], decision_id=decision['id']), expected=expected)

    def prepare(amount, group, code):
        row = call('employee', '/demo/requests', dict(amount=amount, recipient=group, vendor=prefix,
                   receipt=group+'-'+code, purchase_date=date.today().isoformat(), title=group+' '+code, category='other'))
        for action, role in (('submit', 'employee'), ('approve', 'manager')):
            result = call(role, '/demo/requests/'+row['id']+'/action', dict(action=action, operation_id=uuid4().hex, version=row['version']))
            assert result['execution'], (action, result['decision']['state'])
            row = result['execution']['request']
        return row

    def setup(code, second='3500'):
        group = prefix+'-'+code
        baseline = prepare('4000', group, 'baseline')
        perform(attempt(baseline))
        a, b = prepare('3500', group, 'a'), prepare(second, group, 'b')
        expression = dict(kind='aggregate', aggregate='sum', field='amount', op='ge', value=10000,
                          period_seconds=86400, event_types=['pay'], statuses=['SUCCESS'],
                          group_by=['recipient'], include_current=True)
        for reaction in ('REVIEW', 'CONFIRM'):
            rules.append(call('admin', '/admin/rules', dict(application_id='demo', name=group+'-'+reaction,
                          action='pay', expression=expression, reaction=reaction,
                          exception=dict(kind='field', field='recipient', op='ne', value=group))))
        da, db = attempt(a), attempt(b)
        assert da['state'] == db['state'] == 'APPROVED'
        return a, b, da, db

    def cancelled(decision, row, check_replay=True):
        current = call('accountant', '/decisions/'+decision['id'])
        assert current['state'] == 'CANCELLED' and current['executed_at'] is None
        assert current['expires_at'] == decision['expires_at'] and current['reasons'] == decision['reasons']
        assert current['checked_values'] == decision['checked_values'] and current['events'] == []
        assert call('accountant', '/demo/requests/'+row['id'])['status'] == 'APPROVED'
        if check_replay:
            replay = call('accountant', '/demo/requests/'+row['id']+'/check', dict(action='pay', operation_id=decision['operation_id']))
            assert replay['id'] == decision['id'] and replay['state'] == 'CANCELLED' and replay['expires_at'] == decision['expires_at']
        perform(decision, expected=409)

    try:
        for base in (url, outage):
            until = monotonic()+30
            with httpx.Client(base_url=base, trust_env=False, timeout=2) as health:
                while True:
                    try:
                        if health.get('/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    assert monotonic() < until, 'History regression backend did not become healthy'
                    sleep(.2)
        for role in ('admin', 'employee', 'manager', 'accountant', 'specialist', 'outage'):
            clients[role] = httpx.Client(base_url=outage if role == 'outage' else url, trust_env=False, timeout=30,
                                        headers={'X-Requested-With': 'antifraud-ui'}, limits=httpx.Limits(keepalive_expiry=1))
            call(role, '/auth/login', dict(username='accountant' if role == 'outage' else role, password=env['DIPLOMA_SEED_PASSWORD']))

        a, b, da, db = setup('sequential')
        perform(da)
        assert perform(db, expected=409)['code'] == 'history_changed'
        cancelled(db, b)
        fresh = attempt(b)
        assert fresh['state'] == 'PENDING_REVIEW' and fresh['remaining_steps'] == ['REVIEW', 'CONFIRM']
        deadline = fresh['expires_at']
        call('specialist', '/decisions/'+fresh['id']+'/review', dict(approve=True, comment='Regression: current cumulative total reviewed'))
        perform(fresh, expected=409)
        confirmed = call('accountant', '/demo/decisions/'+fresh['id']+'/confirm',
                         dict(approve=True, operation_id=fresh['operation_id'], checked_values=fresh['checked_values']))
        assert confirmed['state'] == 'APPROVED' and confirmed['expires_at'] == deadline
        extra = prepare('500', a['recipient'], 'changed-review-context')
        perform(attempt(extra))  # Allowed 8000 total, but B's reviewed total is now 11500.
        assert perform(confirmed, expected=409)['code'] == 'history_changed'
        cancelled(confirmed, b)
        fresh = attempt(b)
        deadline = fresh['expires_at']
        call('specialist', '/decisions/'+fresh['id']+'/review', dict(approve=True, comment='Regression: changed review context checked again'))
        confirmed = call('accountant', '/demo/decisions/'+fresh['id']+'/confirm',
                         dict(approve=True, operation_id=fresh['operation_id'], checked_values=fresh['checked_values']))
        assert confirmed['expires_at'] == deadline
        saved, replay = perform(confirmed), perform(confirmed)
        assert saved['executed_at'] == replay['executed_at']
        assert len(call('accountant', '/decisions/'+fresh['id'])['events']) == 1
        print('PASS: sequential stale permission and stale completed review cancelled; fresh REVIEW + CONFIRM executes once with unchanged deadlines/explanations')

        a, b, da, db = setup('parallel')
        barrier = Barrier(2)
        def race(decision):
            barrier.wait(timeout=10)
            return clients['accountant'].post('/api/demo/execute', json=dict(operation_id=decision['operation_id'], decision_id=decision['id']))
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(race, (da, db)))
        assert sorted(r.status_code for r in responses) == [200, 409]
        loser = responses.index(next(r for r in responses if r.status_code == 409))
        assert responses[loser].json()['code'] == 'history_changed'
        cancelled((da, db)[loser], (a, b)[loser])
        statuses = [call('accountant', '/demo/requests/'+r['id'])['status'] for r in (a, b)]
        assert sorted(statuses) == ['APPROVED', 'PAID']
        print('PASS: parallel different operations: one payment, one stale permission rejected under the shared lock')

        a, b, da, db = setup('pending')
        saved = perform(da, 'outage')
        assert saved['event_delivery']['pending'] and saved['request']['status'] == 'PAID'
        assert call('accountant', '/decisions/'+da['id'])['events'] == []
        pending_lock = """import asyncio
from sqlalchemy import select
from app.models import Outbox
from app.runtime import demo_sessions
async def run():
    async with demo_sessions().begin() as session:
        row = await session.scalar(select(Outbox).where(Outbox.payload['operation_id'].as_string() == '%s').with_for_update())
        assert row is not None
        print('LOCKED', flush=True)
        await asyncio.sleep(5)
asyncio.run(run())
""" % da['operation_id']  # Generated hex identifier only; not user input.
        holder = subprocess.Popen(['docker', 'exec', container, 'python', '-u', '-c', pending_lock], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        assert holder.stdout.readline().strip() == 'LOCKED'
        assert perform(db, 'outage', 409)['code'] == 'history_changed'
        cancelled(db, b, check_replay=False)
        assert call('accountant', '/decisions/'+da['id'])['events'] == []
        blocked_check = call('accountant', '/demo/requests/'+b['id']+'/check', dict(action='pay', operation_id=uuid4().hex), expected=503)
        assert blocked_check['code'] == 'history_pending'
        assert holder.wait(timeout=10) == 0
        assert perform(da, 'outage')['executed_at'] == saved['executed_at']
        # No manual delivery: a fresh attempt must reach its initial human gates.
        fresh_pending = attempt(b)
        assert fresh_pending['state'] == 'PENDING_REVIEW' and fresh_pending['remaining_steps'] == ['REVIEW', 'CONFIRM']
        assert len(call('accountant', '/decisions/'+da['id'])['events']) == 1
        call('specialist', '/decisions/'+fresh_pending['id']+'/review', dict(approve=True, comment='Regression: previously pending fact reviewed'))
        call('accountant', '/demo/decisions/'+fresh_pending['id']+'/confirm',
             dict(approve=True, operation_id=fresh_pending['operation_id'], checked_values=fresh_pending['checked_values']))
        assert perform(fresh_pending)['request']['status'] == 'PAID'
        assert call('accountant', '/decisions/'+fresh_pending['id'])['expires_at'] == fresh_pending['expires_at']
        print('PASS: undelivered fact blocks stale permission; fresh attempt synchronizes history and completes REVIEW + CONFIRM')

        a, b, da, db = setup('deduplicate', second='1000')
        saved = perform(da, 'outage')
        assert saved['event_delivery']['pending']
        event = dict(application_id='demo', event_id=da['operation_id']+':result', event_at=saved['executed_at'],
                     action='pay', actor='accountant', status='SUCCESS', fields=da['checked_values'],
                     operation_id=da['operation_id'], decision_id=da['id'])
        response = clients['accountant'].post('/api/events', json=event, headers={'X-Application-Key': env['DIPLOMA_DEMO_API_KEY']})
        assert response.status_code == 200
        # The API fact is committed while the outbox acknowledgement is still absent.
        assert len(call('accountant', '/decisions/'+da['id'])['events']) == 1
        assert perform(db, 'outage')['request']['status'] == 'PAID'  # 4000 + 3500 + 1000, never 12000.
        call('outage', '/demo/requests/'+b['id']+'/check', dict(action='pay', operation_id=uuid4().hex), expected=503)
        call('accountant', '/demo/outbox/deliver', {})
        assert len(call('accountant', '/decisions/'+da['id'])['events']) == 1
        print('PASS: API-delivered fact with pending acknowledgement counts once; legitimate 8500 total remains allowed')

        original_app = next(a for a in call('admin', '/admin/applications') if a['id'] == 'demo')
        ready, completed = prepare('500', prefix+'-expiry', 'ready'), prepare('500', prefix+'-expiry', 'completed')
        call('admin', '/admin/applications/demo', {**original_app, 'ttl_seconds': 2}, 'PUT')
        completed_decision = attempt(completed)
        completed_result = perform(completed_decision)
        hold = """import asyncio
from app.decisions import lock_key
from app.runtime import antifraud_sessions
async def run():
    async with antifraud_sessions().begin() as session:
        await lock_key(session, 'history:demo')
        print('LOCKED', flush=True)
        await asyncio.sleep(3)
asyncio.run(run())
"""
        holder = subprocess.Popen(['docker', 'exec', container, 'python', '-u', '-c', hold], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        assert holder.stdout.readline().strip() == 'LOCKED'
        expiring = attempt(ready)  # Checking does not pretend the action has already happened.
        result = perform(expiring, expected=409)
        assert result['code'] == 'decision_expired'
        assert holder.wait(timeout=10) == 0
        expired = call('accountant', '/decisions/'+expiring['id'])
        assert expired['state'] == 'EXPIRED' and expired['expires_at'] == expiring['expires_at'] and not expired['executed_at']
        assert call('accountant', '/demo/requests/'+ready['id'])['status'] == 'APPROVED'
        assert perform(completed_decision)['executed_at'] == completed_result['executed_at']
        print('PASS: expiry while waiting for history lock denies execution; already executed result replays after its deadline')
    finally:
        if holder and holder.poll() is None:
            holder.wait(timeout=10)
        if original_app:
            call('admin', '/admin/applications/demo', original_app, 'PUT')
        for rule in rules:
            call('admin', '/admin/rules/'+rule['id'], {**{k:v for k,v in rule.items() if k not in {'id','version'}}, 'enabled': False}, 'PUT')
        for client in clients.values():
            client.close()


if __name__ == '__main__':
    main()
