import asyncio
import importlib
import logging
from unittest.mock import patch
import pytest


@pytest.fixture
def download_module():
    return importlib.import_module("api.routers.setup.download")


def test_safe_put_normal_and_overflow_eviction(download_module):
    queue = asyncio.Queue(maxsize=2)
    download_module._safe_put(queue, {"event": 1})
    download_module._safe_put(queue, {"event": 2})
    assert queue.qsize() == 2

    # Overflow should evict oldest (event 1) and put event 3
    download_module._safe_put(queue, {"event": 3})
    assert queue.qsize() == 2
    assert queue.get_nowait() == {"event": 2}
    assert queue.get_nowait() == {"event": 3}


def test_safe_put_eviction_queue_empty_concurrent_drain(download_module):
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait({"event": 1})

    original_get = queue.get_nowait

    def mock_get_nowait():
        original_get()
        raise asyncio.QueueEmpty()

    with patch.object(queue, "get_nowait", side_effect=mock_get_nowait):
        download_module._safe_put(queue, {"event": 2})

    assert queue.get_nowait() == {"event": 2}


def test_safe_put_failure_logs_debug_and_scrubs(download_module, caplog):
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait({"event": 1})

    # Make second put_nowait raise with sensitive path
    put_count = 0

    def mock_put_nowait(item):
        nonlocal put_count
        put_count += 1
        if put_count == 1:
            raise asyncio.QueueFull()
        raise RuntimeError("Queue rejected /home/sensitive_user/event.json")

    with patch.object(queue, "put_nowait", side_effect=mock_put_nowait):
        with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.download"):
            download_module._safe_put(queue, {"event": 2})

    assert "Failed to enqueue download progress event after eviction" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_validate_snapshot_has_weights_oswalk_oserror_logs_debug_and_scrubs(download_module, caplog, tmp_path):
    secret_dir = "/home/sensitive_user/snapshot"

    with patch.object(download_module, "snapshot_is_complete", return_value=False):
        with patch("os.scandir", side_effect=OSError(f"Permission denied on {secret_dir}")):
            with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.download"):
                with pytest.raises(OSError, match="download finished but no model weights were found"):
                    download_module._validate_snapshot_has_weights("unknown/repo", str(tmp_path))

    assert "Directory walk failed during snapshot weight verification" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_validate_snapshot_has_weights_getsize_oserror_logs_debug_and_scrubs(download_module, caplog, tmp_path):
    file_path = tmp_path / "model.safetensors"
    file_path.write_bytes(b"dummy")

    secret_path = f"/home/sensitive_user/models/{file_path.name}"

    def mock_getsize(path):
        raise OSError(f"Stat failed for {secret_path}")

    with patch.object(download_module, "snapshot_is_complete", return_value=False):
        with patch("os.path.getsize", side_effect=mock_getsize):
            with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.download"):
                with pytest.raises(OSError, match="download finished but no model weights were found"):
                    download_module._validate_snapshot_has_weights("unknown/repo", str(tmp_path))

    assert "Could not stat snapshot file during weight verification" in caplog.text
    assert "sensitive_user" not in caplog.text


@pytest.mark.asyncio
async def test_setup_download_stream_listener_runtime_error_logs_debug_and_scrubs(download_module, caplog):
    registered_listener = None

    def mock_register(fn):
        nonlocal registered_listener
        registered_listener = fn
        return 12345

    with patch("utils.hf_progress.register_listener", side_effect=mock_register):
        await download_module.setup_download_stream()

    assert registered_listener is not None

    loop = asyncio.get_running_loop()
    with patch.object(
        loop,
        "call_soon_threadsafe",
        side_effect=RuntimeError("Event loop is closed /home/sensitive_user/loop"),
    ):
        with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.download"):
            registered_listener({"status": "progress"})

    assert "Download progress event loop schedule failed" in caplog.text
    assert "sensitive_user" not in caplog.text
