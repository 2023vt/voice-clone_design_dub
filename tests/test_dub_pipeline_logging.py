import asyncio
import logging
import os
from unittest.mock import MagicMock, patch
import pytest

from core import voice_leases
from services import dub_pipeline


def test_job_dir_referenced_by_others_db_error_logs_debug_and_scrubs(caplog, monkeypatch):
    secret_dir = "/home/sensitive_user/db.sqlite3"

    def mock_db_conn():
        raise RuntimeError(f"Database corrupted at {secret_dir}")

    monkeypatch.setattr(dub_pipeline, "db_conn", mock_db_conn)

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        holders = dub_pipeline.job_dir_referenced_by_others("job-123")

    assert holders == []
    assert "sensitive_user" not in caplog.text
    assert "Failed querying dub_history for referenced sources" in caplog.text


def test_discard_reference_run_scandir_error_logs_debug(caplog, monkeypatch, tmp_path):
    refs_dir = tmp_path / "refs"
    run_dir = refs_dir / "run1"
    run_dir.mkdir(parents=True)

    secret_path = str(run_dir)

    monkeypatch.setattr(
        os,
        "scandir",
        MagicMock(side_effect=OSError(f"Failed scanning {secret_path}")),
    )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        dub_pipeline.discard_reference_run(str(run_dir), None)

    assert "Failed scanning run_dir" in caplog.text


def test_discard_reference_run_entry_and_rmdir_error_logs_debug(caplog, monkeypatch, tmp_path):
    refs_dir = tmp_path / "refs"
    run_dir = refs_dir / "run1"
    run_dir.mkdir(parents=True)

    fake_entry = MagicMock()
    fake_entry.is_file.return_value = True
    fake_entry.path = str(run_dir / "leased.wav")

    monkeypatch.setattr(os, "scandir", lambda p: [fake_entry])
    monkeypatch.setattr(voice_leases, "remove_if_unused", MagicMock(side_effect=OSError("locked")))
    monkeypatch.setattr(os, "rmdir", MagicMock(side_effect=OSError("dir not empty")))

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        dub_pipeline.discard_reference_run(str(run_dir), None)

    assert "Failed inspecting entry for lease removal" in caplog.text
    assert "Failed removing run_dir" in caplog.text


@pytest.mark.asyncio
async def test_run_proc_streaming_stderr_kill_and_close_exceptions_logged(caplog, monkeypatch):
    from unittest.mock import AsyncMock

    real_wait_for = asyncio.wait_for

    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.kill.side_effect = RuntimeError("Failed kill /home/sensitive_user/pid")
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.communicate = AsyncMock(return_value=(b"", b"sample error output\n"))
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.close.side_effect = OSError("Pipe broken /home/sensitive_user/pipe")

    async def mock_wait_for(fut, timeout=None):
        if timeout == 5.0:
            if asyncio.iscoroutine(fut):
                fut.close()
            raise asyncio.TimeoutError()
        return await real_wait_for(fut, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", mock_wait_for)
    monkeypatch.setattr(dub_pipeline, "register_proc", lambda *args: None)
    monkeypatch.setattr(dub_pipeline, "unregister_proc", lambda *args: None)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
            events = []
            async for ev in dub_pipeline.run_proc_streaming_stderr("job-1", ["ffmpeg", "-version"], timeout=0.1):
                events.append(ev)

    assert "kill failed for process" in caplog.text
    assert "Timed out waiting 5s for process to terminate" in caplog.text
    assert "stdout close failed for process" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_probe_codecs_error_logs_debug_and_scrubs(caplog, monkeypatch):
    monkeypatch.setattr(dub_pipeline, "find_ffprobe", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        dub_pipeline.subprocess,
        "run",
        MagicMock(side_effect=RuntimeError("probe error at /home/sensitive_user/video.mp4")),
    )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        vc, ac = dub_pipeline._probe_codecs("/home/sensitive_user/video.mp4")

    assert (vc, ac) == ("", "")
    assert "Failed probing codecs for" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_ensure_browser_playable_mp4_remove_failure_logs_debug(caplog, monkeypatch, tmp_path):
    vid = tmp_path / "vid.avi"
    vid.write_bytes(b"dummy")

    monkeypatch.setattr(dub_pipeline, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    res = MagicMock()
    res.returncode = 0
    monkeypatch.setattr(dub_pipeline.subprocess, "run", lambda *a, **kw: res)
    monkeypatch.setattr(dub_pipeline.os.path, "exists", lambda p: True)

    secret_path = str(vid)
    monkeypatch.setattr(
        os,
        "remove",
        MagicMock(side_effect=OSError(f"permission denied on {secret_path}")),
    )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        target = dub_pipeline._ensure_browser_playable_mp4(secret_path)

    assert "Could not remove original video after transcoding" in caplog.text


def test_delete_cookie_export_error_logs_debug_and_scrubs(caplog, monkeypatch):
    secret_cookie = "/home/sensitive_user/secret_cookies.txt"
    monkeypatch.setattr(
        os,
        "unlink",
        MagicMock(side_effect=OSError(f"Failed unlinking {secret_cookie}")),
    )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        result = dub_pipeline._delete_cookie_export(secret_cookie)

    assert result is False
    assert "Failed removing cookie export file" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_parse_vtt_segments_oserror_logs_debug_and_scrubs(caplog):
    secret_path = "/home/sensitive_user/captions.vtt"

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        segs = dub_pipeline.parse_vtt_segments(secret_path)

    assert segs == []
    assert "Failed opening WebVTT file" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_parse_vtt_segments_invalid_timestamp_part_logs_debug(caplog, tmp_path):
    vtt = tmp_path / "captions.vtt"
    vtt.write_text(
        "WEBVTT\n\n1\n00:invalid:01.000 --> 00:00:04.000\nHello world\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        segs = dub_pipeline.parse_vtt_segments(str(vtt))

    assert len(segs) == 1
    assert "Invalid timestamp part in" in caplog.text


def test_parse_vtt_segments_malformed_arrow_line_logs_debug(caplog, tmp_path):
    vtt = tmp_path / "captions_bad.vtt"
    vtt.write_text(
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000 --> 00:00:03.000\nBroken cue\n\n2\n00:00:04.000 --> 00:00:05.000\nValid cue\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.DEBUG, logger="omnivoice.dub_pipeline"):
        segs = dub_pipeline.parse_vtt_segments(str(vtt))

    assert len(segs) == 1
    assert segs[0]["text"] == "Valid cue"
    assert "Skipping malformed WebVTT timestamp line" in caplog.text
