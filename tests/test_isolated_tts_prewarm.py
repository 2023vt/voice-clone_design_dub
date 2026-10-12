"""The crash-isolated OmniVoice sidecar (the MPS default) loaded its model only
inside the first Synthesize: spawn + imports + weights was 35-45 s. Startup now
warms it in the background; these pin the protocol, the lock-sharing that lets a
mid-warm-up request join the load, and the guards that keep it download-free."""
import asyncio
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from engines.omnivoice_subprocess import OmniVoiceSubprocessBackend  # noqa: E402
from engines.omnivoice_subprocess import main as sidecar  # noqa: E402
from services import model_manager, subprocess_backend, tts_backend  # noqa: E402


def _backend(monkeypatch, replies, sent):
    backend = OmniVoiceSubprocessBackend()
    monkeypatch.setattr(backend, "_spawn", lambda: None)
    monkeypatch.setattr(backend, "_send", sent.append)
    queue = list(replies)
    monkeypatch.setattr(backend, "_recv_with_timeout", lambda _t: queue.pop(0) if queue else None)
    return backend


def test_sidecar_warmup_loads_the_model_and_answers_warm(monkeypatch):
    frames, loads = [], []
    monkeypatch.setattr(sidecar, "_load_model", lambda out: loads.append(out))
    monkeypatch.setattr(sidecar, "_send", lambda _out, frame: frames.append(frame))
    sidecar._handle_warmup("stdout")
    assert loads == ["stdout"]
    assert frames == [{"op": "warm"}]


def test_warm_reply_passes_the_parent_op_allowlist():
    """The reply was silently dropped as 'disallowed' until it was listed."""
    assert "warm" in subprocess_backend.PARENT_INBOUND_OPS
    assert "warmup" in subprocess_backend.SIDECAR_INBOUND_OPS


def test_warmup_sends_op_and_waits_through_progress_frames(monkeypatch):
    sent = []
    backend = _backend(
        monkeypatch,
        [{"op": "progress", "percent": 10}, {"op": "progress", "percent": 90}, {"op": "warm"}],
        sent,
    )
    assert backend.warmup() is True
    assert sent == [{"op": "warmup"}]


def test_warmup_surfaces_a_sidecar_error(monkeypatch):
    backend = _backend(monkeypatch, [{"op": "error", "message": "boom"}], [])
    with pytest.raises(RuntimeError, match="warm-up error: boom"):
        backend.warmup()


def test_warmup_reaps_a_sidecar_that_closes_during_load(monkeypatch):
    backend = _backend(monkeypatch, [], [])
    reaped = []
    monkeypatch.setattr(backend, "_reap_unusable_process", reaped.append)
    with pytest.raises(RuntimeError, match="closed during warm-up"):
        backend.warmup()
    assert len(reaped) == 1


def test_engines_without_warmup_keep_their_first_use_cold_start():
    assert subprocess_backend.SubprocessBackend.supports_warmup is False
    plain = OmniVoiceSubprocessBackend()
    plain.supports_warmup = False
    assert plain.warmup() is False


def test_a_synthesize_during_warmup_waits_for_the_same_load(monkeypatch):
    """warmup and generate share the backend lock, so the request queues behind
    the load instead of starting a second one."""
    sent, release = [], threading.Event()
    backend = OmniVoiceSubprocessBackend()
    monkeypatch.setattr(backend, "_spawn", lambda: None)
    monkeypatch.setattr(backend, "_send", sent.append)

    def slow_recv(_t):
        release.wait(5)
        return {"op": "warm"}

    monkeypatch.setattr(backend, "_recv_with_timeout", slow_recv)
    worker = threading.Thread(target=backend.warmup)
    worker.start()
    while not sent:
        pass
    assert backend._lock.locked()
    assert backend._lock.acquire(blocking=False) is False
    release.set()
    worker.join(5)
    assert not backend._lock.locked()


@pytest.fixture
def prewarm(monkeypatch):
    calls = []

    class Warm:
        supports_warmup = True

    class Instance:
        def warmup(self):
            calls.append("warmup")

    monkeypatch.delenv("OMNIVOICE_PRELOAD_ISOLATED_TTS", raising=False)
    monkeypatch.setattr(tts_backend, "active_backend_id", lambda: "omnivoice")
    monkeypatch.setattr(tts_backend, "get_backend_class", lambda _id: Warm)
    monkeypatch.setattr(tts_backend, "get_engine_instance", lambda _cls: Instance())
    monkeypatch.setattr(model_manager, "_ensure_omnivoice_licence", lambda: None)
    monkeypatch.setattr(model_manager, "_checkpoint_in_local_cache", lambda _c: True)

    async def inline(fn, **_kw):
        return fn()

    monkeypatch.setattr(model_manager, "run_on_gpu_pool_guarded", inline)
    return calls


def test_prewarm_warms_an_installed_isolated_engine(prewarm):
    asyncio.run(model_manager.prewarm_isolated_tts())
    assert prewarm == ["warmup"]


def test_prewarm_never_downloads(prewarm, monkeypatch):
    monkeypatch.setattr(model_manager, "_checkpoint_in_local_cache", lambda _c: False)
    asyncio.run(model_manager.prewarm_isolated_tts())
    assert prewarm == []


def test_prewarm_skips_until_the_licence_is_accepted(prewarm, monkeypatch):
    from services.model_acceptance import ModelLicenceNotAccepted

    def refuse():
        raise ModelLicenceNotAccepted("k2-fsa/OmniVoice")

    monkeypatch.setattr(model_manager, "_ensure_omnivoice_licence", refuse)
    asyncio.run(model_manager.prewarm_isolated_tts())
    assert prewarm == []


def test_prewarm_skips_in_process_engines(prewarm, monkeypatch):
    monkeypatch.setattr(tts_backend, "get_backend_class", lambda _id: object)
    asyncio.run(model_manager.prewarm_isolated_tts())
    assert prewarm == []


def test_prewarm_can_be_disabled(prewarm, monkeypatch):
    monkeypatch.setenv("OMNIVOICE_PRELOAD_ISOLATED_TTS", "0")
    asyncio.run(model_manager.prewarm_isolated_tts())
    assert prewarm == []


def test_prewarm_failure_is_non_fatal(prewarm, monkeypatch):
    async def broken(fn, **_kw):
        raise RuntimeError("sidecar exploded")

    monkeypatch.setattr(model_manager, "run_on_gpu_pool_guarded", broken)
    asyncio.run(model_manager.prewarm_isolated_tts())
