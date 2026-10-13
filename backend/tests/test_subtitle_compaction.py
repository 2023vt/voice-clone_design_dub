"""Unit and API contracts for subtitle-cue compaction."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.routers.subtitle_compaction import router
from schemas.subtitle_compaction import (
    DEFAULT_MAX_GAP_MS,
    SubtitleCompactionOptions,
    SubtitleCue,
)
from services.subtitle_compaction import compact_subtitle_cues


@pytest.fixture
def cues() -> list[SubtitleCue]:
    return [
        SubtitleCue(id="a", start_ms=0, end_ms=1_000, text="Hello", speaker="A"),
        SubtitleCue(id="b", start_ms=1_200, end_ms=2_000, text="world", speaker="A"),
        SubtitleCue(id="c", start_ms=2_400, end_ms=3_000, text="Again", speaker="A"),
    ]


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_default_subtitle_compaction_gap() -> None:
    assert DEFAULT_MAX_GAP_MS == 250


def test_subtitle_compaction_uses_documented_defaults(
    cues: list[SubtitleCue],
) -> None:
    compacted = compact_subtitle_cues(cues)
    assert [(cue.id, cue.text) for cue in compacted] == [
        ("a", "Hello world"),
        ("c", "Again"),
    ]


def test_empty_compaction_options_use_defaults(cues: list[SubtitleCue]) -> None:
    compacted = compact_subtitle_cues(cues, SubtitleCompactionOptions())
    assert [(cue.id, cue.text) for cue in compacted] == [
        ("a", "Hello world"),
        ("c", "Again"),
    ]


def test_legacy_compact_flag_uses_shared_defaults(
    client: TestClient,
    cues: list[SubtitleCue],
) -> None:
    response = client.post(
        "/subtitles/compaction/preview",
        json={"cues": [cue.model_dump() for cue in cues], "compact": True},
    )

    assert response.status_code == 200
    assert [(cue["id"], cue["text"]) for cue in response.json()["cues"]] == [
        ("a", "Hello world"),
        ("c", "Again"),
    ]


def test_custom_gap_threshold_is_respected(cues: list[SubtitleCue]) -> None:
    options = SubtitleCompactionOptions(max_gap_ms=450)
    compacted = compact_subtitle_cues(cues, options)
    assert [(cue.id, cue.text) for cue in compacted] == [
        ("a", "Hello world Again")
    ]


def test_speaker_changes_prevent_merging() -> None:
    cues = [
        SubtitleCue(id="a", start_ms=0, end_ms=500, text="One", speaker="A"),
        SubtitleCue(id="b", start_ms=600, end_ms=900, text="Two", speaker="B"),
    ]
    options = SubtitleCompactionOptions(max_gap_ms=250)
    assert [cue.id for cue in compact_subtitle_cues(cues, options)] == ["a", "b"]


def test_maximum_duration_prevents_merging() -> None:
    cues = [
        SubtitleCue(id="a", start_ms=0, end_ms=900, text="One"),
        SubtitleCue(id="b", start_ms=1_000, end_ms=2_000, text="Two"),
    ]
    options = SubtitleCompactionOptions(max_gap_ms=250, max_duration_ms=1_500)
    assert [cue.id for cue in compact_subtitle_cues(cues, options)] == ["a", "b"]


def test_newline_separator_and_first_id_are_preserved() -> None:
    cues = [
        SubtitleCue(id="first", start_ms=0, end_ms=500, text="One"),
        SubtitleCue(id="second", start_ms=550, end_ms=900, text="Two"),
    ]
    options = SubtitleCompactionOptions(max_gap_ms=100, separator="\n")
    assert compact_subtitle_cues(cues, options) == [
        SubtitleCue(id="first", start_ms=0, end_ms=900, text="One\nTwo")
    ]


@pytest.mark.parametrize(
    "model, values",
    [
        (SubtitleCompactionOptions, {"max_gap_ms": -1}),
        (SubtitleCompactionOptions, {"max_duration_ms": 0}),
        (SubtitleCue, {"id": "a", "start_ms": 10, "end_ms": 10, "text": "x"}),
    ],
)
def test_invalid_compaction_input_is_rejected(model: type, values: dict) -> None:
    with pytest.raises(ValidationError):
        model(**values)


def test_compaction_options_have_json_serialization_coverage() -> None:
    options = SubtitleCompactionOptions(
        max_gap_ms=300,
        max_duration_ms=5_000,
        same_speaker_only=False,
        separator="\n",
    )
    assert json.loads(options.model_dump_json()) == {
        "max_gap_ms": 300,
        "max_duration_ms": 5_000,
        "same_speaker_only": False,
        "separator": "\n",
    }
