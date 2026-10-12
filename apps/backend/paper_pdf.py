"""Turn a PDF into the same sections the HTML parser produces.

Words keep their font size, so a heading is a short line set larger than the
body text. The first eight pages are enough for the abstract, the data
section, and the methods. Later pages are mostly results and references.
"""

from __future__ import annotations

import io
import re
from statistics import median

import httpx
import pdfplumber

_HEADING = re.compile(
    r"^(?:abstract|references|acknowledgements?|introduction|methods?|materials?(?:\s+and\s+methods)?|\d+(?:\.\d+){0,2}\s+\S.{0,80})$",
    re.I,
)


def fetch_pdf(url: str) -> tuple[bytes, str]:
    """Return the file bytes and a one-line note. Bytes are empty when it is not a PDF."""
    if not (url or "").startswith(("http://", "https://")):
        return b"", "the link is not an http address"
    host = url.split("/")[2] if "://" in url else "the host"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,*/*",
    }
    try:
        with httpx.stream("GET", url, timeout=25.0, follow_redirects=True, headers=headers) as response:
            if response.status_code >= 400:
                return b"", f"PDF {response.status_code} from {host}"
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > 12_000_000:
                    return b"", f"the PDF from {host} is larger than 12 MB, so it was not read"
                chunks.append(chunk)
            data = b"".join(chunks)
            kind = (response.headers.get("content-type") or "").casefold()
    except httpx.HTTPError as exc:
        return b"", f"PDF request failed for {host}: {exc.__class__.__name__}"
    if not data.startswith(b"%PDF") and "pdf" not in kind:
        return b"", f"{host} did not return a PDF"
    return data, f"read a PDF of {len(data)} bytes from {host}"


def pdf_sections(data: bytes) -> list[dict]:
    """Sections as {heading, text}. Empty when the file has no readable words."""
    if not data:
        return []
    lines: list[dict] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as document:
            for page in document.pages[:8]:
                words = page.extract_words(extra_attrs=["size"]) or []
                lines.extend(_lines(words))
    except Exception:
        return []
    return sections_from_lines(lines)


def sections_from_lines(lines: list[dict]) -> list[dict]:
    """Group sized lines into sections. A heading is larger than the body, or a known title."""
    usable = [line for line in lines if (line.get("text") or "").strip()]
    if not usable:
        return []
    body = median(line["size"] for line in usable)
    sections: list[dict] = []
    heading = "Paper text"
    parts: list[str] = []

    def flush() -> None:
        nonlocal parts
        text = _dehyphenate(parts)
        parts = []
        if text:
            sections.append({"heading": heading, "text": text})

    for line in usable:
        text = " ".join(line["text"].split())
        if _is_heading(text, float(line["size"]), body):
            flush()
            heading = text
            continue
        if _number_heavy(text):
            continue
        parts.append(text)
    flush()
    return sections


def _lines(words: list[dict]) -> list[dict]:
    buckets: dict[int, list[dict]] = {}
    for word in words:
        text = word.get("text") or ""
        if not text.strip():
            continue
        key = int(round(float(word.get("top") or 0)))
        buckets.setdefault(key, []).append(word)
    lines = []
    for top in sorted(buckets):
        group = sorted(buckets[top], key=lambda item: float(item.get("x0") or 0))
        sizes = [float(item.get("size") or 0) for item in group]
        text = " ".join(item.get("text") or "" for item in group)
        text = " ".join(text.split())
        if text:
            lines.append({"text": text, "size": median(sizes) if sizes else 0})
    return lines


def _is_heading(text: str, size: float, body: float) -> bool:
    words = text.split()
    if not words or len(words) > 12 or len(text) > 90 or _number_heavy(text):
        return False
    if size >= body + 1.5 and len(words) <= 8:
        return True
    return bool(_HEADING.match(text))


def _number_heavy(text: str) -> bool:
    return bool(text) and sum(character.isdigit() for character in text) > len(text) / 2


def _dehyphenate(lines: list[str]) -> str:
    if not lines:
        return ""
    text = lines[0]
    for line in lines[1:]:
        if text.endswith("-") and line[:1].islower():
            text = text[:-1] + line
        else:
            text = f"{text} {line}"
    return " ".join(text.split())
