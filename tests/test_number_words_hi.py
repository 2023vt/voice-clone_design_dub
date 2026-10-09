"""Hindi number verbalizer (``services/number_words_hi.py``).

Pinned renderings are what a Hindi news reader says, not what a lookup table
would mechanically produce — the सौ form for 1100–1999, डेढ़/ढाई/सवा/पौने
clock times, पहला/दूसरी ordinals, and एक रुपया vs रुपये.
"""
import pytest

from services import number_words_hi as hi
from services.text_normalization import normalize_text


@pytest.mark.parametrize("n, expected", [
    (0, "शून्य"),
    (1, "एक"),
    (5, "पाँच"),
    (19, "उन्नीस"),
    (21, "इक्कीस"),
    (42, "बयालीस"),
    (99, "निन्यानवे"),
    (100, "एक सौ"),
    (101, "एक सौ एक"),
    (150, "एक सौ पचास"),
    (999, "नौ सौ निन्यानवे"),
    (1000, "एक हज़ार"),
    (1001, "एक हज़ार एक"),
    (1099, "एक हज़ार निन्यानवे"),
    (1100, "ग्यारह सौ"),
    (1200, "बारह सौ"),
    (1500, "पंद्रह सौ"),
    (1984, "उन्नीस सौ चौरासी"),
    (1999, "उन्नीस सौ निन्यानवे"),
    (2000, "दो हज़ार"),
    (2026, "दो हज़ार छब्बीस"),
    (2200, "दो हज़ार दो सौ"),
    (10000, "दस हज़ार"),
    (25000, "पच्चीस हज़ार"),
    (99999, "निन्यानवे हज़ार नौ सौ निन्यानवे"),
    (100000, "एक लाख"),
    (150000, "एक लाख पचास हज़ार"),
    (250500, "दो लाख पचास हज़ार पाँच सौ"),
    (999999, "नौ लाख निन्यानवे हज़ार नौ सौ निन्यानवे"),
])
def test_cardinal(n, expected):
    assert hi.cardinal(n) == expected


def test_cardinal_covers_the_whole_regex_range_without_digits():
    for n in range(1_000_000):
        word = hi.cardinal(n)
        assert word and not any(ch.isdigit() for ch in word), n


def test_cardinal_rejects_out_of_range_and_non_ints():
    with pytest.raises(ValueError):
        hi.cardinal(1_000_000)
    with pytest.raises(ValueError):
        hi.cardinal(-1)
    with pytest.raises(TypeError):
        hi.cardinal(True)


def test_decimal_and_percent():
    assert hi.decimal(3, "5") == "तीन दशमलव पाँच"
    assert hi.decimal(3, "14") == "तीन दशमलव एक चार"
    assert hi.percent("50") == "पचास प्रतिशत"
    assert hi.percent("2.5") == "दो दशमलव पाँच प्रतिशत"


@pytest.mark.parametrize("amount, paise, expected", [
    ("1", None, "एक रुपया"),
    ("500", None, "पाँच सौ रुपये"),
    ("1,50,000", None, "एक लाख पचास हज़ार रुपये"),
    ("5", "50", "पाँच रुपये पचास पैसे"),
    ("1", "25", "एक रुपये पच्चीस पैसे"),
    ("0", "75", "पचहत्तर पैसे"),
])
def test_rupees(amount, paise, expected):
    assert hi.rupees(amount, paise) == expected


@pytest.mark.parametrize("hour, minute, oclock, expected", [
    (10, 0, False, "दस बजे"),
    (10, 0, True, "दस बजे"),
    (10, 15, False, "सवा दस"),
    (10, 15, True, "सवा दस बजे"),
    (10, 30, True, "साढ़े दस बजे"),
    (1, 30, True, "डेढ़ बजे"),
    (2, 30, False, "ढाई"),
    (13, 30, False, "डेढ़"),
    (10, 45, True, "पौने ग्यारह बजे"),
    (12, 45, False, "पौने एक"),
    (0, 30, False, "साढ़े बारह"),
    (10, 20, False, "दस बजकर बीस मिनट"),
    (10, 20, True, "दस बजकर बीस मिनट पर"),
    (23, 5, False, "ग्यारह बजकर पाँच मिनट"),
])
def test_clock(hour, minute, oclock, expected):
    assert hi.clock(hour, minute, spoken_oclock=oclock) == expected


@pytest.mark.parametrize("n, suffix, expected", [
    (1, "वां", "पहला"),
    (1, "वाँ", "पहला"),
    (1, "वीं", "पहली"),
    (2, "वीं", "दूसरी"),
    (3, "वें", "तीसरे"),
    (4, "वां", "चौथा"),
    (6, "वां", "छठा"),
    (5, "वां", "पाँचवां"),
    (5, "वीं", "पाँचवीं"),
    (25, "वें", "पच्चीसवें"),
    (100, "वां", "एक सौवां"),
])
def test_ordinal(n, suffix, expected):
    assert hi.ordinal(n, suffix) == expected


@pytest.mark.parametrize("raw, expected", [
    ("₹500", "पाँच सौ रुपये"),
    ("₹ 500", "पाँच सौ रुपये"),
    ("Rs. 500", "पाँच सौ रुपये"),
    ("Rs 500", "पाँच सौ रुपये"),
    ("rs. 500", "पाँच सौ रुपये"),
    ("रु. 500", "पाँच सौ रुपये"),
    ("₹1,50,000", "एक लाख पचास हज़ार रुपये"),
    ("₹1", "एक रुपया"),
    ("₹5.50", "पाँच रुपये पचास पैसे"),
    ("1,50,000 लोग", "एक लाख पचास हज़ार लोग"),
    ("12,50,000 लोग", "12,50,000 लोग"),       # over six digits: left alone
    ("₹1,000", "₹1,000"),                       # plain thousands grouping
    ("10:30", "साढ़े दस"),
    ("10:30 बजे", "साढ़े दस बजे"),
    ("10:30 बजेगा", "साढ़े दस बजेगा"),          # "बजे" inside a longer word stays
    ("24:30", "24:30"),                          # not a clock time
    ("5वां", "पाँचवां"),
    ("5वाँ", "पाँचवाँ"),
])
def test_patterns_through_the_normalizer(raw, expected):
    assert normalize_text(raw, "Hindi") == expected


def test_normalizer_output_is_idempotent_and_digit_free():
    text = "डॉ. शर्मा 10:20 बजे ₹1,50,000 लेकर 5वीं मंज़िल पर 2026 में 50% छूट देंगे"
    once = normalize_text(text, "Hindi")
    assert not any(ch.isdigit() for ch in once)
    assert normalize_text(once, "Hindi") == once
    assert once == (
        "डॉक्टर शर्मा दस बजकर बीस मिनट पर एक लाख पचास हज़ार रुपये लेकर पाँचवीं "
        "मंज़िल पर दो हज़ार छब्बीस में पचास प्रतिशत छूट देंगे"
    )
