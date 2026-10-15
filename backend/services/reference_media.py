"""Video files as clone references: keep only their audio track.

A reference is stored and passed to engines as audio, so engines, prompt
caches and playback never decode a video container.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Optional

from fastapi import HTTPException

from core.media_types import VIDEO_EXTS

# WebM stays as uploaded: it is the browser recorder's container and every
# engine path already decodes it.
VIDEO_REFERENCE_EXTS = VIDEO_EXTS - {".webm"}
EXTRACT_TIMEOUT_S = 300.0


def is_video_reference(ext: Optional[str]) -> bool:
    return bool(ext) and ext.lower() in VIDEO_REFERENCE_EXTS


async def extract_reference_audio(src: str, dest: str) -> None:
    """Write the first audio track of video ``src`` to mono WAV ``dest``.

    ffmpeg may open only local files, so a container that smuggles a playlist
    cannot make it fetch anything. Raises ``NoAudioTrackError`` for a video
    without sound and ``HTTPException`` for any other failure.
    """
    from services.ffmpeg_utils import (
        find_ffmpeg, raise_for_audio_extract_failure, require_audio_stream, run_ffmpeg,
    )

    await asyncio.to_thread(require_audio_stream, src)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise HTTPException(
            status_code=500,
            detail="ffmpeg was not found. Set it in Settings → Audio tools, then retry.",
        )
    tmp = f"{os.path.splitext(dest)[0]}.part.wav"
    try:
        code, _, stderr = await run_ffmpeg(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-protocol_whitelist", "file,pipe", "-i", src,
             "-map", "0:a:0", "-vn", "-ac", "1", "-c:a", "pcm_s16le", tmp],
            timeout=EXTRACT_TIMEOUT_S,
        )
        if code != 0:
            raise_for_audio_extract_failure(stderr, src)
            raise HTTPException(
                status_code=422,
                detail="Could not read the audio track of that video. Choose another file.",
            )
        os.replace(tmp, dest)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)
