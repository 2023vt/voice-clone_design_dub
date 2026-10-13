"""Preview lossless compaction of adjacent subtitle cues."""

from fastapi import APIRouter

from schemas.subtitle_compaction import (
    SubtitleCompactionOptions,
    SubtitleCompactionRequest,
    SubtitleCompactionResponse,
)
from services.subtitle_compaction import compact_subtitle_cues


router = APIRouter(prefix="/subtitles/compaction", tags=["subtitles"])


@router.post("/preview", response_model=SubtitleCompactionResponse)
def preview_subtitle_compaction(
    request: SubtitleCompactionRequest,
) -> SubtitleCompactionResponse:
    options = request.options
    if request.compact and options is None:
        # Compatibility with clients that predate structured options.
        options = SubtitleCompactionOptions(max_gap_ms=500)

    return SubtitleCompactionResponse(
        cues=compact_subtitle_cues(request.cues, options)
    )
