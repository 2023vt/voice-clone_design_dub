"""Humanize — take the synthetic tells out of a clean render.

A model's output is *too* clean. Three things a listener hears as "AI"
without being able to name them, and what this module does about each:

* **Digital silence.** Every ``[pause]`` and every gap the chunker stitches
  is a run of exact zeros. No microphone has ever recorded that. A low pink
  noise bed runs under the whole take, so a pause sounds like the same room
  as the words around it (:func:`add_room_tone`).
* **Nobody breathes.** A person inhales before a sentence. Short, quiet,
  band-limited noise bursts are placed at the end of silences long enough to
  hold one, timed to finish just before the next onset. Only some gaps get
  one — a breath at every pause is its own tell (:func:`add_breaths`).
* **Metronome pacing.** Every chunk is rendered on its own and joined with
  whatever lead-in and tail the engine padded it with, so each sentence
  boundary has the same shape. :func:`prepare_chunks` trims that padding,
  sizes the gap by the punctuation that ended the chunk (comma, full stop,
  ellipsis), jitters it, and lets each chunk's tempo and pitch drift a
  little, the way one speaker never delivers two sentences quite alike.

Pure torch on the tensor's own device, seeded from the take's seed so a
pinned seed renders the same breaths in the same places. No model, no
network, identical on every platform. Explicit ``[pause Nms]`` lengths are
never changed — those are the user's direction. Everything here is opt-in:
nothing runs unless the request asks for it (``humanize=true``).

A take with no speech in it (a dead render, or pause markers only) is
returned untouched: dressing silence up as a room would hide the failure
from the dead-render guards and let ``normalize_audio`` amplify the bed to
full-scale hiss.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import torch

DEFAULT_STRENGTH = 0.6

#: A silence must be at least this long to hold a breath and still leave a
#: beat between the breath and the next word.
MIN_BREATH_GAP_MS = 350
#: Frames whose peak sits this far below the clip's peak count as silent.
SILENCE_BELOW_PEAK_DB = 40.0
#: Same floor as ``audio_dsp.normalize_audio``: a clip that never rises above
#: it has no speech, and is left alone.
SPEECH_FLOOR_DBFS = -50.0

_FRAME_MS = 5
_BREATH_LEAD_MS = 60      # a breath ends this long before the next onset
_BREATH_MIN_S = 0.18
_BREATH_MAX_S = 0.42
_EDGE_FADE_MS = 8
_PINK_BLOCK = 1 << 15     # ~1.4 s at 24 kHz; FFT-shaped with 75 % Hann overlap

#: Latin, CJK and the Devanagari danda / double danda (Hindi, Marathi, Nepali).
_SENTENCE_END = ".!?。！？।॥"
_CLAUSE_END = ",;:、，；："
_TRAIL_OFF = "…—"
_CLOSERS = "\"')]}»”’"

_SPEECH_FLOOR = 10.0 ** (SPEECH_FLOOR_DBFS / 20.0)


@dataclass(frozen=True)
class HumanizeSettings:
    """What the pass does, resolved from one 0–1 ``strength``.

    ``strength`` scales the breath level and probability, the tempo drift and
    the gap jitter together; the room tone rises from -66 dBFS RMS at 0 to
    -58 dBFS at 1. The three switches exist for tests and power users — the
    request surface is just the strength.
    """

    strength: float = DEFAULT_STRENGTH
    breaths: bool = True
    drift: bool = True
    gaps: bool = True

    @staticmethod
    def from_request(enabled: object, strength: object = None) -> Optional["HumanizeSettings"]:
        """``None`` unless ``enabled`` is truthy; ``strength`` clamped to 0–1,
        falling back to the default when it is missing or not a number."""
        if not enabled:
            return None
        try:
            value = DEFAULT_STRENGTH if strength is None else float(strength)
        except (TypeError, ValueError):
            value = DEFAULT_STRENGTH
        if not math.isfinite(value):
            value = DEFAULT_STRENGTH
        return HumanizeSettings(strength=min(1.0, max(0.0, value)))

    @property
    def room_tone_db(self) -> float:
        return -66.0 + 8.0 * self.strength

    def to_params(self) -> dict:
        """The two request fields, for forwarding to a remote worker."""
        return {"humanize": True, "humanize_strength": self.strength}


def make_rng(seed: Optional[int], salt: int = 0) -> torch.Generator:
    """A CPU generator derived from the take's seed. Two call sites that must
    not share a stream (the join and the whole-take pass) use different salts."""
    rng = torch.Generator(device="cpu")
    if seed is None:
        base = int(torch.randint(0, 2**31 - 1, (1,)).item())
    else:
        base = int(seed)
    rng.manual_seed((base * 1_000_003 + salt * 7919) & 0x7FFF_FFFF_FFFF_FFFF)
    return rng


def _uniform(rng: torch.Generator) -> float:
    return float(torch.rand(1, generator=rng).item())


def _mono_level(audio: torch.Tensor) -> torch.Tensor:
    level = audio.abs()
    if level.dim() > 1:
        level = level.reshape(-1, level.shape[-1]).amax(dim=0)
    return level


def has_speech(audio: torch.Tensor) -> bool:
    """False for an empty clip or one that never rises above the speech floor."""
    if audio is None or audio.numel() == 0:
        return False
    return bool(audio.abs().max().item() > _SPEECH_FLOOR)


# ── Room tone ───────────────────────────────────────────────────────────────

def pink_noise(n: int, sample_rate: int, rng: torch.Generator) -> torch.Tensor:
    """``n`` samples of unit-RMS pink (1/f) noise, high-passed below 30 Hz.

    Shaped block by block in the frequency domain and overlap-added under a
    Hann window at 75 % overlap, where the squared windows sum to a constant:
    the bed's level stays flat across block seams instead of swelling once a
    second. Memory is one output buffer, not a whole-take FFT.
    """
    if n <= 0:
        return torch.zeros(0)
    block = min(_PINK_BLOCK, max(64, 1 << (n - 1).bit_length()))
    hop = block // 4
    window = torch.hann_window(block, periodic=True)
    freqs = torch.fft.rfftfreq(block, d=1.0 / sample_rate)
    weight = torch.where(freqs < 30.0, torch.zeros_like(freqs), (30.0 / freqs.clamp(min=30.0)).sqrt())
    # Pre-roll by (block - hop): the first sample handed back already has all
    # four windows under it, instead of the ramp-up a bare overlap-add starts with.
    lead = block - hop
    total = n + lead
    out = torch.zeros(total + block)
    pos = 0
    while pos < total:
        white = torch.randn(block, generator=rng)
        shaped = torch.fft.irfft(torch.fft.rfft(white) * weight, n=block)
        out[pos:pos + block] += shaped * window
        pos += hop
    bed = out[lead:lead + n]
    rms = bed.pow(2).mean().sqrt()
    return bed / rms if rms > 0 else bed


def add_room_tone(audio: torch.Tensor, sample_rate: int, level_db: float,
                  rng: torch.Generator) -> torch.Tensor:
    """Mix a pink-noise bed at ``level_db`` dBFS RMS under the whole clip."""
    n = audio.shape[-1]
    if n == 0:
        return audio
    bed = pink_noise(n, sample_rate, rng) * (10.0 ** (level_db / 20.0))
    return audio + bed.to(device=audio.device, dtype=audio.dtype)


# ── Breaths ─────────────────────────────────────────────────────────────────

def silent_runs(audio: torch.Tensor, sample_rate: int, *,
                below_peak_db: float = SILENCE_BELOW_PEAK_DB) -> list[tuple[int, int]]:
    """``[(start, end)]`` sample ranges (end exclusive) where the clip sits
    ``below_peak_db`` under its own peak, measured on 5 ms frames."""
    n = audio.shape[-1]
    if n == 0:
        return []
    level = _mono_level(audio)
    peak = level.max()
    if peak <= 0:
        return [(0, n)]
    frame = max(1, sample_rate * _FRAME_MS // 1000)
    pad = (-n) % frame
    if pad:
        level = torch.nn.functional.pad(level, (0, pad))
    peaks = level.view(-1, frame).amax(dim=1)
    quiet = (peaks <= peak * 10.0 ** (-below_peak_db / 20.0)).to(torch.int8)
    edges = torch.diff(quiet, prepend=quiet.new_zeros(1), append=quiet.new_zeros(1))
    starts = torch.nonzero(edges == 1).flatten().tolist()
    ends = torch.nonzero(edges == -1).flatten().tolist()
    return [(s * frame, min(n, e * frame)) for s, e in zip(starts, ends)]


def synth_breath(sample_rate: int, duration_s: float, rng: torch.Generator) -> torch.Tensor:
    """One inhale: noise band-limited around 1.4 kHz under a slow-rise,
    faster-fall envelope. Peak-normalized to 1.0; the caller sets the level."""
    n = max(16, int(sample_rate * duration_s))
    white = torch.randn(n, generator=rng)
    freqs = torch.fft.rfftfreq(n, d=1.0 / sample_rate)
    octaves = torch.log2(freqs.clamp(min=1.0))
    mask = torch.exp(-0.5 * ((octaves - math.log2(1400.0)) / 1.1) ** 2)
    mask = torch.where(freqs < 150.0, torch.zeros_like(mask), mask)
    shaped = torch.fft.irfft(torch.fft.rfft(white) * mask, n=n)
    t = torch.linspace(0.0, 1.0, n)
    rise = 0.6
    env = torch.where(
        t < rise,
        0.5 - 0.5 * torch.cos(math.pi * t / rise),
        0.5 + 0.5 * torch.cos(math.pi * (t - rise) / (1.0 - rise)),
    ) ** 1.5
    breath = shaped * env
    peak = breath.abs().max()
    return breath / peak if peak > 0 else breath


def add_breaths(audio: torch.Tensor, sample_rate: int, strength: float,
                rng: torch.Generator) -> tuple[torch.Tensor, int]:
    """Place breaths before speech that follows a long enough silence.

    Returns the mixed clip and how many breaths were placed. The trailing
    silence never gets one — nobody inhales after the last word — and each
    eligible gap is taken with a probability that rises with ``strength``.
    Breath peaks sit 38 dB (strength 0) to 28 dB (strength 1) under the
    clip's peak, where a close-mic breath lands in a real recording.
    """
    n = audio.shape[-1]
    peak = float(audio.abs().max().item()) if n else 0.0
    if peak <= 0:
        return audio, 0
    min_gap = sample_rate * MIN_BREATH_GAP_MS // 1000
    lead = sample_rate * _BREATH_LEAD_MS // 1000
    level = peak * 10.0 ** ((-38.0 + 10.0 * strength) / 20.0)
    chance = 0.45 + 0.5 * strength
    out = audio.clone()
    placed = 0
    for start, end in silent_runs(audio, sample_rate):
        if end >= n or end - start < min_gap:
            continue
        if _uniform(rng) > chance:
            continue
        gap_s = (end - start) / sample_rate
        duration = min(_BREATH_MAX_S, max(_BREATH_MIN_S, 0.45 * gap_s)) * (0.85 + 0.3 * _uniform(rng))
        breath = synth_breath(sample_rate, duration, rng) * (level * (0.8 + 0.4 * _uniform(rng)))
        b_end = end - lead
        b_start = max(start, b_end - breath.shape[-1])
        if b_end - b_start < 16:
            continue
        breath = breath[-(b_end - b_start):].to(device=out.device, dtype=out.dtype)
        out[..., b_start:b_end] += breath
        placed += 1
    return out, placed


# ── Per-chunk pacing ────────────────────────────────────────────────────────

def drift_ratio(rng: torch.Generator, strength: float) -> float:
    """A tempo/pitch factor near 1: ±0.4 % at strength 0, ±1.6 % at 1."""
    spread = 0.004 + 0.012 * strength
    return 1.0 + (2.0 * _uniform(rng) - 1.0) * spread


def vary_tempo(audio: torch.Tensor, sample_rate: int, ratio: float) -> torch.Tensor:
    """Resample by ``ratio`` (>1 = slower and lower, like a tape running
    slow). Windowed-sinc through torchaudio; linear interpolation if that is
    unavailable. The sample rate is unchanged — only the clip's length is."""
    n = audio.shape[-1]
    if n < 16 or abs(ratio - 1.0) < 1e-4:
        return audio
    squeeze = audio.dim() == 1
    x = audio.unsqueeze(0) if squeeze else audio.reshape(-1, n)
    work = x.to(torch.float32)
    try:
        import torchaudio.functional as af  # noqa: PLC0415 — optional at runtime
        orig = 10_000
        new = max(1, int(round(orig * ratio)))
        y = af.resample(work, orig_freq=orig, new_freq=new)
    except Exception:  # noqa: BLE001 — a missing/failed resampler must not fail the take
        y = torch.nn.functional.interpolate(
            work.unsqueeze(0), size=max(16, int(round(n * ratio))), mode="linear",
            align_corners=False,
        ).squeeze(0)
    y = y.to(dtype=audio.dtype)
    if squeeze:
        return y.squeeze(0)
    return y.reshape(*audio.shape[:-1], y.shape[-1])


def fade_edges(audio: torch.Tensor, sample_rate: int, ms: int = _EDGE_FADE_MS) -> torch.Tensor:
    """Linear fade-in/out over ``ms`` so a trimmed chunk joins without a click."""
    n = audio.shape[-1]
    k = min(n // 2, sample_rate * ms // 1000)
    if k <= 0:
        return audio
    out = audio.clone()
    ramp = torch.linspace(0.0, 1.0, k, dtype=out.dtype, device=out.device)
    out[..., :k] *= ramp
    out[..., n - k:] *= ramp.flip(0)
    return out


def boundary_gap_ms(prev_text: str, rng: torch.Generator, strength: float) -> int:
    """How long to wait after ``prev_text`` before the next chunk starts.

    Sized by what ended the chunk — a paragraph break, a trailing-off ellipsis
    or dash, a sentence end, a clause break, or nothing — then jittered by
    ±10 % (strength 0) to ±35 % (strength 1) so no two boundaries match.
    """
    text = prev_text or ""
    body = text.rstrip()
    trailing = text[len(body):]
    body = body.rstrip(_CLOSERS)
    last = body[-1:] if body else ""
    if "\n\n" in trailing:
        base = 850
    elif body.endswith("...") or body.endswith("--") or (last and last in _TRAIL_OFF):
        base = 650
    elif last and last in _SENTENCE_END:
        base = 420
    elif last and last in _CLAUSE_END:
        base = 220
    else:
        base = 160
    jitter = 0.10 + 0.25 * strength
    return max(0, int(round(base * (1.0 + (2.0 * _uniform(rng) - 1.0) * jitter))))


def prepare_span(audio: torch.Tensor, sample_rate: int, settings: HumanizeSettings,
                 rng: torch.Generator) -> torch.Tensor:
    """Trim the engine's own padding, fade the edges and drift the tempo of
    one rendered span. Used for both chunk joins and ``[pause]`` spans."""
    if audio is None or audio.shape[-1] == 0:
        return audio
    from services.chunked_tts import trim_edge_silence  # noqa: PLC0415

    x = fade_edges(trim_edge_silence(audio, sample_rate), sample_rate)
    if settings.drift:
        x = vary_tempo(x, sample_rate, drift_ratio(rng, settings.strength))
    return x


def prepare_chunks(parts: Sequence[Optional[torch.Tensor]], texts: Optional[Sequence[str]],
                   sample_rate: int, settings: HumanizeSettings,
                   rng: torch.Generator) -> list[Optional[torch.Tensor]]:
    """Humanize each rendered chunk ahead of a hard join.

    Every chunk but the last carries its punctuation-sized gap as trailing
    silence, so the caller joins with ``crossfade_ms=0`` and the list keeps
    one entry per chunk — ``None``/empty entries pass through untouched, so
    dropped-chunk reporting in the join still sees them (#1330).
    """
    out: list[Optional[torch.Tensor]] = []
    last = len(parts) - 1
    for i, part in enumerate(parts):
        if part is None or part.shape[-1] == 0:
            out.append(part)
            continue
        x = prepare_span(part, sample_rate, settings, rng)
        if settings.gaps and i < last:
            text = texts[i] if texts is not None and i < len(texts) else ""
            gap = sample_rate * boundary_gap_ms(text, rng, settings.strength) // 1000
            if gap > 0:
                x = torch.cat([x, torch.zeros(*x.shape[:-1], gap, dtype=x.dtype, device=x.device)], dim=-1)
        out.append(x)
    return out


def span_preparer(sample_rate: int, settings: HumanizeSettings,
                  rng: torch.Generator) -> Callable[[torch.Tensor, int], torch.Tensor]:
    """``prepare(audio, index)`` for ``_render_with_pauses``: spans are
    trimmed, faded and drifted; the ``[pause]`` silences between them stay
    exactly as long as the user wrote."""
    def prepare(audio: torch.Tensor, _index: int) -> torch.Tensor:
        return prepare_span(audio, sample_rate, settings, rng)
    return prepare


# ── Whole take ──────────────────────────────────────────────────────────────

def humanize_audio(audio: torch.Tensor, sample_rate: int, settings: HumanizeSettings,
                   rng: torch.Generator) -> torch.Tensor:
    """Breaths into the long silences, then the room-tone bed under it all.

    Runs on the joined take before mastering so the bed and the breaths get
    the same EQ and compression as the voice. A clip with no speech is
    returned as-is (see the module docstring).
    """
    if not torch.is_tensor(audio) or not has_speech(audio):
        return audio
    work = audio if audio.is_floating_point() else audio.to(torch.float32)
    if settings.breaths:
        work, _ = add_breaths(work, sample_rate, settings.strength, rng)
    work = add_room_tone(work, sample_rate, settings.room_tone_db, rng)
    return work
