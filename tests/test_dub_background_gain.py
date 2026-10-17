"""Background volume reaches real media exports and immutable preview caches."""
from __future__ import annotations

import asyncio
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routers import dub_core, dub_export


@pytest.fixture
def media_client(tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg required for real media mix regression")
    monkeypatch.setenv("FFMPEG_PATH", ffmpeg)
    monkeypatch.setattr(dub_export, "DUB_DIR", str(tmp_path))
    job_id = "gain_fixture"
    folder = tmp_path / job_id
    folder.mkdir()
    def tone(name, frequency, amplitude):
        path = folder / name
        with wave.open(str(path), "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(48000)
            out.writeframes(b"".join(struct.pack("<hh", *([round(32767 * amplitude * math.sin(
                2 * math.pi * frequency * i / 48000))] * 2)) for i in range(48000)))
        return str(path)
    bed = tone("background.wav", 400, .02)
    voice = tone("dubbed_es.wav", 1000, .03)
    video = str(folder / "source.mp4")
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=32x32:r=10:d=1",
                    "-i", bed, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", video],
                   check=True, timeout=15)
    job = {
        "video_path": video, "audio_path": bed, "no_vocals_path": bed,
        "duration": 1., "filename": "source.mp4", "segments": [{"start": .2, "end": .8}],
        "dubbed_tracks": {"es": {"path": voice, "language": "Spanish", "language_code": "es"}},
    }
    monkeypatch.setitem(dub_core._dub_jobs, job_id, job)
    app = FastAPI()
    app.include_router(dub_export.router)
    with TestClient(app) as client:
        yield client, job, folder, ffmpeg


def amplitude(data, folder, ffmpeg, frequency):
    path = folder / "measured-media"
    path.write_bytes(data)
    raw = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0",
                                   "-ar", "48000", "-ac", "2", "-f", "f32le", "pipe:1"], timeout=15)
    values = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)[4800:38400, 0]
    angles = np.arange(len(values)) * (2 * math.pi * frequency / 48000)
    return 2 * abs(np.sum(values * np.exp(-1j * angles))) / len(values)


@pytest.mark.parametrize("kind", ["video", "audio-only", "preview", "wav", "mp3"])
@pytest.mark.parametrize("gain", [0, 1, 2, 4])
def test_real_export_applies_background_gain(media_client, kind, gain):
    client, job, folder, ffmpeg = media_client
    endpoint = {"video": "download", "audio-only": "download", "preview": "preview-video",
                "wav": "download-audio", "mp3": "download-mp3"}[kind]
    if kind == "audio-only":
        job["input_type"] = "audio"
    response = client.get(f"/dub/{endpoint}/gain_fixture", params={
        "lang": "es", "default_track": "es", "include_tracks": "es",
        "out_format": "wav", "bed_gain": gain,
    })
    assert response.status_code == 200, response.text
    assert amplitude(response.content, folder, ffmpeg, 400) == pytest.approx(.02 * gain, rel=.04, abs=.0003)
    assert amplitude(response.content, folder, ffmpeg, 1000) == pytest.approx(.033, abs=.003)


@pytest.mark.parametrize("endpoint", ["download", "preview-video", "download-audio", "download-mp3"])
@pytest.mark.parametrize("gain", ["nan", "inf", "-inf", "-0.1", "4.1", "loud"])
def test_invalid_gain_is_rejected_before_job_lookup(endpoint, gain):
    app = FastAPI()
    app.include_router(dub_export.router)
    with TestClient(app) as client:
        response = client.get(f"/dub/{endpoint}/missing-job", params={"lang": "es", "bed_gain": gain})
    assert response.status_code == 422, response.text
    assert any(error["loc"][-1] == "bed_gain" for error in response.json()["detail"])


def test_default_and_background_off_preserve_existing_audio(media_client):
    client, _, folder, ffmpeg = media_client
    base = "/dub/download-audio/gain_fixture?lang=es"
    default = client.get(base)
    explicit = client.get(base + "&bed_gain=1")
    assert default.status_code == explicit.status_code == 200
    assert default.content == explicit.content
    dry = client.get(base + "&preserve_bg=false&bed_gain=4")
    assert dry.status_code == 200
    assert amplitude(dry.content, folder, ffmpeg, 400) < .0001
    assert amplitude(dry.content, folder, ffmpeg, 1000) == pytest.approx(.03, abs=.0002)


def test_preview_gain_has_independent_cache_and_head_does_not_mux(media_client):
    client, _, folder, _ = media_client
    url = "/dub/preview-video/gain_fixture?lang=es"
    assert client.head(url + "&bed_gain=2").status_code == 200
    assert not list((folder / "exports").glob("preview*.mp4"))
    assert client.get(url).status_code == 200
    assert client.get(url + "&bed_gain=2").status_code == 200
    before = {p.name: p.stat().st_mtime_ns for p in (folder / "exports").glob("preview*.mp4")}
    assert len(before) == 2
    assert client.get(url + "&bed_gain=2").status_code == 200
    assert before == {p.name: p.stat().st_mtime_ns for p in (folder / "exports").glob("preview*.mp4")}
    assert client.get(url + "&bed_gain=2.0000001").status_code == 200
    assert len(list((folder / "exports").glob("preview*.mp4"))) == 3


def test_wav_mix_gain_cache_retains_leased_other_gain(media_client):
    _, job, folder, _ = media_client
    exports = folder / "exports"
    exports.mkdir(exist_ok=True)
    async def run():
        args = (str(exports), "es", job["no_vocals_path"], job["dubbed_tracks"]["es"]["path"])
        normal = await dub_export._mixed_dub_audio(*args)
        louder = await dub_export._mixed_dub_audio(*args, bed_gain=2)
        assert normal != louder
        assert Path(normal).exists()  # still leased by a previous reader
        again = await dub_export._mixed_dub_audio(*args, bed_gain=2.)
        assert again == louder
        for path in [normal, louder, again]:
            dub_export._release_mix(path)
        assert not Path(normal).exists()
        assert Path(louder).is_file()
    asyncio.run(run())


def test_decoder_measures_known_stereo_tones_without_mono_downmix_gain(media_client):
    _, job, folder, ffmpeg = media_client
    for path, frequency, level in [(job["audio_path"], 400, .02),
                                   (job["dubbed_tracks"]["es"]["path"], 1000, .03)]:
        data = Path(path).read_bytes()
        assert amplitude(data, folder, ffmpeg, frequency) == pytest.approx(level, abs=.0001)
