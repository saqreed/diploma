"""Measure only the supported DB connector, inside the runtime container."""
import asyncio
import json
import sys
from statistics import mean
from time import perf_counter

from app.models import Source
from app.runtime import antifraud_sessions
from app.sources import read_source
from sqlalchemy import select


async def main(application_id, record_key):
    assert application_id.startswith('qa-db-')
    async with antifraud_sessions()() as session:
        source = await session.get(Source, application_id)
    assert source is not None
    # Includes connection, permission checks, metadata and the actual SELECT;
    # the connector deliberately disposes its source engine after every read.
    latencies = []
    for _ in range(50):
        started = perf_counter()
        values = await read_source(source, record_key)
        assert len(values) == 2
        latencies.append(perf_counter() - started)
    print(json.dumps({'application_id': application_id, 'samples': len(latencies), 'field_count': 2,
                      'source': 'PostgreSQL in local Compose network', 'measurement': 'read_source only',
                      'includes_connection_permissions_metadata_select': True,
                      'mean_seconds': round(mean(latencies), 4), 'p95_seconds': round(sorted(latencies)[47], 4),
                      'max_seconds': round(max(latencies), 4)}))


asyncio.run(main(sys.argv[1], sys.argv[2]))
