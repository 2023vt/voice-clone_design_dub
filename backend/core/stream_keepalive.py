"""Keep long-running HTTP streams from going byte-silent (#2108 class).

A streamed render can spend minutes on one step — a CPU host synthesizing a
600-character chunk, a long-form chapter, the final assembly — without a
byte to send. Reverse proxies and tunnels sever such a response even though
the render behind it is healthy: Cloudflare answers 524 when no body byte
arrives within ~100 s, nginx/Apache idle timeouts and the desktop webview do
the same. The render then finishes into History while the user sees a failure.

``with_keepalive`` wraps any async stream and interleaves a protocol-neutral
keepalive frame whenever the wrapped stream has been silent for ``interval``
seconds, so every byte-silent step — present or future — is covered by the
one wrapper instead of per-await pings.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
from collections.abc import AsyncIterable, AsyncIterator
from typing import TypeVar

T = TypeVar("T")

#: Seconds of stream silence before a keepalive frame goes out. Well under the
#: shortest common proxy timeout (Cloudflare's ~100 s). ``0`` disables.
def _env_interval(default: float = 15.0) -> float:
    try:
        return float(os.environ.get("OMNIVOICE_STREAM_KEEPALIVE_S", "") or default)
    except ValueError:  # a typo must not stop the backend from starting
        return default


STREAM_KEEPALIVE_S = _env_interval()

#: NDJSON: a blank line. Every NDJSON consumer skips empty lines.
NDJSON_KEEPALIVE = b"\n"
#: SSE: a comment frame, ignored by EventSource and every spec-compliant parser.
SSE_KEEPALIVE = ": keepalive\n\n"

#: Headers that stop intermediaries from buffering or recompressing a stream
#: (which would hold the keepalive back and defeat it).
NO_BUFFER_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


async def with_keepalive(
    source: AsyncIterable[T], ping: T, interval: float | None = None,
) -> AsyncIterator[T]:
    """Yield ``source``'s items, plus ``ping`` after each ``interval`` of silence.

    Each step of ``source`` runs in a task sharing ONE context, so context
    variables behave exactly as they would under a plain ``async for``.
    Closing or cancelling this stream cancels the in-flight step and closes
    ``source`` before returning, preserving prompt-finalization semantics
    (#2536) for wrapped generators.
    """
    interval = STREAM_KEEPALIVE_S if interval is None else interval
    if interval <= 0:
        async for item in source:
            yield item
        return

    it = source.__aiter__()
    ctx = contextvars.copy_context()

    async def _step():
        return await it.__anext__()

    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.get_running_loop().create_task(_step(), context=ctx)
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ping
                continue
            step, pending = pending, None
            try:
                item = step.result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(BaseException):
                await pending
        aclose = getattr(it, "aclose", None)
        if aclose is not None:
            await aclose()
