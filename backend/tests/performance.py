"""Explicit local load experiment: 10,000 persisted API events, 20 rules, 5 rps, 300 seconds.

Creates an isolated QA application. Output contains measurements, never API keys/passwords.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from statistics import mean
from time import perf_counter, sleep
from uuid import uuid4

import os
import httpx2 as httpx
from dotenv import dotenv_values


def percentile(values, fraction):
    return sorted(values)[max(0, int(len(values) * fraction + 0.999999) - 1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=300)
    parser.add_argument('--output', required=True)
    parser.add_argument('--fixture-cache', help='Private local cache; contains an application key. Never publish it.')
    args = parser.parse_args()
    env = dotenv_values('../.env')
    prefix = 'qa-load-' + str(uuid4())[:8]
    client = httpx.Client(trust_env=False, base_url=os.environ.get('DIPLOMA_TEST_URL', 'http://127.0.0.1:8000'), timeout=30, headers={'X-Requested-With': 'antifraud-ui'}, limits=httpx.Limits(max_connections=20))
    def post(path, payload, key=None):
        response = client.post('/api' + path, json=payload, headers={'X-Application-Key': key} if key else None)
        if response.status_code != 200:
            raise RuntimeError(f'{path}: HTTP {response.status_code}')
        return response.json()
    try:
        post('/auth/login', {'username': 'admin', 'password': env['DIPLOMA_SEED_PASSWORD']})
        cache = Path(args.fixture_cache) if args.fixture_cache else None
        cached = json.loads(cache.read_text(encoding='utf-8')) if cache and cache.exists() else None
        fields = {n: {'type': 'number' if n == 'amount' else 'string', 'source': 'API', 'required': True} for n in ('object', 'amount', 'recipient')}
        catalog = {action: {'fields': fields} for action in ('create', 'approve', 'pay')}
        if cached:
            prefix, key = cached['application_id'], cached['api_key']
        else:
            app = post('/admin/applications', {'id': prefix, 'name': 'QA нагрузка', 'ttl_seconds': 600, 'catalog': catalog})
            key = app['api_key']
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({'application_id': prefix, 'api_key': key, 'ready': False}), encoding='utf-8')
        at = datetime.now(timezone.utc) - timedelta(seconds=3500)
        def seed(i):
            post('/events', {'application_id': prefix, 'event_id': str(i), 'event_at': (at + timedelta(milliseconds=i * 250)).isoformat(),
                            'action': ('create', 'approve', 'pay')[i % 3], 'actor': 'benchmark', 'status': 'FAILED' if i % 7 == 0 else 'SUCCESS',
                            'fields': {'object': 'object-' + str(i % 20), 'amount': i % 100, 'recipient': 'recipient-' + str(i % 17)}}, key)
        if not cached or not cached.get('ready', False):
            with ThreadPoolExecutor(max_workers=10) as pool:
                for n, future in enumerate(as_completed([pool.submit(seed, i) for i in range(10000)]), 1):
                    future.result()
                    if n % 2000 == 0: print('Seeded events:', n, flush=True)
        h = {'period_seconds': 86400, 'group_by': ['object'], 'event_types': ['create', 'approve', 'pay'], 'statuses': ['SUCCESS']}
        nodes = [
            {'kind': 'field', 'field': 'amount', 'op': 'gt', 'value': 10000},
            {**h, 'kind': 'duplicate', 'match_fields': ['amount', 'recipient']},
            {**h, 'kind': 'count', 'op': 'ge', 'value': 400, 'include_current': True},
            {**h, 'kind': 'aggregate', 'aggregate': 'sum', 'field': 'amount', 'op': 'ge', 'value': 10000, 'include_current': True},
            {**h, 'kind': 'aggregate', 'aggregate': 'unique', 'field': 'recipient', 'op': 'ge', 'value': 15, 'include_current': True},
            {**h, 'kind': 'sequence', 'sequence': ['create', 'approve', 'pay']},
            {**h, 'kind': 'previous', 'event_types': ['approve'], 'match_fields': ['amount', 'recipient']},
            {**h, 'kind': 'related', 'field': 'amount', 'right_field': 'amount', 'op': 'gt', 'event_types': ['pay']},
            {**h, 'kind': 'novelty', 'field': 'recipient'},
            {'kind': 'all', 'children': [{**h, 'kind': 'count', 'op': 'ge', 'value': 100}, {'kind': 'field', 'field': 'amount', 'op': 'ge', 'value': 0}]},
        ]
        if not cached or not cached.get('ready', False):
            existing_rules = client.get('/api/admin/rules', params={'application_id': prefix}).json()
            for i in range(20):
                if not any(r['name'] == 'Benchmark ' + str(i) for r in existing_rules):
                    post('/admin/rules', {'application_id': prefix, 'name': 'Benchmark ' + str(i), 'action': 'pay', 'expression': nodes[i % len(nodes)], 'reaction': 'LOG'})
            if cache:
                cache.write_text(json.dumps({'application_id': prefix, 'api_key': key, 'ready': True}), encoding='utf-8')
        namespace = str(uuid4())[:8]
        payload = {'application_id': prefix, 'action': 'pay', 'initiator': 'benchmark', 'fields': {'object': 'object-0', 'amount': 100, 'recipient': 'new-recipient'}}
        post('/checks', {**payload, 'operation_id': namespace + '-warmup'}, key)
        print('Measurement started: 10000 events, 20 mixed rules, 5 rps, seconds:', args.duration, flush=True)
        latencies, failures = [], []
        began = perf_counter()
        def measured(i, scheduled):
            try:
                result = post('/checks', {**payload, 'operation_id': namespace + '-measure-' + str(i)}, key)
                if len(result['reasons']) != 20 or result['state'] != 'APPROVED': raise RuntimeError('Incomplete evaluation')
                return perf_counter() - scheduled, None
            except Exception as error:
                return perf_counter() - scheduled, type(error).__name__
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = []
            for i in range(args.duration * 5):
                scheduled = began + i / 5
                if scheduled > perf_counter(): sleep(scheduled - perf_counter())
                futures.append(pool.submit(measured, i, scheduled))
                if i and i % 300 == 0: print('Scheduled requests:', i, flush=True)
            for future in futures:
                latency, error = future.result()
                latencies.append(latency)
                if error: failures.append(error)
        elapsed = perf_counter() - began
        report = {'application_id': prefix, 'events': 10000, 'rules': 20, 'requested_rps': 5, 'duration_seconds': args.duration,
                  'elapsed_seconds': round(elapsed, 4), 'requests': len(latencies), 'failures': len(failures),
                  'mean_seconds': round(mean(latencies), 4), 'p95_seconds': round(percentile(latencies, .95), 4),
                  'max_seconds': round(max(latencies), 4), 'within_one_second_percent': round(100 * sum(v <= 1 for v in latencies) / len(latencies), 2),
                  'external_source': False, 'latency_includes_scheduler_queue': True, 'achieved_rps': round(len(latencies) / elapsed, 3), 'group_count': 20, 'rule_kinds': [n['kind'] for n in nodes]}
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
