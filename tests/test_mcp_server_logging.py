import asyncio
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

import mcp_server


def test_opened_file_is_confined_oserror_logs_debug_and_scrubs(caplog, monkeypatch):
    secret_path = "/home/sensitive_user/base/file.wav"

    # Make /proc/self/fd check return False to exercise the os.fstat fallback
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    monkeypatch.setattr(os.path, "realpath", lambda p: secret_path)
    monkeypatch.setattr(mcp_server, "_path_is_under_base", lambda b, c: True)
    monkeypatch.setattr(
        os,
        "fstat",
        MagicMock(side_effect=OSError(f"permission denied on {secret_path}")),
    )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.mcp"):
        result = mcp_server._opened_file_is_confined(3, secret_path, "/home/sensitive_user/base")

    assert result is False
    assert "Failed verifying fd against path under base" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_read_input_audio_scrubs_path_in_error_messages(monkeypatch, tmp_path):
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(base_dir))

    secret_audio = str(base_dir / "secret_audio.wav")

    # File not found
    raw, err = mcp_server._read_input_audio(None, secret_audio, label="ref_audio")
    assert raw is None
    assert "no such file under OMNIVOICE_MCP_BASE_PATH" in err

    # Non-regular file (directory)
    sub_dir = base_dir / "subdir"
    sub_dir.mkdir()
    raw, err = mcp_server._read_input_audio(None, str(sub_dir), label="ref_audio")
    assert raw is None
    assert "is not a regular file" in err


def test_allowed_hosts_warning_scrubs_exception(caplog, monkeypatch):
    monkeypatch.setenv("OMNIVOICE_MCP_ALLOWED_HOSTS", "example.com")

    server = MagicMock()
    server.settings.transport_security.allowed_hosts.extend.side_effect = RuntimeError(
        "Host error for /home/sensitive_user/host"
    )

    with patch("mcp.server.fastmcp.FastMCP", return_value=server):
        with caplog.at_level(logging.WARNING, logger="omnivoice.mcp"):
            mcp_server.create_mcp_server()

    assert "OMNIVOICE_MCP_ALLOWED_HOSTS not applied" in caplog.text
    assert "sensitive_user" not in caplog.text


@pytest.mark.asyncio
async def test_current_client_id_exception_logs_debug_and_scrubs(caplog):
    server = mcp_server.create_mcp_server()
    generate_speech_fn = server._tool_manager.get_tool("generate_speech").fn

    # Inside generate_speech, _current_client_id() calls mcp.get_context()
    # Mock get_context to raise with sensitive path
    with patch.object(
        server,
        "get_context",
        MagicMock(side_effect=RuntimeError("Context lookup failed /home/sensitive_user/ctx")),
    ):
        with caplog.at_level(logging.DEBUG, logger="omnivoice.mcp"):
            with pytest.raises(Exception):
                await generate_speech_fn("hello")

    assert "Failed resolving client ID from MCP request context" in caplog.text
    assert "sensitive_user" not in caplog.text


@pytest.mark.asyncio
async def test_generate_speech_mcp_bindings_exception_logs_debug_and_scrubs(caplog, monkeypatch):
    from services import mcp_bindings

    monkeypatch.setattr(
        mcp_bindings,
        "resolve_voice",
        MagicMock(side_effect=RuntimeError("Binding DB unavailable at /home/sensitive_user/db.sqlite3")),
    )

    server = mcp_server.create_mcp_server()
    generate_speech_fn = server._tool_manager.get_tool("generate_speech").fn

    with caplog.at_level(logging.DEBUG, logger="omnivoice.mcp"):
        with pytest.raises(Exception):
            await generate_speech_fn("hello")

    assert "MCP binding layer unavailable" in caplog.text
    assert "sensitive_user" not in caplog.text


@pytest.mark.asyncio
async def test_clone_voice_json_decode_error_logs_debug_and_scrubs(caplog):
    server = mcp_server.create_mcp_server()
    clone_voice_fn = server._tool_manager.get_tool("clone_voice").fn

    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.text = "Bad Gateway HTML error from proxy at /home/sensitive_user/gateway"
    mock_resp.json.side_effect = ValueError("Invalid JSON /home/sensitive_user/data")

    http_error = httpx.HTTPStatusError("Bad Gateway", request=MagicMock(), response=mock_resp)

    with patch("httpx.AsyncClient.post", AsyncMock(side_effect=http_error)):
        with caplog.at_level(logging.DEBUG, logger="omnivoice.mcp"):
            res = await clone_voice_fn(
                name="Test Voice",
                ref_audio_base64="dGVzdCBhdWRpbyBkYXRh",
            )

    assert "Failed parsing JSON detail from clone response" in caplog.text
    assert "Bad Gateway" in res


@pytest.mark.asyncio
async def test_design_voice_json_decode_error_logs_debug_and_scrubs(caplog):
    server = mcp_server.create_mcp_server()
    design_voice_fn = server._tool_manager.get_tool("design_voice").fn

    mock_resp_describe = MagicMock()
    mock_resp_describe.status_code = 200
    mock_resp_describe.json.return_value = {
        "matched": True,
        "attrs": {"gender": "female"},
        "instruct": "calm",
        "unmatched": [],
    }

    mock_resp_save = MagicMock()
    mock_resp_save.status_code = 500
    mock_resp_save.text = "Internal Server Error /home/sensitive_user/error"
    mock_resp_save.json.side_effect = ValueError("Invalid JSON response /home/sensitive_user/data")

    save_http_error = httpx.HTTPStatusError("Server Error", request=MagicMock(), response=mock_resp_save)

    async def mock_post(url, *args, **kwargs):
        if "/design/describe" in url:
            return mock_resp_describe
        raise save_http_error

    with patch("httpx.AsyncClient.post", AsyncMock(side_effect=mock_post)):
        with caplog.at_level(logging.DEBUG, logger="omnivoice.mcp"):
            res = await design_voice_fn(
                name="Designed Voice",
                description="calm warm narrator",
            )

    assert "Failed parsing JSON detail from design response" in caplog.text
    assert "Server Error" in res
