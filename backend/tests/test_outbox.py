"""Delivery scheduling is bounded, resets after recovery, and cancels cleanly."""
import asyncio

from app.outbox import dispatch


def test_retry_backoff_recovers_and_cancellation_stops_dispatch(monkeypatch):
    delays, calls = [], []

    async def deliver():
        calls.append(len(calls))
        if len(calls) <= 5:
            raise ConnectionError("must not appear in logs")
        return {"delivered": 1}

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 7:
            raise asyncio.CancelledError()

    monkeypatch.setattr("app.outbox.asyncio.sleep", sleep)

    async def run():
        try:
            await dispatch(deliver, 2, 8)
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert delays == [2, 4, 8, 8, 8, 2, 2]
    assert len(calls) == 7
