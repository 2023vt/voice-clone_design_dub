"""Roman-script text to the language's own script (Hinglish to Devanagari).

Every TTS engine reads ``kya haal hai`` as English: English vowels, English
stress, the wrong voice for a Hindi take. Hindi speakers type Roman script
all the time, so the Script box offers to rewrite it in Devanagari before
synthesis. A language model does the rewrite (the ``transliteration`` LLM
skill, routed like every other LLM call): casual Roman Hindi has no spelling
standard ("nahi", "nhi", "nahin" are one word), which rules cannot resolve
and a language model does well.

Guarded so a model cannot quietly change the script:

* bracket spans (``[pause 300ms]``, ``[laughter]``, ``[voice:Name]``,
  ``[[…]]``) are masked before the call and must all come back exactly once;
* line breaks must come back where they were;
* the answer must be mostly in the target script and of a plausible length.

Anything else raises :class:`TransliterationError`, which the route turns
into an error the UI shows. The user's text is never replaced by a rewrite
that failed these checks.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from services.reference_language import _script_of

logger = logging.getLogger("omnivoice.transliteration")

SKILL_ID = "transliteration"
MAX_CHARS = 20_000
_CHUNK_CHARS = 1_200

#: Language code to (English name, target script id, script name for the prompt).
_TARGETS: dict[str, tuple[str, str, str]] = {
    "hi": ("Hindi", "devanagari", "Devanagari"),
    "mr": ("Marathi", "devanagari", "Devanagari"),
    "ne": ("Nepali", "devanagari", "Devanagari"),
    "bn": ("Bengali", "bengali", "Bengali"),
    "pa": ("Punjabi", "gurmukhi", "Gurmukhi"),
    "gu": ("Gujarati", "gujarati", "Gujarati"),
    "ta": ("Tamil", "tamil", "Tamil"),
    "te": ("Telugu", "telugu", "Telugu"),
    "kn": ("Kannada", "kannada", "Kannada"),
    "ml": ("Malayalam", "malayalam", "Malayalam"),
    "ur": ("Urdu", "arabic", "Urdu (Perso-Arabic)"),
    "ar": ("Arabic", "arabic", "Arabic"),
    "fa": ("Persian", "arabic", "Persian (Perso-Arabic)"),
    "ru": ("Russian", "cyrillic", "Cyrillic"),
    "uk": ("Ukrainian", "cyrillic", "Cyrillic"),
    "el": ("Greek", "greek", "Greek"),
    "th": ("Thai", "thai", "Thai"),
}

_PROMPT = """\
You convert {language} written in Roman (Latin) letters into {language} written \
in the {script} script, the way a native writer would type it.

Rules:
- Transliterate every Romanized {language} word into {script}. Casual spellings \
("nahi", "nhi", "nahin") are the same word: write its standard spelling.
- English words used inside the {language} text (meeting, phone, plan) are \
written in {script} as {language} speakers write them. Brand and product names \
may stay in Latin letters.
- Keep digits, punctuation, emoji and every line break exactly where they are.
- Tokens like {marker} are placeholders: copy each one unchanged, in place.
- Do not translate, explain, add or remove anything.

Reply with only the converted text."""

_BRACKET_RE = re.compile(r"\[\[[^\]\n]*\]\]|\[[^\[\]\n]{0,128}\]")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class TransliterationError(Exception):
    """``code``: ``unsupported_language``, ``llm_unavailable``, ``too_long``,
    ``llm_failed`` or ``bad_output``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Result:
    text: str
    changed: bool


def target_for(language: Optional[str]) -> Optional[tuple[str, str, str]]:
    """``(name, script id, script name)`` for a language with its own script, else None."""
    from services.reference_language import _code  # noqa: PLC0415

    return _TARGETS.get(_code(language) or "")


def _letters(text: str) -> list[str]:
    return [c for c in _BRACKET_RE.sub(" ", text) if c.isalpha()]


def script_share(text: str, script: str) -> float:
    """Share of ``text``'s letters (outside bracket tags) written in ``script``."""
    letters = _letters(text)
    if not letters:
        return 0.0
    return sum(1 for c in letters if _script_of(c) == script) / len(letters)


def needs_conversion(text: str, language: Optional[str]) -> bool:
    """True when ``text`` is mostly Roman letters but ``language`` has its own script."""
    if target_for(language) is None:
        return False
    letters = _letters(text)
    return len(letters) >= 4 and script_share(text, "latin") >= 0.6


def _mask(text: str) -> tuple[str, list[str]]:
    spans: list[str] = []

    def keep(m: re.Match) -> str:
        spans.append(m.group(0))
        return f"⟦{len(spans) - 1}⟧"

    return _BRACKET_RE.sub(keep, text), spans


def _unmask(text: str, spans: list[str]) -> str:
    for i, span in enumerate(spans):
        marker = f"⟦{i}⟧"
        if text.count(marker) != 1:
            raise TransliterationError("bad_output", "a [tag] in the script was lost or duplicated")
        text = text.replace(marker, span)
    if re.search("⟦\\d+⟧", text):
        raise TransliterationError("bad_output", "the model invented a placeholder")
    return text


def _chunks(text: str) -> list[str]:
    """Whole lines, packed up to ``_CHUNK_CHARS`` (a longer line is its own chunk)."""
    out: list[str] = []
    cur = ""
    for line in text.split("\n"):
        candidate = line if not cur else f"{cur}\n{line}"
        if cur and len(candidate) > _CHUNK_CHARS:
            out.append(cur)
            cur = line
        else:
            cur = candidate
    out.append(cur)
    return out


def _clean(answer: str) -> str:
    s = _FENCE_RE.sub("", (answer or "").strip())
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'“”":
        s = s[1:-1]
    return s


def _check(source: str, answer: str, script: str) -> None:
    if answer.count("\n") != source.count("\n"):
        raise TransliterationError("bad_output", "the model changed the line breaks")
    src_letters, out_letters = len(_letters(source)), len(_letters(answer))
    if src_letters and not (0.35 <= out_letters / src_letters <= 2.5):
        raise TransliterationError("bad_output", "the rewrite is not the same length of text")
    if src_letters >= 4 and script_share(answer, script) < 0.6:
        raise TransliterationError("bad_output", "the rewrite is not in the target script")


def transliterate(text: str, language: Optional[str], *, llm=None) -> Result:
    """Rewrite Roman-letter ``text`` in ``language``'s own script.

    Text already in the target script (or with too few Roman letters to
    matter) comes back unchanged without calling the model.
    """
    target = target_for(language)
    if target is None:
        raise TransliterationError("unsupported_language",
                                   "this language is written in Latin letters already")
    if len(text) > MAX_CHARS:
        raise TransliterationError("too_long", f"scripts over {MAX_CHARS} characters are not converted")
    if not needs_conversion(text, language):
        return Result(text=text, changed=False)
    name, script, script_name = target

    if llm is None:
        from services import llm_skills  # noqa: PLC0415
        from services.llm_backend import OffBackend  # noqa: PLC0415

        llm = llm_skills.skill_backend(SKILL_ID)
        if isinstance(llm, OffBackend):
            raise TransliterationError("llm_unavailable", "no LLM is set up for script conversion")

    masked, spans = _mask(text)
    system = _PROMPT.format(language=name, script=script_name, marker="⟦0⟧")
    pieces = []
    for chunk in _chunks(masked):
        if not chunk.strip() or not needs_conversion(chunk, language):
            pieces.append(chunk)
            continue
        try:
            answer = _clean(llm.chat(system=system, user=chunk))
        except TransliterationError:
            raise
        except Exception as exc:  # noqa: BLE001 — provider errors surface as one code
            logger.warning("transliteration LLM call failed: %s", exc)
            raise TransliterationError("llm_failed", "the LLM call failed") from exc
        lead = chunk[: len(chunk) - len(chunk.lstrip())]
        trail = chunk[len(chunk.rstrip()):]
        answer = f"{lead}{answer.strip()}{trail}"
        _check(chunk, answer, script)
        pieces.append(answer)
    converted = _unmask("\n".join(pieces), spans)
    return Result(text=converted, changed=converted != text)
