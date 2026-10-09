"""Hindi (hi) number verbalization — a native backend for text_normalization.

``num2words`` has no Hindi locale (it ships bn/kn/te but not hi, ml or ta),
so a Hindi script reached the engine with raw digits: OmniVoice reads "2026"
in English, or garbles it, in the middle of a Devanagari sentence — the
single most audible "this is a machine" moment in a Hindi take. This module
renders what a Hindi news reader actually says:

  * cardinals 0–999999 with the irregular 1–99 table (इक्कीस, बाईस, …), सौ,
    हज़ार and the Indian लाख (10^5): 150000 → एक लाख पचास हज़ार;
  * the spoken "सौ" form for 1100–1999 — years and amounts alike — because
    1984 is उन्नीस सौ चौरासी and 1500 रुपये is पंद्रह सौ रुपये, never
    "एक हज़ार नौ सौ चौरासी"; 2000 and up stay on हज़ार (दो हज़ार छब्बीस);
  * decimals read digit by digit after दशमलव, percentages with प्रतिशत;
  * rupees: ₹500, Rs. 500, Rs 1,50,000 → … रुपये (and पैसे for ₹5.50);
  * clock times the way they are spoken: 10:30 → साढ़े दस, 1:30 → डेढ़,
    2:30 → ढाई, 10:15 → सवा दस, 10:45 → पौने ग्यारह, 10:00 → दस बजे,
    10:20 → दस बजकर बीस मिनट (a following "बजे" is folded in, becoming
    "पर" after the बजकर form);
  * ordinals written with a digit: 5वां → पाँचवां, 1वीं → पहली, 4वें → चौथे;
  * Indian digit grouping (1,50,000) which the generic conservative rules
    leave alone as "ambiguous" but is unambiguous in Hindi text.

Scope matches the conservative rules of :mod:`services.text_normalization`:
up to six digits (crores are out of scope), bracket spans untouched, any
failure leaves the occurrence as written. Pure Python, no dependencies; every
rendering contains no digits, so a second pass is a no-op.
"""
from __future__ import annotations

import re
from typing import Callable

# ── Tables ───────────────────────────────────────────────────────────────────

_BELOW_HUNDRED = [
    "शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ",
    "दस", "ग्यारह", "बारह", "तेरह", "चौदह", "पंद्रह", "सोलह", "सत्रह", "अठारह", "उन्नीस",
    "बीस", "इक्कीस", "बाईस", "तेईस", "चौबीस", "पच्चीस", "छब्बीस", "सत्ताईस", "अट्ठाईस", "उनतीस",
    "तीस", "इकतीस", "बत्तीस", "तैंतीस", "चौंतीस", "पैंतीस", "छत्तीस", "सैंतीस", "अड़तीस", "उनतालीस",
    "चालीस", "इकतालीस", "बयालीस", "तैंतालीस", "चौवालीस", "पैंतालीस", "छियालीस", "सैंतालीस", "अड़तालीस", "उनचास",
    "पचास", "इक्यावन", "बावन", "तिरपन", "चौवन", "पचपन", "छप्पन", "सत्तावन", "अट्ठावन", "उनसठ",
    "साठ", "इकसठ", "बासठ", "तिरसठ", "चौंसठ", "पैंसठ", "छियासठ", "सड़सठ", "अड़सठ", "उनहत्तर",
    "सत्तर", "इकहत्तर", "बहत्तर", "तिहत्तर", "चौहत्तर", "पचहत्तर", "छिहत्तर", "सतहत्तर", "अठहत्तर", "उनासी",
    "अस्सी", "इक्यासी", "बयासी", "तिरासी", "चौरासी", "पचासी", "छियासी", "सत्तासी", "अट्ठासी", "नवासी",
    "नब्बे", "इक्यानवे", "बानवे", "तिरानवे", "चौरानवे", "पंचानवे", "छियानवे", "सत्तानवे", "अट्ठानवे", "निन्यानवे",
]

HUNDRED = "सौ"
THOUSAND = "हज़ार"
LAKH = "लाख"
DECIMAL_WORD = "दशमलव"
PERCENT_WORD = "प्रतिशत"
RUPEE = "रुपये"
RUPEE_ONE = "रुपया"
PAISE = "पैसे"
OCLOCK = "बजे"
PAST = "बजकर"
MINUTES = "मिनट"

# The idiomatic quarter forms: (quarter past, half past, quarter to) are
# सवा / साढ़े / पौने + hour, except the hours that have their own word.
_HALF_PAST_SPECIAL = {1: "डेढ़", 2: "ढाई"}

# Ordinal stems for the irregular ordinals; everything else is cardinal + suffix.
_ORDINAL_STEMS = {1: "पहल", 2: "दूसर", 3: "तीसर", 4: "चौथ", 6: "छठ"}
_ORDINAL_ENDINGS = {"वां": "ा", "वाँ": "ा", "वीं": "ी", "वें": "े"}


# ── Cardinals ────────────────────────────────────────────────────────────────

def _below_thousand(n: int) -> str:
    """0-999: hundreds as "<unit> सौ", then the irregular 1-99 word."""
    hundreds, rest = divmod(n, 100)
    parts: list[str] = []
    if hundreds:
        parts.append(f"{_BELOW_HUNDRED[hundreds]} {HUNDRED}")
    if rest or not parts:
        parts.append(_BELOW_HUNDRED[rest])
    return " ".join(parts)


def cardinal(n: int) -> str:
    """Render an integer 0 ≤ n ≤ 999999 as Hindi words."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("cardinal() expects an int")
    if n < 0 or n > 999_999:
        raise ValueError("cardinal() supports 0..999999")
    if n < 1000:
        return _below_thousand(n)
    if 1100 <= n <= 1999:
        # Spoken form for years and amounts: उन्नीस सौ चौरासी, पंद्रह सौ.
        hundreds, rest = divmod(n, 100)
        head = f"{_BELOW_HUNDRED[hundreds]} {HUNDRED}"
        return f"{head} {_BELOW_HUNDRED[rest]}" if rest else head
    lakhs, rest = divmod(n, 100_000)
    parts: list[str] = []
    if lakhs:
        parts.append(f"{_BELOW_HUNDRED[lakhs]} {LAKH}")
    thousands, units = divmod(rest, 1000)
    if thousands:
        parts.append(f"{_BELOW_HUNDRED[thousands]} {THOUSAND}")
    if units:
        parts.append(_below_thousand(units))
    return " ".join(parts)


def decimal(int_part: int, frac_digits: str) -> str:
    """3.14 → तीन दशमलव एक चार (fraction digits are read one by one)."""
    digits = " ".join(_BELOW_HUNDRED[int(d)] for d in frac_digits)
    return f"{cardinal(int_part)} {DECIMAL_WORD} {digits}"


def percent(raw: str) -> str:
    """'50' → पचास प्रतिशत; '2.5' → दो दशमलव पाँच प्रतिशत."""
    if "." in raw:
        a, b = raw.split(".", 1)
        body = decimal(int(a), b)
    else:
        body = cardinal(int(raw))
    return f"{body} {PERCENT_WORD}"


# ── Hindi-specific forms ─────────────────────────────────────────────────────

def _grouped_int(raw: str) -> int:
    """'1,50,000' → 150000. Raises for anything cardinal() cannot say."""
    return int(raw.replace(",", ""))


def rupees(raw_amount: str, paise: str | None = None) -> str:
    """'500' → पाँच सौ रुपये; '1' → एक रुपया; ('5', '50') → पाँच रुपये पचास पैसे."""
    amount = _grouped_int(raw_amount)
    paise_n = int(paise) if paise else 0
    if amount == 1 and not paise_n:
        return f"{cardinal(1)} {RUPEE_ONE}"
    words = f"{cardinal(amount)} {RUPEE}" if amount or not paise_n else ""
    if paise_n:
        tail = f"{cardinal(paise_n)} {PAISE}"
        return f"{words} {tail}" if words else tail
    return words


def clock(hour: int, minute: int, *, spoken_oclock: bool = False) -> str:
    """The spoken time for ``hour``:``minute`` (24-hour input).

    ``spoken_oclock`` says a "बजे" followed the digits in the text; it is
    folded into the forms that carry their own (the quarter forms keep it,
    "बजकर … मिनट" replaces it, "N बजे" is the on-the-hour form either way).
    """
    h = hour % 12 or 12
    nxt = h % 12 + 1
    suffix = f" {OCLOCK}" if spoken_oclock else ""
    if minute == 0:
        return f"{_BELOW_HUNDRED[h]} {OCLOCK}"
    if minute == 15:
        return f"सवा {_BELOW_HUNDRED[h]}{suffix}"
    if minute == 30:
        return f"{_HALF_PAST_SPECIAL.get(h, 'साढ़े ' + _BELOW_HUNDRED[h])}{suffix}"
    if minute == 45:
        return f"पौने {_BELOW_HUNDRED[nxt]}{suffix}"
    # "10:20 बजे मिलेंगे" → "दस बजकर बीस मिनट पर मिलेंगे": the postposition
    # that "बजे" carried has to survive the rewrite.
    tail = " पर" if spoken_oclock else ""
    return f"{_BELOW_HUNDRED[h]} {PAST} {_BELOW_HUNDRED[minute]} {MINUTES}{tail}"


def ordinal(n: int, suffix: str) -> str:
    """5 + वां → पाँचवां; the irregular 1/2/3/4/6 take their own stems."""
    ending = _ORDINAL_ENDINGS[suffix]
    stem = _ORDINAL_STEMS.get(n)
    if stem is not None:
        return stem + ending
    return cardinal(n) + suffix


# ── Patterns the normalizer runs before its generic percent/decimal/integer
#    passes. Same boundary guards as text_normalization's own regexes; every
#    pattern's group(1) starts with the number so the shared leading-zero
#    guard applies. Order matters: rupees and times claim their digits first.

_AMOUNT = r"(\d{1,2}(?:,\d{2})+,\d{3}|\d{1,6})"
_RUPEE_RE = re.compile(
    r"(?<![\w.,:/$%+-])(?:\u20b9|[Rr]s\.?|रु\.?)\s?" + _AMOUNT
    + r"(?:\.(\d{2}))?(?![\w:/%+-])(?![.,]\d)"
)
_TIME_RE = re.compile(
    r"(?<![\w:.,/$%+-])([01]?\d|2[0-3]):([0-5]\d)(?![\w:/%+-])(?![.,]\d)(\s*बजे(?!\w))?"
)
_ORDINAL_RE = re.compile(r"(?<![\w.,:/$%+-])(\d{1,4})(वां|वाँ|वीं|वें)(?![\w])")
_GROUPED_RE = re.compile(
    r"(?<![\w.,:/$%-])(\d{1,2}(?:,\d{2})+,\d{3})(?![\w:/%-])(?![.,]\d)"
)


def _rupee(m: re.Match) -> str:
    return rupees(m.group(1), m.group(2))


def _time(m: re.Match) -> str:
    return clock(int(m.group(1)), int(m.group(2)), spoken_oclock=bool(m.group(3)))


def _ordinal(m: re.Match) -> str:
    return ordinal(int(m.group(1)), m.group(2))


def _grouped(m: re.Match) -> str:
    return cardinal(_grouped_int(m.group(1)))


PATTERNS: list[tuple[re.Pattern, Callable[[re.Match], str]]] = [
    (_RUPEE_RE, _rupee),
    (_TIME_RE, _time),
    (_ORDINAL_RE, _ordinal),
    (_GROUPED_RE, _grouped),
]
