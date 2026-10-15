"""A video can be a clone reference: its audio track is stored as WAV."""
import os
import subprocess

import numpy as np
import pytest
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.ffmpeg_utils import find_ffmpeg

FFMPEG = find_ffmpeg()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg required to build test videos")


def _video(path, *, audio=True, seconds=6.0, seed=0) -> bytes:
    """A tiny MP4 (black frames) with a speech-like tone-burst audio track."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"color=c=black:s=64x64:d={seconds}"]
    if audio:
        sr = 16000
        t = np.arange(int(seconds * sr)) / sr
        tone = 0.4 * np.sin(2 * np.pi * (170 + 10 * seed) * t)
        tone[(t % 1.5) > 1.2] = 0.0
        wav = f"{path}.src.wav"
        sf.write(wav, tone.astype(np.float32), sr)
        cmd += ["-i", wav, "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return open(path, "rb").read()


@pytest.fixture
def env(tmp_path, monkeypatch):
    from api.routers import profiles
    from core import db

    voices = tmp_path / "voices"
    monkeypatch.setattr(profiles, "VOICES_DIR", str(voices))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "profiles.db"))
    monkeypatch.setattr(profiles.event_bus, "emit", lambda *_a: None)
    transcribed = []

    async def fake_transcribe(path):
        transcribed.append(path)
        return "auto transcript"

    monkeypatch.setattr(profiles, "_auto_transcribe_reference", fake_transcribe)
    db.init_db()
    app = FastAPI()
    app.include_router(profiles.router)
    return TestClient(app), voices, tmp_path, transcribed


def _is_mono_wav(path) -> bool:
    info = sf.info(str(path))
    return info.format == "WAV" and info.channels == 1 and info.frames > 0


def test_video_reference_is_stored_as_audio(env):
    client, voices, tmp, transcribed = env
    clip = _video(tmp / "talk.mp4")
    response = client.post(
        "/profiles", data={"name": "From video"},
        files={"ref_audio": ("talk.mp4", clip, "video/mp4")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ref_audio_path"] == f"{body['id']}.wav"
    assert _is_mono_wav(voices / body["ref_audio_path"])
    # Transcribed from the extracted audio; the video itself is not kept.
    assert transcribed == [str(voices / body["ref_audio_path"])]
    assert sorted(os.listdir(voices)) == [body["ref_audio_path"]]


def test_video_without_audio_is_refused_and_leaves_nothing(env):
    client, voices, tmp, _ = env
    from core.failure import NoAudioTrackError

    clip = _video(tmp / "silent.mp4", audio=False)
    # main.py maps NoAudioTrackError to its user-facing response.
    with pytest.raises(NoAudioTrackError):
        client.post(
            "/profiles", data={"name": "Mute"},
            files={"ref_audio": ("silent.mp4", clip, "video/mp4")},
        )
    assert os.listdir(voices) == []


def test_videos_can_be_merged_as_samples(env):
    client, voices, tmp, _ = env
    files = [
        ("ref_audio", ("one.mp4", _video(tmp / "one.mp4", seed=1), "video/mp4")),
        ("extra_ref_audio", ("two.mov", _video(tmp / "two.mov", seed=2), "video/quicktime")),
    ]
    response = client.post("/profiles", data={"name": "Mixed"}, files=files)
    assert response.status_code == 200, response.text
    body = response.json()
    assert _is_mono_wav(voices / body["ref_audio_path"])
    assert sorted(os.listdir(voices)) == [body["ref_audio_path"]]


def test_replace_accepts_a_video(env):
    client, voices, tmp, _ = env
    created = client.post(
        "/profiles", data={"name": "Swap"},
        files={"ref_audio": ("first.mp4", _video(tmp / "first.mp4"), "video/mp4")},
    ).json()
    response = client.put(
        f"/profiles/{created['id']}/audio",
        files={"ref_audio": ("second.mkv", _video(tmp / "second.mkv", seed=3), "video/x-matroska")},
    )
    assert response.status_code == 200, response.text
    new_name = response.json()["ref_audio_path"]
    assert new_name.startswith(f"{created['id']}-") and new_name.endswith(".wav")
    assert _is_mono_wav(voices / new_name)
    assert not [n for n in os.listdir(voices) if ".part" in n or n.endswith((".mkv", ".mp4"))]


def test_one_shot_video_reference_reaches_the_engine_as_audio(tmp_path, monkeypatch):
    """A video used without saving is passed to the engine as its audio track."""
    import importlib

    import torch
    from fastapi.testclient import TestClient

    os.environ.setdefault("OMNIVOICE_MODEL", "test")
    tts = importlib.import_module("services.tts_backend")
    seen = {}

    class _Engine(tts.TTSBackend):
        id = "fake-video-ref"
        display_name = "Video reference engine (test)"
        supports_cloning = True
        applies_own_mastering = False
        gpu_compat = ("cpu",)

        @property
        def sample_rate(self) -> int:
            return 24000

        @property
        def supported_languages(self) -> list[str]:
            return ["multi"]

        @classmethod
        def is_available(cls):
            return True, "ready"

        def generate(self, text, **kw) -> torch.Tensor:
            ref = kw.get("ref_audio")
            seen["ref"] = ref
            seen["wav"] = bool(ref) and _is_mono_wav(ref)
            return torch.zeros(1, 2400)

    monkeypatch.setitem(tts._REGISTRY, _Engine.id, _Engine)
    asr = importlib.import_module("services.asr_backend")
    monkeypatch.setattr(asr, "transcribe_reference", lambda *a, **k: None)
    from main import app

    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.post(
        "/generate",
        data={"text": "Hello there.", "engine": _Engine.id, "ref_text": "hello"},
        files={"ref_audio": ("clip.mp4", _video(tmp_path / "clip.mp4"), "video/mp4")},
    )
    assert response.status_code == 200, response.text
    assert str(seen["ref"]).endswith(".wav")
    assert seen["wav"]
