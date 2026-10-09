"""Roman-script to native-script conversion (``services/transliteration.py``).

The LLM is faked: these tests pin the guards around it — what is sent, what
must come back, and that a bad rewrite never replaces the user's text.
"""
import pytest

from services import transliteration as tl
from services.transliteration import TransliterationError, needs_conversion, transliterate


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, *, system, user, **_):
        self.calls.append((system, user))
        return self.reply(user) if callable(self.reply) else self.reply


def _devanagari_for(user: str) -> str:
    """A faithful fake: maps a few Roman words, keeps placeholders and breaks."""
    words = {"kya": "क्या", "haal": "हाल", "hai": "है", "aap": "आप", "sab": "सब",
             "ka": "का", "meeting": "मीटिंग", "kal": "कल", "thi": "थी", "nahi": "नहीं"}
    out_lines = []
    for line in user.split("\n"):
        out_lines.append(" ".join(words.get(w, w) for w in line.split(" ")))
    return "\n".join(out_lines)


@pytest.mark.parametrize("text, language, expected", [
    ("kya haal hai", "Hindi", True),
    ("kya haal hai", "hi", True),
    ("क्या हाल है", "Hindi", False),
    ("kya haal hai", "English", False),
    ("kya haal hai", "Auto", False),
    ("ok", "Hindi", False),                         # too few letters
    ("[pause 300ms] है", "Hindi", False),           # tags do not count
])
def test_needs_conversion(text, language, expected):
    assert needs_conversion(text, language) is expected


def test_converts_and_keeps_tags_and_line_breaks():
    llm = FakeLLM(_devanagari_for)
    res = transliterate("kya haal hai [pause 300ms] aap\nsab ka [laughter]", "Hindi", llm=llm)
    assert res.changed
    assert res.text == "क्या हाल है [pause 300ms] आप\nसब का [laughter]"
    system, user = llm.calls[0]
    assert "Hindi" in system and "Devanagari" in system
    assert "[pause" not in user and "⟦0⟧" in user, "tags travel as placeholders"


def test_text_already_in_script_does_not_call_the_model():
    llm = FakeLLM(lambda u: pytest.fail("the LLM must not be called"))
    res = transliterate("क्या हाल है आप सब का", "Hindi", llm=llm)
    assert res == tl.Result(text="क्या हाल है आप सब का", changed=False)


@pytest.mark.parametrize("reply, why", [
    ("kya haal hai aap", "still Roman letters"),
    ("क्या हाल है आप", "dropped the placeholder for [pause 300ms]"),
    ("क्या हाल है ⟦0⟧ ⟦0⟧ आप", "duplicated the placeholder"),
    ("क्या हाल है ⟦0⟧\nआप", "added a line break"),
    ("क्या ⟦0⟧ " + "हाल " * 40, "far longer than the source"),
])
def test_bad_rewrites_are_refused(reply, why):
    with pytest.raises(TransliterationError) as err:
        transliterate("kya haal hai [pause 300ms] aap", "Hindi", llm=FakeLLM(reply))
    assert err.value.code == "bad_output", why


def test_code_fences_and_quotes_are_stripped():
    res = transliterate("kya haal hai", "Hindi", llm=FakeLLM('```\n"क्या हाल है"\n```'))
    assert res.text == "क्या हाल है"


def test_long_text_goes_in_line_aligned_chunks():
    line = "kya haal hai aap sab ka " * 20
    text = "\n".join([line.strip()] * 6)
    llm = FakeLLM(_devanagari_for)
    res = transliterate(text, "Hindi", llm=llm)
    assert len(llm.calls) > 1
    assert res.text.count("\n") == 5
    assert "kya" not in res.text


def test_unsupported_language_and_too_long():
    with pytest.raises(TransliterationError) as err:
        transliterate("kya haal hai", "English", llm=FakeLLM("x"))
    assert err.value.code == "unsupported_language"
    with pytest.raises(TransliterationError) as err:
        transliterate("a" * (tl.MAX_CHARS + 1), "Hindi", llm=FakeLLM("x"))
    assert err.value.code == "too_long"


def test_provider_failure_is_one_error_code():
    class Boom:
        def chat(self, **_):
            raise RuntimeError("401 from provider")

    with pytest.raises(TransliterationError) as err:
        transliterate("kya haal hai", "Hindi", llm=Boom())
    assert err.value.code == "llm_failed"


def test_no_llm_configured(monkeypatch):
    from services import llm_skills
    from services.llm_backend import OffBackend

    monkeypatch.setattr(llm_skills, "skill_backend", lambda *_a, **_k: OffBackend())
    with pytest.raises(TransliterationError) as err:
        transliterate("kya haal hai", "Hindi")
    assert err.value.code == "llm_unavailable"


# ── route ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app, client=("127.0.0.1", 50000))


def test_route_returns_the_conversion(client, monkeypatch):
    monkeypatch.setattr(tl, "transliterate",
                        lambda text, language: tl.Result(text="क्या हाल है", changed=True))
    resp = client.post("/tools/transliterate", json={"text": "kya haal hai", "language": "Hindi"})
    assert resp.status_code == 200
    assert resp.json() == {"text": "क्या हाल है", "changed": True}


@pytest.mark.parametrize("code, status", [
    ("llm_unavailable", 503), ("unsupported_language", 422), ("too_long", 413),
    ("bad_output", 502), ("llm_failed", 502),
])
def test_route_maps_errors_to_statuses(client, monkeypatch, code, status):
    def fail(text, language):
        raise TransliterationError(code, "nope")

    monkeypatch.setattr(tl, "transliterate", fail)
    resp = client.post("/tools/transliterate", json={"text": "kya haal hai", "language": "Hindi"})
    assert resp.status_code == status
    assert resp.json()["detail"]["code"] == code
