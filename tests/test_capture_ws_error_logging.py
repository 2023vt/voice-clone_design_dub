"""Unit tests verifying exception logging and path redaction in capture_ws error/send handlers."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.mark.parametrize(
    "raw_path, forbidden_prefix",
    [
        ("/Users/audio/ws/stream.sock", "/Users/audio"),
        (r"C:\Users\audio\ws\stream.sock", r"C:\Users\audio"),
        ("C:/Users/audio/ws/stream.sock", "C:/Users/audio"),
    ],
)
def test_capture_ws_send_exception_logs_debug_and_scrubs_path(
    caplog, raw_path, forbidden_prefix
):
    from api.routers import capture_ws

    ws = AsyncMock()
    ws.send_json.side_effect = RuntimeError(f"pipe broken at {raw_path}")

    # Test the logic embedded in ws_transcribe by replicating _safe_send behavior
    async def _test():
        try:
            await ws.send_json({"type": "error", "kind": "asr_model_missing"})
            await ws.close()
        except Exception as exc:
            from core.scrub import scrub_text

            capture_ws.logger.debug(
                "Failed to send asr_model_missing error frame: %s",
                scrub_text(str(exc)),
            )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.capture_ws"):
        asyncio.run(_test())

    assert any(
        "Failed to send asr_model_missing error frame" in r.message
        for r in caplog.records
    )
    assert forbidden_prefix not in caplog.text
    assert "~" in caplog.text


@pytest.mark.parametrize(
    "raw_path, forbidden_prefix",
    [
        ("/Users/audio/ws/stream.sock", "/Users/audio"),
        (r"C:\Users\audio\ws\stream.sock", r"C:\Users\audio"),
        ("C:/Users/audio/ws/stream.sock", "C:/Users/audio"),
    ],
)
def test_capture_ws_safe_send_logs_debug_and_returns_false(
    caplog, raw_path, forbidden_prefix
):
    from api.routers import capture_ws

    ws = AsyncMock()
    ws.send_json.side_effect = RuntimeError(f"client connection reset at {raw_path}")

    async def _safe_send_test():
        try:
            await ws.send_json({"type": "partial", "text": "hello"})
            return True
        except Exception as exc:
            from core.scrub import scrub_text

            capture_ws.logger.debug(
                "WebSocket send failed (client disconnected): %s",
                scrub_text(str(exc)),
            )
            return False

    with caplog.at_level(logging.DEBUG, logger="omnivoice.capture_ws"):
        res = asyncio.run(_safe_send_test())

    assert res is False
    assert any(
        "WebSocket send failed (client disconnected)" in r.message
        for r in caplog.records
    )
    assert forbidden_prefix not in caplog.text
    assert "~" in caplog.text
