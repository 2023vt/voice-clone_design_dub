import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest


@pytest.fixture
def mcp_server_module():
    import mcp_server
    return mcp_server


def test_opened_file_is_confined_oserror_logs_debug_and_scrubs(mcp_server_module, caplog, monkeypatch):
    secret_path = "/home/sensitive_user/base/file.wav"

    # Make /proc/self/fd check return False to exercise the os.fstat fallback
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    monkeypatch.setattr(os.path, "realpath", lambda p: secret_path)
    monkeypatch.setattr(mcp_server_module, "_path_is_under_base", lambda b, c: True)
    monkeypatch.setattr(
        os,
        "fstat",
        MagicMock(side_effect=OSError(f"permission denied on {secret_path}")),
    )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.mcp"):
        result = mcp_server_module._opened_file_is_confined(3, secret_path, "/home/sensitive_user/base")

    assert result is False
    assert "Failed verifying fd against path under base" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_read_input_audio_scrubs_path_in_error_messages(mcp_server_module, monkeypatch, tmp_path):
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(base_dir))

    # Test file not found with sensitive home path
    sensitive_missing = "/home/sensitive_user/base/missing.wav"
    with patch.object(mcp_server_module, "_open_under_base", side_effect=FileNotFoundError):
        raw, err = mcp_server_module._read_input_audio(None, sensitive_missing, label="ref_audio")
    assert raw is None
    assert "no such file under OMNIVOICE_MCP_BASE_PATH" in err
    assert "sensitive_user" not in err
    assert "/home/sensitive_user" not in err

    # Test directory check with sensitive home path
    sensitive_dir = "/home/sensitive_user/base/subdir"
    mock_stat = MagicMock()
    mock_stat.st_mode = 0o040755  # directory
    with patch.object(mcp_server_module, "_open_under_base", return_value=(99, sensitive_dir)):
        with patch("os.fstat", return_value=mock_stat):
            with patch("os.close") as mock_close:
                raw, err = mcp_server_module._read_input_audio(None, sensitive_dir, label="ref_audio")
                mock_close.assert_called_once_with(99)
    assert raw is None
    assert "is not a regular file" in err
    assert "sensitive_user" not in err
    assert "/home/sensitive_user" not in err

    # Test ValueError (path outside base) with sensitive home path
    sensitive_outside = "/home/sensitive_user/other/secret.wav"
    with patch.object(
        mcp_server_module,
        "_open_under_base",
        side_effect=ValueError(f"'{sensitive_outside}' resolves outside OMNIVOICE_MCP_BASE_PATH"),
    ):
        raw, err = mcp_server_module._read_input_audio(None, sensitive_outside, label="ref_audio")
    assert raw is None
    assert "resolves outside OMNIVOICE_MCP_BASE_PATH" in err
    assert "sensitive_user" not in err
    assert "/home/sensitive_user" not in err


def test_read_input_audio_read_oserror_cleans_up_without_double_close(mcp_server_module, monkeypatch, tmp_path):
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    monkeypatch.setenv("OMNIVOICE_MCP_BASE_PATH", str(base_dir))

    valid_file = base_dir / "valid.wav"
    valid_file.write_bytes(b"RIFFdummydata")

    original_fdopen = os.fdopen

    class FailingHandle:
        def __init__(self, raw_handle):
            self._handle = raw_handle

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self._handle.close()

        def read(self, *args, **kwargs):
            raise OSError("I/O failure during read /home/sensitive_user/read_error")

    def mock_fdopen(fd, mode="r", *args, **kwargs):
        real_handle = original_fdopen(fd, mode, *args, **kwargs)
        return FailingHandle(real_handle)

    monkeypatch.setattr(os, "fdopen", mock_fdopen)

    close_calls = []
    original_close = os.close

    def tracking_close(fd):
        close_calls.append(fd)
        return original_close(fd)

    monkeypatch.setattr(os, "close", tracking_close)

    raw, err = mcp_server_module._read_input_audio(None, str(valid_file), label="ref_audio")
    assert raw is None
    assert "could not safely read" in err
    assert "sensitive_user" not in err
    # os.close should be called exactly once by the handle context, NOT a second time by except block
    assert len(close_calls) == 1


def test_allowed_hosts_warning_scrubs_exception(mcp_server_module, caplog, monkeypatch):
    monkeypatch.setenv("OMNIVOICE_MCP_ALLOWED_HOSTS", "example.com")

    server = MagicMock()
    server.settings.transport_security.allowed_hosts.extend.side_effect = RuntimeError(
        "Host error for /home/sensitive_user/host"
    )

    with patch("mcp.server.fastmcp.FastMCP", return_value=server):
        with caplog.at_level(logging.WARNING, logger="omnivoice.mcp"):
            mcp_server_module.create_mcp_server()

    assert "OMNIVOICE_MCP_ALLOWED_HOSTS not applied" in caplog.text
    assert "sensitive_user" not in caplog.text


@pytest.mark.asyncio
async def test_current_client_id_exception_logs_debug_and_scrubs(mcp_server_module, caplog):
    server = mcp_server_module.create_mcp_server()
    generate_speech_fn = server._tool_manager.get_tool("generate_speech").fn

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"X-Audio-Id": "test_audio_123", "X-Gen-Time": "0.5", "X-Audio-Duration": "1.2"}
    mock_resp.content = b"RIFFtestwavbytes"

    # Inside generate_speech, _current_client_id() calls mcp.get_context()
    # Mock get_context to raise with sensitive path
    with patch.object(
        server,
        "get_context",
        MagicMock(side_effect=RuntimeError("Context lookup failed /home/sensitive_user/ctx")),
    ):
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)) as mock_post:
            with caplog.at_level(logging.DEBUG, logger="omnivoice.mcp"):
                res = await generate_speech_fn("hello")

    assert "Failed resolving client ID from MCP request context" in caplog.text
    assert "sensitive_user" not in caplog.text
    mock_post.assert_awaited_once()
    assert mock_post.await_args.kwargs["data"]["text"] == "hello"
    assert "profile_id" not in mock_post.await_args.kwargs["data"]
    assert "test_audio_123" in res


@pytest.mark.asyncio
async def test_generate_speech_mcp_bindings_exception_logs_debug_and_scrubs(mcp_server_module, caplog, monkeypatch):
    from services import mcp_bindings

    monkeypatch.setattr(
        mcp_bindings,
        "resolve_voice",
        MagicMock(side_effect=RuntimeError("Binding DB unavailable at /home/sensitive_user/db.sqlite3")),
    )

    server = mcp_server_module.create_mcp_server()
    generate_speech_fn = server._tool_manager.get_tool("generate_speech").fn

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"X-Audio-Id": "test_audio_456", "X-Gen-Time": "0.3", "X-Audio-Duration": "1.0"}
    mock_resp.content = b"RIFFtestwavbytes"

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)) as mock_post:
        with caplog.at_level(logging.DEBUG, logger="omnivoice.mcp"):
            res = await generate_speech_fn("hello")

    assert "MCP binding layer unavailable" in caplog.text
    assert "sensitive_user" not in caplog.text
    mock_post.assert_awaited_once()
    assert mock_post.await_args.kwargs["data"]["text"] == "hello"
    assert "profile_id" not in mock_post.await_args.kwargs["data"]
    assert "test_audio_456" in res


@pytest.mark.asyncio
async def test_clone_voice_json_decode_error_logs_debug_and_scrubs(mcp_server_module, caplog):
    server = mcp_server_module.create_mcp_server()
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
async def test_design_voice_json_decode_error_logs_debug_and_scrubs(mcp_server_module, caplog):
    server = mcp_server_module.create_mcp_server()
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
