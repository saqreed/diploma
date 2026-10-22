"""Restart-safe delivery from the durable demo outbox; no in-memory event queue."""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from app.config import Environment


async def dispatch(deliver, interval: float, maximum: float):
    delay = interval
    while True:
        # Also on startup: committed rows survive a process interruption.
        try:
            result = await deliver()
            if result["delivered"]:
                logging.getLogger("antifraud").info("outbox_delivered count=%s", result["delivered"])
            delay = interval
        except Exception as error:
            # Never serialize a driver/HTTP error, payload or credentials.
            logging.getLogger("antifraud").warning("outbox_retry stage=event_delivery error_type=%s retry_seconds=%s", type(error).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(maximum, delay * 2)
            continue
        await asyncio.sleep(delay)


def delivery_lifespan(settings):
    @asynccontextmanager
    async def lifespan(application):
        from app.demo import deliver_outbox

        task = None
        if settings.outbox_dispatch_enabled and settings.environment != Environment.TESTING:
            task = asyncio.create_task(dispatch(deliver_outbox, settings.outbox_interval_seconds, settings.outbox_max_retry_seconds), name="demo-outbox")
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task  # cancellation rolls back any unacknowledged batch
    return lifespan
