"""Catch a take that keeps talking after its text has ended, and render it again.

Autoregressive engines decide for themselves when to stop, and sometimes they
do not: on the Hindi eval set (``scripts/eval_hindi.py``, VoxCPM2, 25 lines) a
one-line question came back 26.7 s long, the line followed by twenty seconds
of invented syllables, and two more lines ran on the same way. Measured there,
good takes ran up to 2.1x the language's expected reading time (a slow
documentary narrator) and runaway ones from 2.6x to 12.6x.

A take longer than ``RUNAWAY_RATIO`` times its expected length, and at least
``MIN_EXCESS_S`` seconds over it, is rendered once more with another seed. The
retry is kept when it is not itself a runaway and not suspiciously short;
otherwise the shorter runaway wins, and a too-short retry loses to the
complete first take. One retry at most and only on a runaway, so a normal take
costs nothing. Expected reading time comes from ``speech_rate`` (per-language
characters per second); pure arithmetic, identical on every platform.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

logger = logging.getLogger("omnivoice.runaway_guard")

RUNAWAY_RATIO = 2.3
MIN_EXCESS_S = 2.5
#: A retry shorter than this share of the expected time has probably lost words.
MIN_COMPLETE_RATIO = 0.5
RETRY_SEED_OFFSET = 7919

_TAGS = re.compile(r"\[[^\]]*\]")
_LEADING_CONTROL = re.compile(r"^\s*\([^()]*\)")


def expected_seconds(text: str, language: Optional[str] = None,
                     speed: Optional[float] = None) -> float:
    """How long a natural reading of ``text`` takes, in seconds."""
    from services.speech_rate import expected_duration  # noqa: PLC0415
    from services.text_normalization import _plain_lang_code  # noqa: PLC0415

    spoken = " ".join(_TAGS.sub(" ", _LEADING_CONTROL.sub("", text or "")).split())
    seconds = expected_duration(spoken, _plain_lang_code(language) or "en")
    try:
        rate = float(speed) if speed is not None else 1.0
    except (TypeError, ValueError):
        rate = 1.0
    return seconds / max(0.25, rate)


def is_runaway(seconds: float, expected: float) -> bool:
    return expected > 0 and seconds > max(RUNAWAY_RATIO * expected, expected + MIN_EXCESS_S)


def retry_seed(seed: Optional[int]) -> Optional[int]:
    """The seed for the second attempt; None stays None (the engine draws one)."""
    if seed is None:
        return None
    return (int(seed) + RETRY_SEED_OFFSET) & 0x7FFF_FFFF


def render_guarded(render: Callable[[int], "object"], text: str, *, sample_rate: int,
                   language: Optional[str] = None, speed: Optional[float] = None,
                   label: str = "") -> "object":
    """``render(attempt)`` for attempt 0, and once more for attempt 1 when
    attempt 0 ran away. Returns the take to keep (a tensor, last axis = samples)."""
    first = render(0)
    expected = expected_seconds(text, language, speed)
    first_s = first.shape[-1] / sample_rate
    if not is_runaway(first_s, expected):
        return first
    second = render(1)
    second_s = second.shape[-1] / sample_rate
    logger.warning(
        "%s take ran on past its text: %.1f s for about %.1f s of reading; "
        "re-rendered with another seed: %.1f s", label or "TTS", first_s, expected, second_s,
    )
    if not is_runaway(second_s, expected) and second_s >= MIN_COMPLETE_RATIO * expected:
        return second
    if is_runaway(second_s, expected):
        return first if first_s <= second_s else second
    return first
