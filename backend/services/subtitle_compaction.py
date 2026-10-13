"""Compact adjacent subtitle cues without changing their source order."""

from __future__ import annotations

from schemas.subtitle_compaction import (
    DEFAULT_MAX_GAP_MS,
    SubtitleCompactionOptions,
    SubtitleCue,
)


def _can_merge(
    previous: SubtitleCue,
    current: SubtitleCue,
    *,
    options: SubtitleCompactionOptions,
    max_gap_ms: int,
) -> bool:
    gap_ms = current.start_ms - previous.end_ms
    if gap_ms < 0 or gap_ms > max_gap_ms:
        return False
    if current.end_ms - previous.start_ms > options.max_duration_ms:
        return False
    if options.same_speaker_only and previous.speaker != current.speaker:
        return False
    return True


def compact_subtitle_cues(
    cues: list[SubtitleCue],
    options: SubtitleCompactionOptions | None = None,
) -> list[SubtitleCue]:
    """Merge eligible adjacent cues while retaining the first cue's ID."""

    if options is None:
        options = SubtitleCompactionOptions(max_gap_ms=DEFAULT_MAX_GAP_MS)

    # An explicit options object supplies its own gap policy.
    max_gap_ms = options.max_gap_ms or 0
    compacted: list[SubtitleCue] = []

    for cue in cues:
        if not compacted or not _can_merge(
            compacted[-1],
            cue,
            options=options,
            max_gap_ms=max_gap_ms,
        ):
            compacted.append(cue.model_copy())
            continue

        previous = compacted[-1]
        compacted[-1] = previous.model_copy(
            update={
                "end_ms": cue.end_ms,
                "text": f"{previous.text}{options.separator}{cue.text}",
            }
        )

    return compacted
