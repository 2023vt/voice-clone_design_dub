"""Models for deterministic subtitle-cue compaction previews."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


DEFAULT_MAX_GAP_MS = 100


class SubtitleCompactionOptions(BaseModel):
    max_gap_ms: int | None = Field(default=None, ge=0, le=10_000)
    max_duration_ms: int = Field(default=7_000, gt=0, le=60_000)
    same_speaker_only: bool = True
    separator: Literal[" ", "\n"] = " "


class SubtitleCue(BaseModel):
    id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1)
    speaker: str | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "SubtitleCue":
        if self.end_ms <= self.start_ms:
            raise ValueError("subtitle cue must end after it starts")
        return self


class SubtitleCompactionRequest(BaseModel):
    cues: list[SubtitleCue]
    options: SubtitleCompactionOptions | None = None
    compact: bool = False


class SubtitleCompactionResponse(BaseModel):
    cues: list[SubtitleCue]
