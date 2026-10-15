"""Cloning from several samples: merge into one composite reference."""
import asyncio
import io
import os

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi import FastAPI

SR = 16000


def _speech(seconds: float, *, amp: float, pauses_every: float = 1.2, noise: float = 0.0,
            seed: int = 0) -> np.ndarray:
    """Tone bursts separated by 0.3 s pauses — enough structure for the cutter."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    audio = amp * np.sin(2 * np.pi * 180 * t)
    period = pauses_every + 0.3
    audio[(t % period) > pauses_every] = 0.0
    audio += noise * rng.standard_normal(audio.size)
    lead = np.zeros(int(0.5 * SR))
    return np.concatenate([lead, audio, lead]).astype(np.float32)


def _write(path, audio, sr=SR):
    sf.write(path, audio, sr)
    return str(path)


def test_merge_combines_every_sample_under_the_transcript_limit(tmp_path):
    from services import reference_merge as rm

    paths = [
        _write(tmp_path / "a.wav", _speech(30, amp=0.5, seed=1)),
        _write(tmp_path / "b.wav", _speech(30, amp=0.05, seed=2)),
        _write(tmp_path / "c.wav", _speech(30, amp=0.3, noise=0.01, seed=3), sr=44100),
    ]
    out = tmp_path / "merged.wav"
    seconds = rm.merge_references(paths, str(out))

    audio, sr = sf.read(out)
    assert sr == rm.TARGET_SAMPLE_RATE
    assert audio.ndim == 1
    assert 3 * rm.MIN_PASSAGE_SECONDS < seconds <= rm.MERGED_MAX_SECONDS
    assert abs(len(audio) / sr - seconds) < 0.01
    # Loudness matched: the quiet sample is no longer 20 dB below the loud one.
    frame = int(0.5 * sr)
    levels = [np.sqrt(np.mean(audio[i:i + frame] ** 2)) for i in range(0, len(audio) - frame, frame)]
    voiced = [lvl for lvl in levels if lvl > 0.01]
    assert max(voiced) / min(voiced) < 3


def test_merge_cuts_on_pauses_not_mid_burst(tmp_path):
    from services import reference_merge as rm

    paths = [_write(tmp_path / f"{i}.wav", _speech(20, amp=0.4, seed=i)) for i in range(2)]
    out = tmp_path / "merged.wav"
    rm.merge_references(paths, str(out))
    audio, sr = sf.read(out)
    edge = int(0.01 * sr)
    # Composite starts and ends in a pause, not inside a tone burst.
    assert np.max(np.abs(audio[:edge])) < 0.05
    assert np.max(np.abs(audio[-edge:])) < 0.05


def test_merge_needs_two_samples_with_speech(tmp_path):
    from services import reference_merge as rm

    paths = [
        _write(tmp_path / "speech.wav", _speech(5, amp=0.4)),
        _write(tmp_path / "silence.wav", np.zeros(SR * 3, dtype=np.float32)),
    ]
    with pytest.raises(rm.ReferenceMergeError):
        rm.merge_references(paths, str(tmp_path / "out.wav"))
    assert not (tmp_path / "out.wav").exists()


def test_merge_rejects_too_many_samples(tmp_path):
    from services import reference_merge as rm

    with pytest.raises(rm.ReferenceMergeError):
        rm.merge_references(["x.wav"] * (rm.MAX_SAMPLES + 1), str(tmp_path / "out.wav"))


@pytest.fixture
def client_app(tmp_path, monkeypatch):
    from api.routers import profiles
    from core import db

    voices = tmp_path / "voices"
    monkeypatch.setattr(profiles, "VOICES_DIR", str(voices))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "profiles.db"))
    monkeypatch.setattr(profiles.event_bus, "emit", lambda *_a: None)
    transcribed = []

    async def fake_transcribe(path):
        transcribed.append(path)
        return "merged words"

    monkeypatch.setattr(profiles, "_auto_transcribe_reference", fake_transcribe)
    db.init_db()
    app = FastAPI()
    app.include_router(profiles.router)
    return app, voices, transcribed


def _post(app, files, data=None):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
            return await http.post("/profiles", data={"name": "Multi", **(data or {})}, files=files)

    return asyncio.run(run())


def _wav_bytes(audio) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, SR, format="WAV")
    return buf.getvalue()


def test_create_profile_from_several_samples(client_app):
    app, voices, transcribed = client_app
    files = [
        ("ref_audio", ("one.wav", _wav_bytes(_speech(8, amp=0.4, seed=1)), "audio/wav")),
        ("extra_ref_audio", ("two.wav", _wav_bytes(_speech(8, amp=0.2, seed=2)), "audio/wav")),
        ("extra_ref_audio", ("three.wav", _wav_bytes(_speech(8, amp=0.3, seed=3)), "audio/wav")),
    ]
    response = _post(app, files, {"ref_text": "words of only the first clip"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ref_audio_path"] == f"{body['id']}.wav"
    # The typed transcript described one clip; the composite is transcribed.
    assert body["ref_text"] == "merged words"
    assert transcribed == [str(voices / body["ref_audio_path"])]
    # Only the composite remains; staged samples are cleaned up.
    assert sorted(os.listdir(voices)) == [body["ref_audio_path"]]


def test_failed_merge_leaves_no_files_or_row(client_app):
    app, voices, _ = client_app
    silence = _wav_bytes(np.zeros(SR * 2, dtype=np.float32))
    files = [
        ("ref_audio", ("one.wav", _wav_bytes(_speech(5, amp=0.4)), "audio/wav")),
        ("extra_ref_audio", ("two.wav", silence, "audio/wav")),
    ]
    response = _post(app, files)
    assert response.status_code == 422
    assert "two of the samples" in response.json()["detail"]
    assert os.listdir(voices) == []
    from core.db import db_conn

    with db_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM voice_profiles WHERE name='Multi'").fetchone()[0] == 0


def test_single_sample_save_is_unchanged(client_app):
    app, voices, _ = client_app
    files = {"ref_audio": ("voice.wav", _wav_bytes(_speech(4, amp=0.4)), "audio/wav")}
    response = _post(app, files, {"ref_text": "typed"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ref_text"] == "typed"
    assert body["ref_audio_path"] == f"{body['id']}.wav"
