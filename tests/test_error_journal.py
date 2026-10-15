"""core.error_journal — structured, deduped, classified backend error ring."""
import json
import os

import pytest

from core import error_journal
from core.error_journal import classify_exception, record, recent


@pytest.fixture(autouse=True)
def isolated_journal(monkeypatch, tmp_path):
    """Point persistence at a temp file and start every test empty."""
    monkeypatch.setattr(error_journal, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    error_journal._entries.clear()
    yield
    error_journal._entries.clear()


# ── Classification ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc,trace,expected",
    [
        (RuntimeError("CUDA out of memory. Tried to allocate 2.5 GiB"), "", "GPU_OOM"),
        (RuntimeError("MPS backend out of memory"), "", "GPU_OOM"),
        (OSError(28, "No space left on device"), "", "DISK_FULL"),
        (RuntimeError("401 Client Error: Unauthorized for url: https://huggingface.co/x"), "", "HF_AUTH_FAILED"),
        (RuntimeError("boom"), "huggingface_hub.errors.GatedRepoError: ...", "HF_AUTH_FAILED"),
        (FileNotFoundError("No such file or directory: 'ffmpeg'"), "", "FFMPEG_MISSING"),
        (ConnectionError("Connection refused"), "", "NETWORK_ERROR"),
        (TimeoutError("timed out"), "", "NETWORK_ERROR"),
        (ValueError("tensor shape mismatch"), "", "UNKNOWN"),
    ],
)
def test_classify(exc, trace, expected):
    assert classify_exception(exc, trace) == expected


def test_pyannote_needs_auth_marker():
    # pyannote alone is any diarization bug — must NOT classify as license.
    plain = RuntimeError("pyannote pipeline failed on segment 3")
    assert classify_exception(plain, "") != "PYANNOTE_LICENSE_REQUIRED"
    gated = RuntimeError("pyannote/speaker-diarization-3.1: 403 gated repo, accept access")
    assert classify_exception(gated, "") == "PYANNOTE_LICENSE_REQUIRED"


# ── Recording + dedup ─────────────────────────────────────────────────────


def test_record_and_recent_order():
    record(ValueError("first"), route="/a")
    record(KeyError("second"), route="/b")
    errors = recent()
    assert errors[0]["message"].endswith("'second'") or "second" in errors[0]["message"]
    assert errors[1]["route"] == "/a"


def test_dedup_bumps_count():
    for _ in range(3):
        record(ValueError("same failure"), route="/gen")
    errors = recent()
    assert len(errors) == 1
    assert errors[0]["count"] == 3


def test_trace_is_scrubbed_and_truncated():
    trace = "File \"/home/eve/app/main.py\" line 1\n" + "x" * 10_000
    entry = record(RuntimeError("boom"), trace=trace)
    assert "/home/eve" not in entry["trace"]
    assert len(entry["trace"]) <= error_journal._MAX_TRACE_CHARS


def test_ring_capped():
    for i in range(error_journal._MAX_ENTRIES + 10):
        record(ValueError(f"distinct-{i}"))
    assert len(recent(limit=50)) == error_journal._MAX_ENTRIES


def test_persists_to_jsonl():
    record(ValueError("persisted"))
    with open(error_journal.JOURNAL_PATH, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]
    assert any("persisted" in e["message"] for e in lines)


def test_record_never_raises(monkeypatch):
    # Even with persistence broken, record() must return an entry.
    monkeypatch.setattr(error_journal, "JOURNAL_PATH", "/nonexistent/dir/x.jsonl")
    entry = record(ValueError("still works"))
    assert entry["error_class"] == "UNKNOWN"
    assert entry["count"] == 1


def test_persistence_failure_is_observable_without_losing_memory(monkeypatch, caplog):
    monkeypatch.setattr(error_journal, "JOURNAL_PATH", "/nonexistent/dir/x.jsonl")
    with caplog.at_level("WARNING", logger="omnivoice.error_journal"):
        entry = record(ValueError("still visible"))
    assert entry in recent()
    assert "persistence failed" in caplog.text


def test_hydrate_failure_is_observable(monkeypatch, caplog, tmp_path):
    journal_dir = tmp_path / "journal-dir"
    journal_dir.mkdir()
    monkeypatch.setattr(error_journal, "JOURNAL_PATH", str(journal_dir))
    with caplog.at_level("WARNING", logger="omnivoice.error_journal"):
        error_journal._hydrate()
    assert "could not be loaded" in caplog.text


def test_clear_failure_keeps_entries_retryable(monkeypatch, caplog):
    entry = record(ValueError("keep me"))
    monkeypatch.setattr(
        error_journal.os,
        "remove",
        lambda _path: (_ for _ in ()).throw(PermissionError("locked")),
    )
    with caplog.at_level("WARNING", logger="omnivoice.error_journal"):
        assert error_journal.clear() is False
    assert entry in recent()
    assert "keeping entries available for retry" in caplog.text


def test_clear_is_idempotent_when_durable_mirror_is_already_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(error_journal, "JOURNAL_PATH", str(tmp_path / "absent.jsonl"))
    error_journal._entries["entry"] = {"fingerprint": "entry"}
    assert error_journal.clear() is True
    assert recent() == []


def test_hydrate_malformed_entry_logs_debug_and_scrubs(tmp_path, monkeypatch, caplog):
    secret_path = "/home/sensitive_user/secret.json"
    journal_file = tmp_path / "journal_malformed.jsonl"
    journal_file.write_text(f'{{"fingerprint": "valid"}}\nmalformed_json_at_{secret_path}\n', encoding="utf-8")
    monkeypatch.setattr(error_journal, "JOURNAL_PATH", str(journal_file))

    with caplog.at_level("DEBUG", logger="omnivoice.error_journal"):
        error_journal._hydrate()

    assert "Skipping malformed error journal entry: " in caplog.text
    assert "JSONDecodeError" in caplog.text or "Expecting value" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_coarse_stage_exception_logs_debug(caplog):
    class BadRoute:
        def split(self, *args):
            raise RuntimeError("Route parsing failed at /home/sensitive_user/route")

    with caplog.at_level("DEBUG", logger="omnivoice.error_journal"):
        stage = error_journal._coarse_stage(BadRoute())

    assert stage == ""
    assert "Failed parsing coarse stage from route: Route parsing failed at " in caplog.text
    assert "~/route" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_analytics_recording_failure_logs_debug_and_scrubs(monkeypatch, caplog):
    import core
    secret = "/home/sensitive_user/analytics.token"
    mock_analytics = type("MockAnalytics", (), {
        "record_error_event": staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(f"Token read error at {secret}"))),
    })
    monkeypatch.setattr(core, "analytics", mock_analytics, raising=False)

    with caplog.at_level("DEBUG", logger="omnivoice.error_journal"):
        entry = record(ValueError("test error"))

    assert entry["type"] == "ValueError"
    assert "Analytics error event recording skipped: Token read error at " in caplog.text
    assert "~/analytics.token" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_record_internal_exception_logs_debug_and_scrubs(monkeypatch, caplog):
    secret = "/home/sensitive_user/internal.db"
    monkeypatch.setattr(
        error_journal,
        "classify_exception",
        lambda *args: (_ for _ in ()).throw(RuntimeError(f"Internal crash at {secret}")),
    )

    with caplog.at_level("DEBUG", logger="omnivoice.error_journal"):
        entry = record(TypeError("original type must be preserved"))

    # Crucial test: original exception type (TypeError) is preserved rather than shadowed by internal RuntimeError
    assert entry["error_class"] == "UNKNOWN"
    assert entry["type"] == "TypeError"
    assert "Error journal recording failed: Internal crash at " in caplog.text
    assert "~/internal.db" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_persistence_failure_logs_scrubbed_warning(monkeypatch, caplog):
    secret_path = "/home/sensitive_user/cannot_write.jsonl"
    monkeypatch.setattr(error_journal, "JOURNAL_PATH", secret_path)

    with caplog.at_level("WARNING", logger="omnivoice.error_journal"):
        record(ValueError("sample error"))

    assert "Error journal persistence failed (" in caplog.text
    assert "~/cannot_write.jsonl" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_clear_failure_logs_scrubbed_warning(monkeypatch, caplog):
    secret_path = "/home/sensitive_user/cannot_delete.jsonl"
    monkeypatch.setattr(
        error_journal.os,
        "remove",
        lambda _path: (_ for _ in ()).throw(PermissionError(f"Denied {secret_path}")),
    )

    with caplog.at_level("WARNING", logger="omnivoice.error_journal"):
        res = error_journal.clear()

    assert res is False
    assert "Error journal could not be cleared (Denied " in caplog.text
    assert "~/cannot_delete.jsonl" in caplog.text
    assert "sensitive_user" not in caplog.text


def test_safe_str_handles_broken_str():
    class BrokenException(Exception):
        def __str__(self):
            raise RuntimeError("broken string representation")

    broken = BrokenException()
    assert error_journal._safe_str(broken) == "BrokenException"


def test_record_with_broken_str_exception_does_not_crash():
    class BrokenException(Exception):
        def __str__(self):
            raise RuntimeError("broken string representation")

    entry = record(BrokenException())
    assert entry["error_class"] == "UNKNOWN"
    assert entry["type"] == "BrokenException"
