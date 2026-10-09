"""Humanize pass (``services/humanize.py``): breaths, room tone, pacing.

Pure DSP, no model. Every assertion is about the shape of the audio the pass
produces, measured — not about how it was produced — so an engine or platform
change cannot pass by accident and the room-tone / breath levels are pinned to
what a listener gets.
"""
import math

import pytest
import torch

from api.routers.generation import _apply_effect_chain, _render_with_pauses
from services.chunked_tts import trim_edge_silence
from services.humanize import (
    DEFAULT_STRENGTH,
    MIN_BREATH_GAP_MS,
    HumanizeSettings,
    add_breaths,
    add_room_tone,
    boundary_gap_ms,
    drift_ratio,
    fade_edges,
    has_speech,
    humanize_audio,
    make_rng,
    pink_noise,
    prepare_chunks,
    silent_runs,
    span_preparer,
    vary_tempo,
)

SR = 24000


def _db(x: torch.Tensor) -> float:
    return 20.0 * math.log10(max(float(x), 1e-12))


def _tone(seconds: float, amp: float = 0.5, hz: float = 220.0) -> torch.Tensor:
    t = torch.arange(int(SR * seconds)) / SR
    return torch.sin(2 * math.pi * hz * t) * amp


def _silence(seconds: float) -> torch.Tensor:
    return torch.zeros(int(SR * seconds))


def _take(gap_s: float = 0.6, tail_s: float = 0.3) -> torch.Tensor:
    """speech · exact-zero gap · speech · exact-zero tail — what the pause
    stitcher and the chunk join produce."""
    return torch.cat([_tone(1.0), _silence(gap_s), _tone(1.0), _silence(tail_s)])


# ── settings ────────────────────────────────────────────────────────────────

def test_from_request_is_none_unless_enabled():
    assert HumanizeSettings.from_request(False) is None
    assert HumanizeSettings.from_request(None, 0.9) is None
    assert HumanizeSettings.from_request(True).strength == DEFAULT_STRENGTH


@pytest.mark.parametrize("raw, expected", [
    ("0.3", 0.3), (1.7, 1.0), (-2, 0.0), ("nope", DEFAULT_STRENGTH),
    (float("nan"), DEFAULT_STRENGTH), (None, DEFAULT_STRENGTH),
])
def test_from_request_clamps_strength(raw, expected):
    assert HumanizeSettings.from_request(True, raw).strength == pytest.approx(expected)


def test_to_params_round_trips_through_a_worker():
    settings = HumanizeSettings.from_request(True, 0.25)
    params = settings.to_params()
    assert params == {"humanize": True, "humanize_strength": 0.25}
    assert HumanizeSettings.from_request(params["humanize"], params["humanize_strength"]) == settings


def test_room_tone_level_tracks_strength():
    assert HumanizeSettings(strength=0.0).room_tone_db == pytest.approx(-66.0)
    assert HumanizeSettings(strength=1.0).room_tone_db == pytest.approx(-58.0)


# ── room tone ───────────────────────────────────────────────────────────────

def test_pink_noise_is_unit_rms_and_flat_across_block_seams():
    bed = pink_noise(SR * 6, SR, make_rng(1))
    assert bed.shape == (SR * 6,)
    assert bed.pow(2).mean().sqrt().item() == pytest.approx(1.0, abs=1e-4)
    # No swell once per block: every half-second slice sits within 1.5 dB of the whole.
    slices = bed.view(-1, SR // 2).pow(2).mean(dim=1).sqrt()
    assert slices.max() / slices.min() < 10 ** (1.5 / 20)
    # 1/f: the lower octave carries more energy than the one above it.
    spectrum = torch.fft.rfft(bed).abs()
    freqs = torch.fft.rfftfreq(bed.shape[-1], d=1.0 / SR)
    low = spectrum[(freqs >= 200) & (freqs < 400)].pow(2).mean()
    high = spectrum[(freqs >= 800) & (freqs < 1600)].pow(2).mean()
    assert low > high


def test_room_tone_replaces_digital_silence_at_the_requested_level():
    take = _take()
    out = add_room_tone(take, SR, -60.0, make_rng(7))
    assert out.shape == take.shape
    gap = out[SR:SR + int(0.6 * SR)]
    assert bool((gap != 0).all()), "a pause must never be exact zeros"
    assert _db(gap.pow(2).mean().sqrt()) == pytest.approx(-60.0, abs=1.5)
    # The voice is untouched beyond the bed itself.
    assert (out[:SR] - take[:SR]).abs().max() < 10 ** (-40 / 20)


def test_room_tone_keeps_channels():
    stereo = torch.stack([_take(), _take()])
    out = add_room_tone(stereo, SR, -60.0, make_rng(2))
    assert out.shape == stereo.shape


# ── breaths ─────────────────────────────────────────────────────────────────

def test_silent_runs_find_exact_zero_gaps_and_the_tail():
    take = _take(gap_s=0.6, tail_s=0.3)
    runs = silent_runs(take, SR)
    assert len(runs) == 2
    (g0, g1), (t0, t1) = runs
    assert abs(g0 - SR) <= SR // 100 and abs(g1 - int(1.6 * SR)) <= SR // 100
    assert abs(t0 - int(2.6 * SR)) <= SR // 100 and t1 == take.shape[-1]


def test_breath_lands_inside_a_long_gap_and_never_in_the_tail():
    gap_s = 0.8
    take = _take(gap_s=gap_s, tail_s=0.5)
    # Strength 1 takes a gap with probability 0.95; try a few seeds so the
    # assertion is about placement, not one draw.
    placed_any = False
    for seed in range(6):
        out, placed = add_breaths(take, SR, 1.0, make_rng(seed))
        assert out.shape == take.shape
        tail = out[-int(0.5 * SR):]
        assert torch.equal(tail, torch.zeros_like(tail)), "nobody inhales after the last word"
        if not placed:
            continue
        placed_any = True
        diff = (out - take).abs()
        touched = torch.nonzero(diff > 0).flatten()
        gap_start, gap_end = SR, SR + int(gap_s * SR)
        assert touched.min() >= gap_start
        assert touched.max() < gap_end - SR * 50 // 1000, "a breath ends before the next onset"
        # 28 dB under the clip's peak at strength 1 (±2 dB for the random level spread).
        assert _db(diff.max() / take.abs().max()) == pytest.approx(-28.0, abs=2.5)
    assert placed_any


def test_short_gaps_get_no_breath():
    take = _take(gap_s=(MIN_BREATH_GAP_MS - 50) / 1000)
    for seed in range(4):
        out, placed = add_breaths(take, SR, 1.0, make_rng(seed))
        assert placed == 0 and torch.equal(out, take)


def test_breath_probability_rises_with_strength():
    take = torch.cat([torch.cat([_tone(0.5), _silence(0.6)]) for _ in range(40)] + [_tone(0.5)])
    low = sum(add_breaths(take, SR, 0.0, make_rng(s))[1] for s in range(3))
    high = sum(add_breaths(take, SR, 1.0, make_rng(s))[1] for s in range(3))
    assert 0 < low < high <= 120


# ── pacing ──────────────────────────────────────────────────────────────────

def test_drift_ratio_spread_scales_with_strength():
    for strength, spread in ((0.0, 0.004), (1.0, 0.016)):
        ratios = [drift_ratio(make_rng(s), strength) for s in range(200)]
        assert all(abs(r - 1.0) <= spread + 1e-9 for r in ratios)
        assert max(abs(r - 1.0) for r in ratios) > spread * 0.5


def test_vary_tempo_changes_length_by_the_ratio_only():
    tone = _tone(1.0)
    slow = vary_tempo(tone, SR, 1.012)
    assert slow.shape[-1] == pytest.approx(tone.shape[-1] * 1.012, rel=1e-3)
    assert slow.abs().max() == pytest.approx(0.5, abs=0.02)
    assert vary_tempo(tone, SR, 1.0) is tone
    stereo = torch.stack([tone, tone])
    assert vary_tempo(stereo, SR, 0.99).shape[0] == 2


def test_fade_edges_removes_the_click():
    tone = _tone(0.5) + 0.3
    out = fade_edges(tone, SR)
    assert out[0].abs() < 1e-6 and out[-1].abs() < 1e-6
    assert torch.equal(out[SR // 4], tone[SR // 4])


@pytest.mark.parametrize("text, low, high", [
    ("Hello world.", 378, 462),
    ("Wait, what?", 378, 462),
    ("यह वाक्य है।", 378, 462),  # Devanagari danda
    ("He said “go.”", 378, 462),
    ("First,", 198, 242),
    ("and then...", 585, 715),
    ("so…", 585, 715),
    ("no punctuation", 144, 176),
    ("Paragraph.\n\n", 765, 935),
    ("", 144, 176),
])
def test_boundary_gap_is_sized_by_punctuation(text, low, high):
    for seed in range(20):
        assert low <= boundary_gap_ms(text, make_rng(seed), 0.0) <= high


def test_prepare_chunks_pads_every_boundary_and_keeps_dropped_entries():
    padded = torch.cat([_silence(0.2), _tone(0.5), _silence(0.3)])  # engine lead-in/tail
    settings = HumanizeSettings(strength=0.0, drift=False)
    parts = prepare_chunks([padded, padded, torch.zeros(0), None, padded],
                           ["A.", "B,", "C", "D", "E."], SR, settings, make_rng(3))
    assert len(parts) == 5
    assert parts[2].shape[-1] == 0 and parts[3] is None
    kept = trim_edge_silence(padded, SR).shape[-1]  # the tone plus 40 ms either side
    assert abs(kept - int(0.58 * SR)) <= 2
    first, second, last = parts[0], parts[1], parts[4]
    assert last.shape[-1] == kept, "the last chunk carries no gap"
    for part, (low, high) in ((first, (378, 462)), (second, (198, 242))):
        gap = part.shape[-1] - kept
        assert SR * low // 1000 <= gap <= SR * high // 1000
        assert torch.equal(part[kept:], torch.zeros(gap))


def test_prepare_chunks_without_gaps_only_trims_and_drifts():
    padded = torch.cat([_silence(0.2), _tone(0.5), _silence(0.3)])
    parts = prepare_chunks([padded, padded], None, SR, HumanizeSettings(gaps=False), make_rng(1))
    kept = trim_edge_silence(padded, SR).shape[-1]
    for part in parts:
        assert part.shape[-1] == pytest.approx(kept, rel=0.02)
        assert part[-1].abs() < 1e-6


def test_pause_markers_stay_exact_with_the_span_preparer():
    """``[pause 500ms]`` is the user's direction: Humanize trims and fades the
    rendered spans but the stitched silence is exactly what was asked for."""
    padded = torch.cat([_silence(0.2), _tone(0.5), _silence(0.3)])
    settings = HumanizeSettings(drift=False)
    out = _render_with_pauses(lambda _t: padded.clone(), [("a", 500), ("b", 0)], SR,
                              prepare=span_preparer(SR, settings, make_rng(9)))
    kept = trim_edge_silence(padded, SR).shape[-1]
    assert out.shape[-1] == 2 * kept + SR // 2
    assert torch.equal(out[kept:kept + SR // 2], torch.zeros(SR // 2))


# ── whole take ──────────────────────────────────────────────────────────────

def test_humanize_is_deterministic_for_a_seed_and_differs_across_seeds():
    take = _take()
    settings = HumanizeSettings()
    a = humanize_audio(take, SR, settings, make_rng(42))
    b = humanize_audio(take, SR, settings, make_rng(42))
    c = humanize_audio(take, SR, settings, make_rng(43))
    assert torch.equal(a, b)
    assert not torch.equal(a, c)
    assert not torch.equal(humanize_audio(take, SR, settings, make_rng(42, salt=1)), a)


def test_humanize_leaves_a_dead_render_alone():
    """Room tone over silence would hide a failed render from the dead-render
    guard and hand normalize_audio a bed to amplify to full-scale hiss."""
    dead = torch.full((SR,), 10 ** (-55 / 20))
    assert not has_speech(dead)
    assert torch.equal(humanize_audio(dead, SR, HumanizeSettings(), make_rng(1)), dead)
    assert torch.equal(humanize_audio(torch.zeros(SR), SR, HumanizeSettings(), make_rng(1)),
                       torch.zeros(SR))
    assert has_speech(_tone(0.1))


def test_humanize_runs_on_the_tensors_device_and_dtype_family():
    take = _take()
    out = humanize_audio(take.to(torch.float64), SR, HumanizeSettings(), make_rng(1))
    assert out.dtype == torch.float64 and out.shape == take.shape
    out16 = humanize_audio((take * 32767).to(torch.int16), SR, HumanizeSettings(), make_rng(1))
    assert out16.is_floating_point()


def test_effect_chain_is_byte_identical_without_humanize_and_changed_with_it():
    take = _take()
    plain = _apply_effect_chain(take.clone(), SR, "raw")
    assert torch.equal(plain, take)
    human = _apply_effect_chain(take.clone(), SR, "raw",
                                humanize=HumanizeSettings(), seed=5)
    assert human.shape == take.shape
    gap = human[SR:SR + int(0.6 * SR)]
    assert bool((gap != 0).all())
    again = _apply_effect_chain(take.clone(), SR, "raw",
                                humanize=HumanizeSettings(), seed=5)
    assert torch.equal(human, again)
