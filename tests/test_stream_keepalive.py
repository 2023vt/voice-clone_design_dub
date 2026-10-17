"""#2108 class: streamed renders must not go byte-silent behind a proxy.

POST /generate?stream=true wrote nothing until its first text chunk had
rendered. On a CPU host one ~600-character chunk takes longer than
Cloudflare's ~100 s first-byte limit, so a 1220-character request failed with
HTTP 524 in the browser while the take still finished into History. Long-form
SSE renders had the same gap for each chapter. ``core.stream_keepalive`` now
interleaves keepalive frames during silence; these tests pin the wrapper
contract and both wired-up routes.
"""
import asyncio
import contextvars
import os
import time
from urllib.parse import urlencode

os.environ.setdefault("OMNIVOICE_MODEL", "test")
os.environ.setdefault("OMNIVOICE_DISABLE_FILE_LOG", "1")

import pytest
from core import stream_keepalive as sk


async def _collect(agen, limit=50):
    out = []
    async for item in agen:
        out.append(item)
        if len(out) >= limit:
            break
    return out


def test_pings_fill_silence_and_items_keep_order():
    async def slow():
        yield "a"
        await asyncio.sleep(0.12)
        yield "b"

    out = asyncio.run(_collect(sk.with_keepalive(slow(), "~", interval=0.03)))
    assert out[0] == "a" and out[-1] == "b"
    assert out.count("~") >= 2, out
    assert set(out[1:-1]) == {"~"}


def test_fast_stream_gets_no_pings():
    async def fast():
        for i in range(5):
            yield i

    assert asyncio.run(_collect(sk.with_keepalive(fast(), "~", interval=1.0))) == list(range(5))


def test_zero_interval_disables_keepalive():
    async def slow():
        await asyncio.sleep(0.05)
        yield "x"

    assert asyncio.run(_collect(sk.with_keepalive(slow(), "~", interval=0))) == ["x"]


def test_source_exception_propagates():
    async def boom():
        yield 1
        await asyncio.sleep(0.05)
        raise RuntimeError("render failed")

    async def run():
        return await _collect(sk.with_keepalive(boom(), "~", interval=0.01))

    with pytest.raises(RuntimeError, match="render failed"):
        asyncio.run(run())


def test_closing_mid_step_cancels_and_finalizes_source():
    """A client disconnect must stop the in-flight step and run the source's
    cleanup now (#2536), exactly like closing an unwrapped generator."""
    state = {"cancelled": False, "finalized": False}

    async def source():
        try:
            yield "first"
            await asyncio.sleep(10)
            yield "never"
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        finally:
            state["finalized"] = True

    async def run():
        wrapped = sk.with_keepalive(source(), "~", interval=0.01)
        assert await wrapped.__anext__() == "first"
        assert await wrapped.__anext__() == "~"  # source is now mid-sleep
        await wrapped.aclose()

    asyncio.run(run())
    assert state == {"cancelled": True, "finalized": True}


def test_context_variables_persist_across_steps():
    """Steps share one context, so a var set inside the stream stays visible
    to its later steps, the same as a plain ``async for``."""
    var = contextvars.ContextVar("v", default="unset")

    async def source():
        var.set("set-in-step-1")
        yield var.get()
        await asyncio.sleep(0.03)
        yield var.get()

    out = asyncio.run(_collect(sk.with_keepalive(source(), "~", interval=0.01)))
    assert out[0] == out[-1] == "set-in-step-1", out


# ── /generate?stream=true ──────────────────────────────────────────────────


def _slow_engine(delay_s):
    import importlib

    import torch

    tts = importlib.import_module("services.tts_backend")

    class _Engine(tts.TTSBackend):
        id = "keepalive-fake"
        display_name = "Keepalive fake engine (test)"
        gpu_compat = ("cpu",)

        @property
        def sample_rate(self) -> int:
            return 24000

        @property
        def supported_languages(self) -> list[str]:
            return ["multi"]

        @classmethod
        def is_available(cls):
            return True, "ready"

        def generate(self, text, **kw):
            time.sleep(delay_s)
            return (torch.linspace(-1.0, 1.0, 4800) * 0.3).unsqueeze(0)

    return tts, _Engine


async def _raw_stream_body(path, form):
    """POST at the ASGI app and return the response's raw body bytes."""
    from main import app

    body = urlencode(form).encode()
    sent, delivered = [], False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()

    async def send(msg):
        sent.append(msg)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "",
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 3900),
        "headers": [
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", str(len(body)).encode()),
        ],
    }
    await app(scope, receive, send)
    start = sent[0]
    assert start["type"] == "http.response.start" and start["status"] == 200, sent
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    return headers, b"".join(m.get("body", b"") for m in sent[1:] if m["type"] == "http.response.body")


def test_generate_stream_sends_keepalive_before_slow_first_chunk(monkeypatch, tmp_path):
    import api.routers.generation as gen
    import core.config as cfg

    outdir = tmp_path / "outputs"
    outdir.mkdir()
    monkeypatch.setattr(cfg, "OUTPUTS_DIR", str(outdir))
    monkeypatch.setattr(gen, "OUTPUTS_DIR", str(outdir))
    # Throwaway history DB, same seam as test_generate_streaming's fixture.
    import sqlite3

    def _get_db():
        conn = sqlite3.connect(str(tmp_path / "history.db"))
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setitem(gen.ensure_schema.__globals__, "get_db", _get_db)
    gen.ensure_schema()
    monkeypatch.setattr(sk, "STREAM_KEEPALIVE_S", 0.05)
    tts, engine = _slow_engine(delay_s=0.4)
    monkeypatch.setitem(tts._REGISTRY, engine.id, engine)

    headers, body = asyncio.run(_raw_stream_body("/generate", {
        "text": "A slow first chunk on a CPU host.", "engine": engine.id,
        "seed": "3", "stream": "true",
    }))

    first_event = body.index(b'{"type":"start"')
    # Keepalives must reach the client while the first chunk is still rendering.
    assert body[:first_event].count(b"\n") >= 2, body[:first_event]
    assert body[:first_event].strip() == b""
    assert b'"type":"done"' in body
    assert headers["x-accel-buffering"] == "no"
    assert "no-transform" in headers["cache-control"]


# ── long-form SSE ──────────────────────────────────────────────────────────


def test_longform_stream_sends_sse_comments_during_slow_chapter(monkeypatch):
    from api.routers import audiobook as ab

    async def slow_render(plan, **kw):
        yield 'data: {"type": "chapter_start"}\n\n'
        await asyncio.sleep(0.2)
        yield 'data: {"type": "done"}\n\n'

    monkeypatch.setattr(ab, "_render_longform_sse", slow_render)
    monkeypatch.setattr(sk, "STREAM_KEEPALIVE_S", 0.05)

    out = asyncio.run(_collect(ab._public_longform_stream(plan=None)))
    assert out[0].startswith("data:") and out[-1].startswith("data:")
    assert out.count(sk.SSE_KEEPALIVE) >= 2, out
