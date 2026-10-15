"""Combine several recordings of one speaker into a single clone reference.

Every cloning engine conditions on exactly one reference clip (OmniVoice
builds one codec-token prompt from it; the subprocess engines take one path),
so "clone from several samples" cannot mean averaging speaker embeddings. It
means giving the engine a reference that covers more of the speaker: several
recording sessions, phrasings and pitch ranges instead of one take.

``merge_references`` cuts the best voiced passage out of each sample, matches
their loudness (different microphones and distances otherwise make the
engine copy the loudness jumps), and joins them with short pauses into one
mono WAV. The composite stays under ``MERGED_MAX_SECONDS`` so OmniVoice keeps
its transcript (``CLONE_REF_TEXT_MAX_SECONDS``) and uses all of it instead of
picking one 15 s window. Passages are cut on pauses where possible, so the
transcript of the composite reads as whole words.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import torch

logger = logging.getLogger("omnivoice.reference_merge")

MAX_SAMPLES = 8
# Under OmniVoice's 20 s transcript limit with margin for the pauses.
MERGED_MAX_SECONDS = 18.0
# A passage shorter than this carries too little of the voice to help.
MIN_PASSAGE_SECONDS = 1.0
GAP_SECONDS = 0.3
TARGET_SAMPLE_RATE = 24000

_FRAME_SECONDS = 0.03
_MIN_PAUSE_SECONDS = 0.15
# Speech frames sit within this many dB of the clip's loud frames.
_VOICED_RANGE_DB = 35.0
_SILENCE_FLOOR_DB = -50.0
_TARGET_RMS_DB = -20.0
_PEAK_CEILING = 10 ** (-1.0 / 20.0)


class ReferenceMergeError(ValueError):
    """The samples cannot form a usable reference; the message is user-facing."""


@dataclass(frozen=True)
class _Sample:
    audio: np.ndarray  # mono float32 at TARGET_SAMPLE_RATE
    voiced: np.ndarray  # bool per frame
    quality_db: float


def _to_mono(audio: torch.Tensor, sample_rate: int) -> np.ndarray:
    if audio.ndim > 1:
        audio = audio.mean(dim=0)
    if sample_rate != TARGET_SAMPLE_RATE:
        import torchaudio.functional as F

        audio = F.resample(audio, sample_rate, TARGET_SAMPLE_RATE)
    return audio.to(torch.float32).numpy()


def _frame_db(audio: np.ndarray) -> np.ndarray:
    frame = int(_FRAME_SECONDS * TARGET_SAMPLE_RATE)
    count = len(audio) // frame
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    frames = audio[: count * frame].reshape(count, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return (20.0 * np.log10(np.maximum(rms, 1e-10))).astype(np.float32)


def _analyse(audio: np.ndarray) -> _Sample:
    db = _frame_db(audio)
    if db.size == 0:
        return _Sample(audio, np.zeros(0, dtype=bool), float("-inf"))
    loud = float(np.percentile(db, 95))
    threshold = max(_SILENCE_FLOOR_DB, loud - _VOICED_RANGE_DB)
    voiced = db > threshold
    if not voiced.any():
        return _Sample(audio, voiced, float("-inf"))
    # Rough signal-to-noise: speech level over the noise floor. Clean close-mic
    # takes rank above roomy or noisy ones.
    quality = loud - float(np.percentile(db, 10))
    return _Sample(audio, voiced, quality)


def _cut_points(voiced: np.ndarray) -> list[int]:
    """Frame indices where a passage may start or end without splitting a word."""
    first = int(np.argmax(voiced))
    last = len(voiced) - int(np.argmax(voiced[::-1]))
    points = [first]
    min_run = max(1, round(_MIN_PAUSE_SECONDS / _FRAME_SECONDS))
    i = first
    while i < last:
        if voiced[i]:
            i += 1
            continue
        j = i
        while j < last and not voiced[j]:
            j += 1
        if j - i >= min_run:
            points.append((i + j) // 2)
        i = j
    points.append(last)
    return points


def _best_passage(sample: _Sample, budget_s: float) -> tuple[int, int]:
    """Frame span with the most speech that fits ``budget_s``.

    Prefers spans bounded by pauses; falls back to a hard cut only when the
    speaker never pauses inside the budget.
    """
    voiced = sample.voiced
    budget = max(1, int(budget_s / _FRAME_SECONDS))
    points = _cut_points(voiced)
    speech = np.concatenate([[0], np.cumsum(voiced)])
    best: tuple[int, int, int] | None = None
    for a_index, a in enumerate(points):
        for b in points[a_index + 1:]:
            if b - a > budget:
                break
            amount = int(speech[b] - speech[a])
            if best is None or amount > best[0]:
                best = (amount, a, b)
    if best is not None and best[0] * _FRAME_SECONDS >= MIN_PASSAGE_SECONDS:
        return best[1], best[2]
    # Continuous speech longer than the budget: take the densest window.
    start = points[0]
    end = min(points[-1], start + budget)
    top = int(speech[end] - speech[start])
    for a in range(points[0], max(points[0], points[-1] - budget) + 1):
        amount = int(speech[a + budget] - speech[a]) if a + budget < len(speech) else 0
        if amount > top:
            top, start, end = amount, a, a + budget
    return start, end


def _level(audio: np.ndarray, voiced_audio: np.ndarray) -> np.ndarray:
    rms = float(np.sqrt(np.mean(voiced_audio.astype(np.float64) ** 2))) if voiced_audio.size else 0.0
    if rms <= 0:
        return audio
    gain = 10 ** (_TARGET_RMS_DB / 20.0) / rms
    peak = float(np.max(np.abs(audio))) * gain
    if peak > _PEAK_CEILING:
        gain *= _PEAK_CEILING / peak
    return (audio * gain).astype(np.float32)


def merge_references(paths: list[str], out_path: str) -> float:
    """Write one composite reference built from ``paths``; return its seconds.

    Samples are ordered cleanest first so a downstream engine that trims the
    reference keeps the best material. Raises ``ReferenceMergeError`` when
    fewer than two samples contain speech.
    """
    from services.audio_io import atomic_save_wav, load_audio

    if len(paths) > MAX_SAMPLES:
        raise ReferenceMergeError(f"Use at most {MAX_SAMPLES} samples for one voice.")
    samples: list[_Sample] = []
    for path in paths:
        audio, sample_rate = load_audio(path)
        sample = _analyse(_to_mono(audio, sample_rate))
        if sample.voiced.any():
            samples.append(sample)
        else:
            logger.info("reference sample %s has no speech; skipped", path)
    if len(samples) < 2:
        raise ReferenceMergeError(
            "At least two of the samples need audible speech to combine them. "
            "Check the recordings or save a single sample instead."
        )
    samples.sort(key=lambda s: s.quality_db, reverse=True)

    frame = int(_FRAME_SECONDS * TARGET_SAMPLE_RATE)
    speech_budget = MERGED_MAX_SECONDS - GAP_SECONDS * (len(samples) - 1)
    remaining = speech_budget
    passages: list[np.ndarray] = []
    for index, sample in enumerate(samples):
        share = remaining / (len(samples) - index)
        a, b = _best_passage(sample, share)
        piece = sample.audio[a * frame: b * frame]
        voiced = np.repeat(sample.voiced[a:b], frame)[: len(piece)]
        passages.append(_level(piece, piece[voiced]))
        # Unused share from a short sample goes to the ones after it.
        remaining -= len(piece) / TARGET_SAMPLE_RATE

    gap = np.zeros(int(GAP_SECONDS * TARGET_SAMPLE_RATE), dtype=np.float32)
    joined: list[np.ndarray] = []
    for index, passage in enumerate(passages):
        if index:
            joined.append(gap)
        joined.append(passage)
    merged = np.concatenate(joined)
    atomic_save_wav(out_path, torch.from_numpy(merged).unsqueeze(0), TARGET_SAMPLE_RATE)
    return len(merged) / TARGET_SAMPLE_RATE
