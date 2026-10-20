"""Stems must share the exported track's fitted timeline."""
import asyncio
import importlib.util
import io
from pathlib import Path
import sys
import types
import zipfile
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def export_module(monkeypatch):
    # Job-store boundary only: importing dub_core also loads unrelated engines.
    core = types.ModuleType("api.routers.dub_core")
    core._get_job = lambda job_id: None
    core._safe_lang_or_400 = lambda lang: lang
    monkeypatch.setitem(sys.modules, "api.routers.dub_core", core)
    path = Path(__file__).parents[1] / "backend/api/routers/dub_export.py"
    spec = importlib.util.spec_from_file_location("stems_export_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stems_zip_uses_the_same_retimed_background_as_playback(export_module, monkeypatch, tmp_path):
    module = export_module
    vocals = tmp_path / "voice.wav"
    original_bed = tmp_path / "original.wav"
    fitted_bed = tmp_path / "fitted.wav"
    for path in (vocals, original_bed, fitted_bed):
        path.write_bytes(path.stem.encode())
    job = {"dubbed_tracks": {"de": {"path": str(vocals), "timing_strategy": "smart_fit"}},
           "no_vocals_path": str(original_bed), "filename": "interview.mp4",
           "fit_plans": {"de": {"plan": [{"orig_start": 0, "orig_end": 1, "stretch_ratio": 2}]}}}
    monkeypatch.setattr(module, "_job_dir_or_400", lambda _: str(tmp_path))
    monkeypatch.setattr(module, "_get_job", lambda _: job)
    monkeypatch.setattr(module, "_dub_artifact", lambda value, *a, **kw: value)
    monkeypatch.setattr(module, "_optional_dub_artifact", lambda value, *a: value)
    prepare = AsyncMock(return_value=str(fitted_bed))
    monkeypatch.setattr(module, "_preserved_background", prepare)
    response = asyncio.run(module.dub_export_stems("job", lang="de"))
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert archive.read("background_original.wav") == b"fitted"
        assert archive.read("vocals_dubbed_de.wav") == b"voice"
    prepare.assert_awaited_once_with(job, "job", "de")


def test_stems_without_separated_background_still_export_vocals(export_module, monkeypatch, tmp_path):
    module = export_module
    vocals = tmp_path / "voice.wav"
    vocals.write_bytes(b"voice")
    job = {"dubbed_tracks": {"de": {"path": str(vocals)}}}
    monkeypatch.setattr(module, "_job_dir_or_400", lambda _: str(tmp_path))
    monkeypatch.setattr(module, "_get_job", lambda _: job)
    monkeypatch.setattr(module, "_dub_artifact", lambda value, *a, **kw: value)
    prepare = AsyncMock()
    monkeypatch.setattr(module, "_preserved_background", prepare)
    response = asyncio.run(module.dub_export_stems("job", lang="de"))
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert archive.namelist() == ["vocals_dubbed_de.wav"]
    prepare.assert_not_awaited()
