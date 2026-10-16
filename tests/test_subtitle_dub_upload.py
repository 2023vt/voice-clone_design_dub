"""Subtitle-first jobs preserve cue timing without requiring source media."""
import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile


@pytest.mark.parametrize(
    "name,content",
    [
        ("lines.srt", "1\n00:00:01,000 --> 00:00:02,000\nHello\n"),
        ("lines.vtt", "WEBVTT\n\n00:01.000 --> 00:02.000\nHello\n"),
    ],
)
def test_subtitle_upload_creates_audio_only_job(monkeypatch, tmp_path, name, content):
    from api.routers import dub_core

    jobs = {}
    monkeypatch.setattr(dub_core, "_safe_job_dir", lambda job_id: str(tmp_path / job_id))
    monkeypatch.setattr(
        dub_core.dub_pipeline,
        "put_and_save_job",
        lambda job_id, job, **kwargs: jobs.setdefault(job_id, job) is job,
    )
    result = asyncio.run(
        dub_core.dub_upload_subtitles(UploadFile(filename=name, file=BytesIO(content.encode())))
    )
    job = jobs[result["job_id"]]
    assert job["input_type"] == "subtitle"
    assert job["audio_path"] is None and job["video_path"] is None
    assert result["segments"][0]["start"] == 1
    assert result["duration"] == 2


def test_subtitle_upload_rejects_invalid_file(monkeypatch, tmp_path):
    from api.routers import dub_core

    monkeypatch.setattr(dub_core, "_safe_job_dir", lambda job_id: str(tmp_path / job_id))
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            dub_core.dub_upload_subtitles(
                UploadFile(filename="empty.vtt", file=BytesIO(b"WEBVTT\n"))
            )
        )
    assert error.value.status_code == 400
    assert not list(tmp_path.iterdir())
