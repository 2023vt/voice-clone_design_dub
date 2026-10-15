"""Unit tests verifying exception logging and redaction in longform_render.py SegmentCache.store."""
import logging
from unittest.mock import MagicMock
import pytest


def test_segment_cache_store_exception_logs_debug_and_scrubs_path(tmp_path, monkeypatch, caplog):
    import sys
    monkeypatch.setitem(sys.modules, "torch", MagicMock())
    monkeypatch.setitem(sys.modules, "torchaudio", MagicMock())

    from services import longform_render

    cache = longform_render.SegmentCache(
        str(tmp_path),
        sample_rate=24000,
        engine_id="test_engine",
    )

    span = MagicMock()
    span.text = "Hello world"
    span.voice_id = "speaker_1"
    span.speed = None

    audio = MagicMock()

    # Mock atomic_save_wav to fail with private path
    def _faulty_save(*args, **kwargs):
        raise RuntimeError("disk write failure at /Users/developer/cache/segment.wav")

    monkeypatch.setattr("services.audio_io.atomic_save_wav", _faulty_save)

    with caplog.at_level(logging.DEBUG, logger="omnivoice.longform_render"):
        # Must not raise
        cache.store(span, audio)

    # Verify debug message logged and path redacted
    assert any("Failed to cache longform span" in r.message for r in caplog.records)
    assert "/Users/developer" not in caplog.text
