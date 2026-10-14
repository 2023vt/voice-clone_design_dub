"""Unit tests for SoniTranslate subprocess stdout draining and process termination."""
import asyncio
import collections
import io
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services import sonitranslate


def test_drain_output_reads_lines_into_ring_buffer():
    lines = [b"Line 1\n", b"Line 2\n", b"Line 3\n"]
    mock_stdout = io.BytesIO(b"".join(lines))
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.stdout = mock_stdout

    tail = collections.deque(maxlen=2)
    sonitranslate._drain_output(mock_proc, tail)

    assert list(tail) == ["Line 2", "Line 3"]


def test_stop_terminates_and_cleans_up():
    async def _run():
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.stdout = MagicMock()
        mock_proc.wait = MagicMock(return_value=0)

        sonitranslate._proc = mock_proc
        result = await sonitranslate.stop()

        assert result["stopped"] is True
        assert sonitranslate._proc is None
        mock_proc.terminate.assert_called_once()
        mock_proc.stdout.close.assert_called_once()

    asyncio.run(_run())


def test_start_cleans_up_on_early_exit(monkeypatch):
    async def _run():
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll = MagicMock(return_value=1)
        mock_proc.stdout = io.BytesIO(b"Failed to import torch\n")

        monkeypatch.setattr(sonitranslate, "is_installed", lambda: True)
        monkeypatch.setattr(sonitranslate, "is_running", lambda: False)
        monkeypatch.setattr(sonitranslate, "is_venv_ready", lambda: False)
        monkeypatch.setattr(sonitranslate.subprocess, "Popen", lambda *args, **kwargs: mock_proc)

        with pytest.raises(RuntimeError, match="SoniTranslate exited early"):
            await sonitranslate.start()

        assert sonitranslate._proc is None

    asyncio.run(_run())
