import importlib
import logging
import os
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def models_module():
    return importlib.import_module("api.routers.setup.models")


def test_current_platform_tags_torch_exception_logs_debug_and_scrubs(models_module, caplog, monkeypatch):
    secret_path = "/home/sensitive_user/torch/libcuda.so"

    mock_torch = MagicMock()
    mock_torch.cuda.is_available.side_effect = RuntimeError(f"Driver error at {secret_path}")
    monkeypatch.setattr("sys.modules", {**os.sys.modules, "torch": mock_torch})

    with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.models"):
        tags = models_module._current_platform_tags()

    assert "Torch platform acceleration probe skipped or unavailable" in caplog.text
    assert "sensitive_user" not in caplog.text
    assert "cpu" in tags or "darwin-arm64" in tags


def test_disk_free_bytes_exception_logs_debug_and_scrubs(models_module, caplog):
    secret_path = "/home/sensitive_user/cache_volume"

    with patch("shutil.disk_usage", side_effect=OSError(f"Failed probing {secret_path}")):
        with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.models"):
            free = models_module.disk_free_bytes(secret_path)

    assert free == 0
    assert "Disk free bytes probe failed" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_snapshot_has_weights_scandir_oserror_logs_debug_and_scrubs(models_module, caplog, tmp_path):
    secret_dir = "/home/sensitive_user/snapshot"

    with patch("os.scandir", side_effect=OSError(f"Permission denied on {secret_dir}")):
        with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.models"):
            result = models_module.snapshot_has_weights(str(tmp_path))

    assert result is True
    assert "Directory walk error in snapshot weight check" in caplog.text or "Snapshot weight inspection failed" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_snapshot_dirs_oserror_logs_debug_and_scrubs(models_module, caplog, tmp_path):
    secret_path = f"/home/sensitive_user/snapshots"

    with patch.object(models_module, "_hub_cache_roots", return_value=[str(tmp_path)]):
        with patch("os.listdir", side_effect=OSError(f"Unreadable directory {secret_path}")):
            with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.models"):
                dirs = models_module._snapshot_dirs("org/model")

    assert dirs == []
    assert "Could not list snapshot directory" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_snapshot_is_complete_oserror_logs_debug_and_scrubs(models_module, caplog, tmp_path):
    secret_path = f"/home/sensitive_user/weight.bin"

    model = {"repo_id": "test/model", "required_files": ["weight.bin"]}
    with patch("os.path.isfile", return_value=True):
        with patch("os.path.getsize", side_effect=OSError(f"I/O error on {secret_path}")):
            with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.models"):
                complete = models_module.snapshot_is_complete(model, str(tmp_path))

    assert complete is False
    assert "Failed verifying snapshot completeness for test/model" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_is_cached_on_disk_oserror_logs_debug_and_scrubs(models_module, caplog, tmp_path):
    secret_path = f"/home/sensitive_user/snapshots"

    with patch.object(models_module, "_hub_cache_roots", return_value=[str(tmp_path)]):
        with patch("os.path.isdir", return_value=True):
            with patch("os.listdir", side_effect=OSError(f"Permission denied on {secret_path}")):
                with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.models"):
                    cached = models_module._is_cached_on_disk("test/model")

    assert cached is False
    assert "Could not scan snapshot revisions" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_scan_cache_on_disk_oserror_logs_debug_and_scrubs(models_module, caplog, tmp_path):
    secret_root = "/home/sensitive_user/cache_root"

    with patch.object(models_module, "_hub_cache_roots", return_value=[secret_root]):
        with patch("os.listdir", side_effect=OSError(f"Failed reading {secret_root}")):
            with caplog.at_level(logging.DEBUG, logger="omnivoice.setup.models"):
                result = models_module._scan_cache_on_disk()

    assert result == {}
    assert "Could not list hub cache root" in caplog.text
    assert "sensitive_user" not in caplog.text
