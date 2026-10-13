"""Profile reconciliation probes every engine runtime (argostranslate alone is
8-54 s to import), so it must not hold /health at 503 during startup."""
import asyncio
import inspect
import os
import threading
from types import SimpleNamespace

import importlib

import main

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_phase_b_does_not_reconcile_inline():
    assert "reconcile_active_profile" not in inspect.getsource(main._phase_b)
    assert "_reconcile_profile_in_background" in inspect.getsource(main._phase_b)


def test_warmups_wait_for_reconcile_in_background(monkeypatch):
    release = threading.Event()
    finished = []

    def slow_reconcile():
        release.wait(5)
        finished.append(True)
        return {"asr": {}}

    monkeypatch.setattr(importlib.import_module("services.performance_profiles"), "reconcile_active_profile", slow_reconcile)

    async def scenario():
        app = SimpleNamespace(state=SimpleNamespace())
        app.state.profile_reconcile_task = asyncio.create_task(
            main._reconcile_profile_in_background()
        )
        waiter = asyncio.create_task(main._await_profile_reconcile(app))
        await asyncio.sleep(0.05)
        # The caller (startup) got control back while reconcile is still running.
        assert not app.state.profile_reconcile_task.done()
        assert not waiter.done()
        release.set()
        await waiter
        assert finished == [True]

    asyncio.run(scenario())


def test_reconcile_failure_is_non_fatal_and_does_not_block_warmups(monkeypatch):
    def broken():
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(importlib.import_module("services.performance_profiles"), "reconcile_active_profile", broken)

    async def scenario():
        app = SimpleNamespace(state=SimpleNamespace())
        app.state.profile_reconcile_task = asyncio.create_task(
            main._reconcile_profile_in_background()
        )
        await main._await_profile_reconcile(app)
        assert app.state.profile_reconcile_task.exception() is None

    asyncio.run(scenario())


def test_await_without_a_task_returns_immediately():
    asyncio.run(main._await_profile_reconcile(SimpleNamespace(state=SimpleNamespace())))


def test_inventory_probe_does_not_import_engine_runtimes():
    """argostranslate takes 8-54 s to import; the inventory only needs to know
    whether it is installed."""
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, 'backend');"
        "from services import translation_engines as t;"
        "t.is_ready('argos', import_check=False);"
        "sys.exit(1 if 'argostranslate.translate' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], cwd=_REPO).returncode == 0


def test_import_check_default_still_imports(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "importlib.import_module", lambda name: seen.append(name) or object(),
    )
    from services import translation_engines as t

    entry = {"id": "x", "probe_module": "somepkg.sub"}
    assert t._probe(entry) == (True, None)
    assert seen == ["somepkg.sub"]
    assert t._probe({"id": "x", "probe_module": "definitely_not_installed_pkg"}, import_check=False)[0] is False


def test_eager_boots_keep_the_classic_synchronous_startup():
    """Engine probes read at lifespan open must not race a reconcile that is
    importing the same runtimes (tests/probe/test_probe_engines.py)."""
    source = inspect.getsource(main._phase_b)
    guarded = source.split("if _EAGER:", 1)[1].split("\n\n", 1)[0]
    assert "_await_profile_reconcile(app)" in guarded


def test_shutdown_waits_for_a_running_reconcile_thread():
    source = inspect.getsource(main.lifespan)
    assert "_profile_reconcile_finished.wait" in source
