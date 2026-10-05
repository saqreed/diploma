"""Local diagnostics on a QA application; reports call costs without field values or credentials."""
import asyncio
import cProfile
import pstats
import sys
from time import perf_counter
from uuid import uuid4

from app.contracts import CheckInput
from app.decisions import make_check
from app.runtime import antifraud_sessions


async def main():
    app_id = sys.argv[1]
    assert app_id.startswith('qa-load-')
    profiler = cProfile.Profile()
    start = perf_counter()
    profiler.enable()
    async with antifraud_sessions().begin() as session:
        result = await make_check(session, CheckInput(application_id=app_id, operation_id='profile-' + str(uuid4()), action='pay', initiator='benchmark', fields={'object': 'object-0', 'amount': 100, 'recipient': 'new-recipient'}))
    profiler.disable()
    print('elapsed_seconds:', perf_counter() - start, 'state:', result['state'], 'rules:', len(result['reasons']))
    pstats.Stats(profiler).strip_dirs().sort_stats('cumulative').print_stats(20)


if __name__ == '__main__':
    asyncio.run(main())
