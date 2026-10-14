"""Unit tests for WebSocket audio streaming buffer quota and memory bounds."""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

# Gracefully stub third-party framework dependencies if running in hermetic test env
for mod_name in ("fastapi", "starlette", "starlette.requests", "starlette.websockets", "starlette.status"):
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except ModuleNotFoundError:
            m = MagicMock()
            if mod_name == "fastapi":
                class _WebSocketDisconnect(Exception):
                    pass
                m.WebSocketDisconnect = _WebSocketDisconnect
                m.APIRouter = lambda *a, **kw: MagicMock(
                    websocket=lambda *wa, **wkw: lambda fn: fn,
                    get=lambda *ga, **gkw: lambda fn: fn,
                    post=lambda *pa, **pkw: lambda fn: fn,
                )
            sys.modules[mod_name] = m

import pytest


def test_buffer_limit_constant_defaults_and_overrides(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_MAX_STREAM_BUFFER_BYTES", "1048576")
    from api.routers import capture_ws

    val = int(os.environ.get("OMNIVOICE_MAX_STREAM_BUFFER_BYTES", 25 * 1024 * 1024))
    assert val == 1048576


def test_ws_transcribe_enforces_buffer_limit(monkeypatch):
    from api.routers import capture_ws

    async def _run():
        monkeypatch.setattr(capture_ws, "MAX_STREAM_BUFFER_BYTES", 500)

        mock_ws = MagicMock()
        mock_ws.url.path = "/ws/transcribe"
        mock_ws.headers = {}
        mock_ws.client.host = "127.0.0.1"
        mock_ws.query_params = {}
        mock_ws.accept = AsyncMock()
        mock_ws.close = AsyncMock()

        sent_messages = []

        async def _mock_send_json(payload):
            sent_messages.append(payload)

        mock_ws.send_json = AsyncMock(side_effect=_mock_send_json)

        messages = [
            {"type": "websocket.receive", "bytes": b"A" * 300},
            {"type": "websocket.receive", "bytes": b"B" * 300},
        ]
        msg_idx = 0

        async def _mock_receive():
            nonlocal msg_idx
            if msg_idx < len(messages):
                msg = messages[msg_idx]
                msg_idx += 1
                return msg
            await asyncio.sleep(10)
            return {"type": "websocket.disconnect"}

        mock_ws.receive = AsyncMock(side_effect=_mock_receive)

        monkeypatch.setattr(capture_ws, "_transcribe_buffer", AsyncMock(return_value=""))
        monkeypatch.setattr(
            capture_ws,
            "_transcribe_buffer_full",
            AsyncMock(return_value={"text": "", "segments": []}),
        )

        await capture_ws.ws_transcribe(mock_ws)

        error_frames = [msg for msg in sent_messages if msg.get("type") == "error"]
        assert len(error_frames) >= 1
        assert "Audio stream exceeded maximum buffer limit" in error_frames[0].get("error", "")

    asyncio.run(_run())
