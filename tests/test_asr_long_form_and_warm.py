"""Whisper long-form decoding and the warm transcription engine.

1. Sequential Whisper decoding conditions each 30 s window on the previous
   window's text by default, so one bad window repeats through the rest of a
   long file (measured: 594 words for a 540-word truth, 3.4x slower). Every
   in-house sequential Whisper call must turn that off: faster-whisper
   in-process, the isolated faster-whisper sidecar, and MLX Whisper.
2. ``get_active_asr_backend()`` builds a fresh whisper instance per call, so
   each Clone reference / accurate transcription reloaded the weights (8.7 s
   load for 1.7 s of decoding on a CUDA GPU). ``warm_asr_backend()`` leases
   one loaded instance per (engine, model). Concurrent first requests load it
   once; it is unloaded by the idle timer and the Unload control, never while
   a request holds it.

Fail-before/pass-after: before this change no call passes
``condition_on_previous_text``, ``warm_asr_backend`` does not exist, and there
is no ``transcription-asr`` entry to list or unload.
"""
from __future__ import annotations

import asyncio
import importlib
import threading
import time
import importlib.util
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("asr_model_installed")


class _Info:
    language = "en"
    language_probability = 1.0
    duration = 1.0


class _RecordingWhisperModel:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, audio_path, **kwargs):
        self.kwargs = kwargs
        return iter(()), _Info()


@pytest.fixture
def ab(monkeypatch):
    """The live module: earlier tests in a full run may purge ``services.*``
    from sys.modules, so a module-level alias can be stale."""
    module = importlib.import_module("services.asr_backend")
    monkeypatch.delenv("OMNIVOICE_ASR_BACKEND", raising=False)
    monkeypatch.setattr(module, "_warm_active", None, raising=False)
    monkeypatch.setattr(module, "_warm_active_key", None, raising=False)
    monkeypatch.setattr(module, "_warm_active_last_used", 0.0, raising=False)
    monkeypatch.setattr(module, "_warm_active_leases", 0, raising=False)
    return module


# ── 1. long-form conditioning is off on every sequential Whisper path ──────


def test_faster_whisper_does_not_condition_on_previous_text(ab):
    backend = ab.FasterWhisperBackend(model_name="fake/model")
    backend._model = _RecordingWhisperModel()

    backend.transcribe("clip.wav", word_timestamps=False)

    assert backend._model.kwargs["condition_on_previous_text"] is False


def test_mlx_whisper_does_not_condition_on_previous_text(ab, monkeypatch):
    seen = {}

    def fake_transcribe(audio, **kwargs):
        seen.update(kwargs)
        return {"segments": [], "language": "en", "text": ""}

    monkeypatch.setitem(sys.modules, "mlx_whisper", types.SimpleNamespace(transcribe=fake_transcribe))
    monkeypatch.setattr(ab, "_decode_audio_16k_mono", lambda path: [0.0])

    ab.MLXWhisperBackend(model_name="fake/mlx").transcribe("clip.wav", word_timestamps=False)

    assert seen["condition_on_previous_text"] is False


def test_isolated_sidecar_does_not_condition_on_previous_text(ab, monkeypatch):
    monkeypatch.setattr("core.cudnn8.preload", lambda: None)
    path = Path(ab.__file__).resolve().parents[1] / "engines" / "_asr_sidecar" / "main.py"
    spec = importlib.util.spec_from_file_location("_sidecar_long_form", path)
    sidecar = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(sidecar)
    finally:
        sys.path[:] = saved
    model = _RecordingWhisperModel()
    monkeypatch.setattr(sidecar, "_get_model", lambda: model)

    sidecar._transcribe("clip.wav", False)

    assert model.kwargs["condition_on_previous_text"] is False


# ── 2. warm transcription engine ────────────────────────────────────────────


@pytest.fixture
def faster_whisper_selected(ab, monkeypatch):
    """Select faster-whisper; count weight loads and unloads. Faster-Whisper
    loads lazily (``_ensure_model``), which is what the handout must cover."""
    calls = {"loads": [], "unloads": 0}
    model_name = {"value": "fake/large-v3"}
    monkeypatch.setattr(ab, "active_backend_id", lambda: "faster-whisper")
    monkeypatch.setattr(ab, "faster_whisper_model_id", lambda: model_name["value"])

    def ensure_model(self):
        if self._model is None:
            time.sleep(0.05)  # widen the window two first requests race in
            calls["loads"].append(self._model_name)
            self._model = _RecordingWhisperModel()

    def unload(self):
        calls["unloads"] += 1
        self._model = None

    monkeypatch.setattr(ab.FasterWhisperBackend, "_ensure_model", ensure_model)
    monkeypatch.setattr(ab.FasterWhisperBackend, "unload", unload)
    return calls, model_name


def _handout(ab):
    with ab.warm_asr_backend() as backend:
        return backend


def test_warm_requests_reuse_one_loaded_engine(ab, faster_whisper_selected):
    calls, _ = faster_whisper_selected

    first = _handout(ab)
    second = _handout(ab)

    assert second is first
    assert calls["loads"] == ["fake/large-v3"]


def test_concurrent_first_requests_load_once(ab, faster_whisper_selected):
    calls, _ = faster_whisper_selected
    got = []
    threads = [threading.Thread(target=lambda: got.append(_handout(ab))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(got) == 4 and all(b is got[0] for b in got)
    assert calls["loads"] == ["fake/large-v3"]


def test_cold_calls_keep_private_instances(ab, faster_whisper_selected):
    """Dub and batch unload their engine for the TTS stage; they must never
    receive (and unload) the shared warm instance."""
    warm = _handout(ab)
    cold = ab.load_active_asr_backend()

    assert cold is not warm
    assert _handout(ab) is warm


def test_model_change_replaces_the_warm_engine(ab, faster_whisper_selected):
    calls, model_name = faster_whisper_selected

    first = _handout(ab)
    model_name["value"] = "fake/turbo"
    second = _handout(ab)

    assert second is not first
    assert calls["loads"] == ["fake/large-v3", "fake/turbo"]


def test_idle_release_unloads_the_warm_engine(ab, faster_whisper_selected):
    calls, _ = faster_whisper_selected
    backend = _handout(ab)
    last = ab._warm_active_last_used

    assert ab.release_idle_warm_asr_backend(60.0, now=last + 30) is False
    assert ab._warm_active is backend
    assert ab.release_idle_warm_asr_backend(60.0, now=last + 61) is True
    assert ab._warm_active is None
    assert calls["unloads"] == 1  # weights freed, not just dereferenced (MLX)
    assert ab.release_idle_warm_asr_backend(0.0) is False


def test_release_waits_for_a_running_transcription(ab, faster_whisper_selected):
    calls, _ = faster_whisper_selected

    with ab.warm_asr_backend() as backend:
        assert ab.release_idle_warm_asr_backend(0.0, now=time.monotonic() + 10_000) is False
        assert ab._warm_active is backend and calls["unloads"] == 0

    assert ab.release_idle_warm_asr_backend(0.0) is True
    assert calls["unloads"] == 1


def test_warm_engine_is_listed_and_unloadable(ab, faster_whisper_selected, monkeypatch):
    model_lifecycle = importlib.import_module("services.model_lifecycle")
    monkeypatch.setattr(model_lifecycle.mm, "free_vram", lambda: None)
    _handout(ab)

    listed = {m["id"]: m for m in model_lifecycle.list_loaded()["models"]}
    assert listed["transcription-asr"]["unloadable"] is True
    assert listed["transcription-asr"]["checkpoint"] == "fake/large-v3"

    result = asyncio.run(model_lifecycle.unload("transcription-asr"))
    assert result == {"unloaded": "transcription-asr", "success": True}
    assert ab._warm_active is None


def test_faster_whisper_loads_at_preflight(ab, monkeypatch):
    """``ensure_loaded`` must load the weights (#578): otherwise the warm
    handout publishes an empty engine and its lock covers no load at all."""
    loaded = []
    monkeypatch.setattr(
        ab.FasterWhisperBackend, "_ensure_model", lambda self: loaded.append(self._model_name),
    )

    ab.FasterWhisperBackend(model_name="fake/model").ensure_loaded()

    assert loaded == ["fake/model"]
