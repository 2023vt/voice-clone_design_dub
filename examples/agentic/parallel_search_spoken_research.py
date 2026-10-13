"""Search the web with Parallel MCP, then synthesize chosen results locally.

Install the optional MCP client in your own environment and run from the repo
root (VoiceStudio must be running):

    uv pip install "mcp>=2,<3"
    python examples/agentic/parallel_search_spoken_research.py "recent open source speech synthesis"

Parallel is contacted only after confirmation. The query and chosen URLs go to
Parallel; fetched excerpts go to VoiceStudio only after a separate prompt.
Nothing is added to the app's dependencies or runtime network calls.

Optional: OMNIVOICE_API_URL, OMNIVOICE_API_KEY, OMNIVOICE_VOICE, --output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PARALLEL_MCP_URL = "https://search.parallel.ai/mcp"
URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)


def result_text(result: object) -> str:
    """Read the server's text blocks, or its structured result if needed."""
    blocks = getattr(result, "content", ()) or ()
    texts = [
        text.strip()
        for block in blocks
        if isinstance((text := getattr(block, "text", None)), str) and text.strip()
    ]
    if texts:
        return "\n\n".join(texts)
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    return json.dumps(structured, ensure_ascii=False, indent=2) if structured else ""


def search_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.findall(text):
        # Drop sentence punctuation, then remove only unmatched closing
        # delimiters that wrap URLs in prose. Balanced URL parentheses are valid.
        url = match.rstrip(".,;:!?")
        for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
            while url.endswith(closing) and url.count(closing) > url.count(opening):
                url = url[:-1]
        if url not in urls:
            urls.append(url)
    return urls


def choose_urls(urls: list[str]) -> list[str]:
    print("\nSearch result URLs:")
    for index, url in enumerate(urls, 1):
        print(f"  {index}. {url}")
    raw = input("Fetch which results? Enter numbers separated by commas (default 1): ").strip()
    try:
        indices = [int(part.strip()) for part in raw.split(",")] if raw else [1]
    except ValueError as exc:
        raise ValueError("Enter result numbers separated by commas, such as 1,2.") from exc
    indices = list(dict.fromkeys(indices))
    if any(index < 1 or index > len(urls) for index in indices):
        raise ValueError(f"Choose numbers from 1 to {len(urls)}.")
    return [urls[index - 1] for index in indices]


def synthesize(text: str, output: Path) -> None:
    service_root = os.environ.get("OMNIVOICE_API_URL", "http://localhost:3900").rstrip("/")
    api_root = service_root if service_root.endswith("/v1") else f"{service_root}/v1"
    request = urllib.request.Request(
        f"{api_root}/audio/speech",
        data=json.dumps({
            "model": "tts-1",
            "voice": os.environ.get("OMNIVOICE_VOICE", "default"),
            "input": text,
            "response_format": "wav",
        }).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ.get('OMNIVOICE_API_KEY', 'not-needed-locally')}",
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"VoiceStudio TTS returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach VoiceStudio. Start its backend first.") from exc
    if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
        raise RuntimeError("VoiceStudio returned data that is not a WAV file.")
    output.write_bytes(audio)


async def run(query: str, output: Path) -> int:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        print('Install the optional client first: uv pip install "mcp>=2,<3"', file=sys.stderr)
        return 2

    print(
        f"This sends your query and chosen URLs to Parallel ({PARALLEL_MCP_URL}). "
        "No request is sent until you continue."
    )
    if input("Continue with web search? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("Cancelled before contacting Parallel.")
        return 0

    async with streamable_http_client(PARALLEL_MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            session_id = str(uuid.uuid4())
            search = await session.call_tool(
                "web_search",
                {"objective": query, "search_queries": [query], "session_id": session_id},
            )
            if getattr(search, "isError", False):
                print(result_text(search), file=sys.stderr)
                return 1
            text = result_text(search)
            print("\nSearch results:\n" + text)
            urls = search_urls(text)
            if not urls:
                print("No result URLs were returned, so there is nothing to fetch.")
                return 1
            try:
                selected = choose_urls(urls)
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 2

            fetched = await session.call_tool(
                "web_fetch",
                {
                    "urls": selected,
                    "objective": query[:200],
                    "search_queries": [query],
                    "session_id": session_id,
                    "full_content": False,
                },
            )
            if getattr(fetched, "isError", False):
                print(result_text(fetched), file=sys.stderr)
                return 1
            excerpts = result_text(fetched)
            print("\nFetched excerpts:\n" + excerpts)

    if not excerpts:
        print("The fetch returned no text to synthesize.")
        return 1
    if len(excerpts) > 4_096:
        print("Speech input is limited to the first 4,096 characters.")
        excerpts = excerpts[:4_096]

    service_root = os.environ.get("OMNIVOICE_API_URL", "http://localhost:3900").rstrip("/")
    print(
        f"\nThe selected excerpts will be sent to VoiceStudio at {service_root} "
        "(loopback by default). Check OMNIVOICE_API_URL."
    )
    if input("Synthesize with VoiceStudio? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("Cancelled before sending text to VoiceStudio.")
        return 0
    try:
        synthesize(excerpts, output)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Saved speech to {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Short search query, ideally 3–6 words")
    parser.add_argument("--output", type=Path, default=Path("spoken-research.wav"))
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.query, args.output))
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:
        print(f"Research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
