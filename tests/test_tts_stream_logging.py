import asyncio
import importlib
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def tts_stream_module():
    return importlib.import_module("api.routers.tts_stream")


def test_resolve_emotion_clip_logs_debug_and_scrubs(tts_stream_module, caplog, monkeypatch):
    secret_dir = "/home/sensitive_user/emo.wav"
    secret_root = "/home/sensitive_user/voices"

    def mock_resolve_within(root, path):
        raise OSError(f"Permission denied on {secret_dir}")

    import core.path_security
    monkeypatch.setattr(core.path_security, "resolve_within", mock_resolve_within)
    import core.config
    monkeypatch.setattr(core.config, "VOICES_DIR", secret_root)

    with caplog.at_level(logging.DEBUG, logger="omnivoice.tts_stream"):
        with pytest.raises(ValueError):
            tts_stream_module.resolve_emotion_clip("emo.wav")

    assert "Failed resolving emo audio path" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_build_stream_kwargs_db_error_logs_debug_and_scrubs(tts_stream_module, caplog, monkeypatch):
    secret_db = "/home/sensitive_user/db.sqlite3"

    def mock_db_conn():
        raise RuntimeError(f"Database error at {secret_db}")

    import core.db
    monkeypatch.setattr(core.db, "db_conn", mock_db_conn)

    with caplog.at_level(logging.DEBUG, logger="omnivoice.tts_stream"):
        kw = tts_stream_module.build_stream_kwargs({"voice": "custom_profile_1"})

    assert kw.get("voice") == "custom_profile_1"
    assert "Voice profile resolution failed for custom_profile_1" in caplog.text
    assert "sensitive_user" not in caplog.text


@pytest.mark.asyncio
async def test_ws_tts_memory_budget_failure_logs_debug_and_scrubs(tts_stream_module, caplog, monkeypatch):
    import services.memory_budget

    secret_path = "/home/sensitive_user/cgroups/mem"

    def mock_log_if_low(msg):
        raise RuntimeError(f"Memory probe failed for {secret_path}")

    monkeypatch.setattr(services.memory_budget, "log_if_low", mock_log_if_low)

    mock_backend = MagicMock()
    mock_backend.id = "mock_engine"
    mock_backend.generate_stream = MagicMock()

    async def mock_resolve(eid):
        return mock_backend

    monkeypatch.setattr(tts_stream_module, "_resolve_stream_backend", mock_resolve)

    import services.tts_backend
    monkeypatch.setattr(services.tts_backend, "engine_in_use", MagicMock())

    import services.engine_routing
    monkeypatch.setattr(
        services.engine_routing,
        "runtime_compute_profile_async",
        AsyncMock(return_value={
            "effective_device": "cpu",
            "routing_status": "cpu_only",
            "routing_reason": None,
        }),
    )

    import services.engine_memory
    monkeypatch.setattr(services.engine_memory, "evict_other_tts_engines", AsyncMock())

    mock_ws = MagicMock()
    mock_ws.accept = AsyncMock()
    # First message: text request; second message: raise disconnect
    receive_calls = 0

    async def mock_receive_json():
        nonlocal receive_calls
        receive_calls += 1
        if receive_calls == 1:
            return {"text": "hello", "engine": "test"}
        from fastapi import WebSocketDisconnect
        raise WebSocketDisconnect()

    mock_ws.receive_json = mock_receive_json
    mock_ws.send_json = AsyncMock()
    mock_ws.send_bytes = AsyncMock()

    with caplog.at_level(logging.DEBUG, logger="omnivoice.tts_stream"):
        await tts_stream_module.ws_tts(mock_ws)

    assert "Memory budget probe failed" in caplog.text
    assert "sensitive_user" not in caplog.text


@pytest.mark.asyncio
async def test_ws_tts_streaming_error_logs_error_without_traceback_paths(tts_stream_module, caplog, monkeypatch):
    async def mock_resolve(eid):
        raise RuntimeError("Generation failed: model at /home/sensitive_user/models/weights.bin corrupted")

    monkeypatch.setattr(tts_stream_module, "_resolve_stream_backend", mock_resolve)

    mock_ws = MagicMock()
    mock_ws.accept = AsyncMock()
    # First message: triggers error; second message: disconnect
    receive_calls = 0

    async def mock_receive_json():
        nonlocal receive_calls
        receive_calls += 1
        if receive_calls == 1:
            return {"text": "generate audio", "engine": "test"}
        from fastapi import WebSocketDisconnect
        raise WebSocketDisconnect()

    mock_ws.receive_json = mock_receive_json
    mock_ws.send_json = AsyncMock()
    mock_ws.send_bytes = AsyncMock()

    with caplog.at_level(logging.ERROR, logger="omnivoice.tts_stream"):
        await tts_stream_module.ws_tts(mock_ws)

    error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("TTS streaming failed" in m for m in error_msgs)
    # Verify sensitive path is scrubbed and no traceback is attached to the record
    for record in caplog.records:
        assert "sensitive_user" not in record.message
        if record.exc_info:
            import traceback
            tb_text = "".join(traceback.format_exception(*record.exc_info))
            assert "sensitive_user" not in tb_text


@pytest.mark.asyncio
async def test_ws_tts_error_frame_send_failure_logs_debug_and_scrubs(tts_stream_module, caplog, monkeypatch):
    mock_backend = MagicMock()
    mock_backend.id = "mock_engine"

    async def mock_resolve(eid):
        raise RuntimeError("Engine load failed /home/sensitive_user/weights.bin")

    monkeypatch.setattr(tts_stream_module, "_resolve_stream_backend", mock_resolve)

    mock_ws = MagicMock()
    mock_ws.accept = AsyncMock()
    mock_ws.receive_json = AsyncMock(return_value={"text": "generate audio"})
    mock_ws.send_json = AsyncMock(side_effect=RuntimeError("Socket error /home/sensitive_user/socket"))

    with caplog.at_level(logging.DEBUG, logger="omnivoice.tts_stream"):
        await tts_stream_module.ws_tts(mock_ws)

    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("Failed sending error frame over websocket" in m for m in debug_msgs)
    for m in debug_msgs:
        assert "sensitive_user" not in m


@pytest.mark.asyncio
async def test_ws_tts_outer_exception_logs_debug_and_scrubs(tts_stream_module, caplog):
    mock_ws = MagicMock()
    mock_ws.accept = AsyncMock(side_effect=RuntimeError("Accept failed on /home/sensitive_user/port"))

    with caplog.at_level(logging.DEBUG, logger="omnivoice.tts_stream"):
        await tts_stream_module.ws_tts(mock_ws)

    assert "TTS WebSocket ended" in caplog.text
    assert "sensitive_user" not in caplog.text
