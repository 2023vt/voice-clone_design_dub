"""Unit tests verifying stderr drain thread cleanup across subprocess sidecar lifecycle."""
import collections
import io
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_torch_if_missing(monkeypatch):
    if "torch" not in sys.modules:
        mock_t = MagicMock()
        mock_t.cuda.is_available.return_value = False
        monkeypatch.setitem(sys.modules, "torch", mock_t)


def _get_dummy_sidecar_class():
    from services.subprocess_backend import SubprocessBackend

    class DummySidecar(SubprocessBackend):
        id = "dummy"
        display_name = "Dummy Sidecar"

        @classmethod
        def venv_python(cls):
            return "/bin/python3"

        @classmethod
        def sidecar_script(cls):
            from pathlib import Path
            return Path("/tmp/dummy.py")

        @property
        def sample_rate(self):
            return 24000

        @property
        def supported_languages(self):
            return ["en"]

        @classmethod
        def is_available(cls):
            return True, "ok"

    return DummySidecar


def test_join_stderr_thread_closes_stderr_and_joins_alive_thread():
    DummySidecar = _get_dummy_sidecar_class()
    backend = DummySidecar()
    mock_stderr = MagicMock()
    mock_proc = MagicMock()
    mock_proc.stderr = mock_stderr

    started_event = threading.Event()
    stop_event = threading.Event()

    def fake_drain():
        started_event.set()
        stop_event.wait(timeout=2.0)

    thread = threading.Thread(target=fake_drain, daemon=True)
    backend._stderr_thread = thread
    thread.start()
    started_event.wait(timeout=1.0)
    assert thread.is_alive()

    # Trigger stop and join
    stop_event.set()
    backend._join_stderr_thread(mock_proc, timeout=1.0)

    mock_stderr.close.assert_called_once()
    assert not thread.is_alive()
    assert backend._stderr_thread is None


def test_force_kill_cleans_up_stderr_thread():
    DummySidecar = _get_dummy_sidecar_class()
    backend = DummySidecar()
    mock_stderr = MagicMock()
    mock_proc = MagicMock()
    mock_proc.stderr = mock_stderr
    mock_proc.kill = MagicMock()
    mock_proc.wait = MagicMock(return_value=0)

    backend._proc = mock_proc

    mock_thread = MagicMock()
    mock_thread.is_alive.side_effect = [True, False]
    backend._stderr_thread = mock_thread

    backend._force_kill()

    assert backend._proc is None
    assert backend._stderr_thread is None
    mock_stderr.close.assert_called_once()
    mock_thread.join.assert_called_once()


def test_shutdown_cleans_up_stderr_thread():
    DummySidecar = _get_dummy_sidecar_class()
    backend = DummySidecar()
    mock_stderr = MagicMock()
    mock_proc = MagicMock()
    mock_proc.stderr = mock_stderr
    mock_proc.wait = MagicMock(return_value=0)

    backend._proc = mock_proc

    mock_thread = MagicMock()
    mock_thread.is_alive.side_effect = [True, False]
    backend._stderr_thread = mock_thread

    backend.shutdown()

    assert backend._proc is None
    assert backend._stderr_thread is None
    mock_stderr.close.assert_called_once()
    mock_thread.join.assert_called_once()


def test_join_stderr_thread_retains_reference_on_timeout():
    DummySidecar = _get_dummy_sidecar_class()
    backend = DummySidecar()
    mock_stderr = MagicMock()
    mock_proc = MagicMock()
    mock_proc.stderr = mock_stderr

    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True
    backend._stderr_thread = mock_thread

    backend._join_stderr_thread(mock_proc, timeout=0.1)

    mock_stderr.close.assert_called_once()
    mock_thread.join.assert_called_once_with(timeout=0.1)
    # The reference is retained because the thread is still running
    assert backend._stderr_thread is mock_thread


def test_drain_stderr_closes_stderr_in_finally():
    DummySidecar = _get_dummy_sidecar_class()
    backend = DummySidecar()
    tail = collections.deque()
    mock_stderr = MagicMock()
    mock_stderr.readline = MagicMock(return_value=b"")
    mock_proc = MagicMock()
    mock_proc.stderr = mock_stderr

    backend._drain_stderr(mock_proc, tail)

    mock_stderr.close.assert_called_once()
