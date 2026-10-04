"""Stream committed projection changes; notifications only wake the database reader."""

import asyncio
import sys
from collections.abc import AsyncGenerator

import psycopg
from fastapi import Request
from psycopg_pool import ConnectionPool

from seismic_stream.api.repository import list_changes

CHANNEL = "earthquake_changes"
HEARTBEAT_SECONDS = 15


async def change_stream(
    request: Request, pool: ConnectionPool, *, after: int
) -> AsyncGenerator[str, None]:
    try:
        # Psycopg's async connection cannot run on Windows' default Proactor loop.
        # Poll the same ordered cursor there; Linux uses LISTEN for prompt wakeups.
        if sys.platform == "win32" and isinstance(
            asyncio.get_running_loop(), asyncio.ProactorEventLoop
        ):
            async for frame in _stream_changes(
                request, pool, after=after, listener=None
            ):
                yield frame
            return
        conninfo = pool.conninfo() if callable(pool.conninfo) else pool.conninfo
        async with await psycopg.AsyncConnection.connect(
            conninfo, autocommit=True
        ) as listener:
            # LISTEN must take effect before the first catch-up query.
            await listener.execute(f"LISTEN {CHANNEL}")
            async for frame in _stream_changes(
                request, pool, after=after, listener=listener
            ):
                yield frame
    except psycopg.Error:
        yield 'event: error\ndata: {"message":"Live updates unavailable"}\n\n'


async def _stream_changes(
    request: Request,
    pool: ConnectionPool,
    *,
    after: int,
    listener: psycopg.AsyncConnection[tuple[object, ...]] | None,
) -> AsyncGenerator[str, None]:
    cursor = after
    yield ": connected\n\n"
    while not await request.is_disconnected():
        page = await asyncio.to_thread(list_changes, pool, after=cursor, limit=100)
        for change in page.items:
            cursor = change.cursor
            yield (
                f"id: {cursor}\nevent: earthquake\ndata: {change.model_dump_json()}\n\n"
            )
        if page.next_cursor is not None:
            continue
        if await request.is_disconnected():
            break
        if listener is None:
            await asyncio.sleep(2)
            continue
        notified = False
        async for _ in listener.notifies(timeout=HEARTBEAT_SECONDS, stop_after=1):
            notified = True
        if not notified:
            yield ": heartbeat\n\n"
