"""Cancellation before dispatch must not invoke the queued work."""
import asyncio
import contextlib
import uuid

import pytest

from core import job_store
from core.db import init_db
from core.tasks import TaskManager


@pytest.mark.parametrize("kind", ["sync", "coroutine", "stream"])
def test_cancelled_pending_task_never_executes_and_persists_cancelled(kind):
    init_db()
    manager = TaskManager()
    task_id = uuid.uuid4().hex
    calls = []

    def sync():
        calls.append("executed")

    async def coroutine():
        calls.append("executed")

    async def stream():
        calls.append("executed")
        yield 'data: {"type":"progress"}\n\n'

    async def scenario():
        await manager.add_task(task_id, "test", locals_work[kind])
        listener = asyncio.Queue()
        await manager.add_listener(task_id, listener)
        assert manager.cancel_task(task_id)
        worker = asyncio.create_task(manager.worker())
        try:
            await asyncio.wait_for(manager.queue.join(), 1)
            frames = []
            while not listener.empty():
                frames.append(listener.get_nowait())
            return frames
        finally:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

    locals_work = {"sync": sync, "coroutine": coroutine, "stream": stream}
    frames = asyncio.run(scenario())
    assert calls == []
    assert manager.active_tasks[task_id]["status"] == "cancelled"
    assert job_store.get(task_id)["status"] == "cancelled"
    assert frames == ['data: {"type": "cancelled"}\n\n', None]


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_cancellation_does_not_change_a_terminal_task(status):
    manager = TaskManager()
    manager.active_tasks["finished"] = {"status": status, "cancelled": False}
    assert manager.cancel_task("finished") is False
    assert manager.active_tasks["finished"] == {"status": status, "cancelled": False}
