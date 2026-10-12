"""Turn a paper's HTML into named sections.

Two wrappers show up. A Google Scholar cache is a stack of positioned lines
from a PDF, with no headings. An article page, such as PMC or arXiv HTML,
has real headings. The wrapper is detected from the document after download.
The model is not asked to parse the HTML.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from statistics import median
from urllib.parse import urlparse

import httpx

_TOP = re.compile(r"top:\s*(\d+)", re.I)
_LEFT = re.compile(r"left:\s*(\d+)", re.I)
_FONT = re.compile(r"font-size:\s*(\d+)px", re.I)
_HEADING = re.compile(
    r"^(?:abstract|references|acknowledgements?|\d+(?:\.\d+){0,2}\s+\S.{0,80})$",
    re.I,
)
_SKIP_SECTION = re.compile(
    r"result|discussion|conclusion|related\s+work|reference|acknowledge|appendix|limitation|ethic|conflict|navigation|subscribe",
    re.I,
)
_DATA = re.compile(r"\b(data|datasets?|corpus|corpora|materials?|cohorts?|benchmarks?)\b", re.I)
_METHOD = re.compile(r"\b(methods?|approaches?|models?|architectures?|implementations?|techniques?)\b", re.I)
_SETUP = re.compile(r"\b(experiments?|evaluations?|setups?|protocols?|tasks?|problems?)\b", re.I)
_INTRO = re.compile(r"\bintroduc", re.I)
_ABOUT = re.compile(r"abstract|background|method|data description|usage note|statistic|format", re.I)
_SKIP_HEAD = re.compile(r"permalink|cite|cookie|navigation|footer", re.I)


def fetch_article_html(url: str) -> tuple[str, str]:
    """Return the page body and a one-line note. The body is empty when it cannot be read."""
    if not (url or "").startswith(("http://", "https://")):
        return "", "the link is not an http address"
    host = urlparse(url).netloc or "the host"
    try:
        response = httpx.get(
            url,
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
    except httpx.HTTPError as exc:
        return "", f"request failed for {host}: {exc.__class__.__name__}"
    if response.status_code >= 400:
        return "", f"{response.status_code} from {host}"
    kind = (response.headers.get("content-type") or "").casefold()
    text = response.text[:1_500_000]
    if "pdf" in kind or not _looks_like_html(text, kind):
        return "", f"{host} returned {kind or 'an unknown type'}"
    return text, f"read {len(text)} characters from {host}"


def _looks_like_html(text: str, content_type: str) -> bool:
    if "html" in content_type or "xml" in content_type:
        return True
    sample = text.lstrip()[:300].casefold()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<html" in sample


def parse_paper(html: str) -> list[dict]:
    """Sections as {heading, text}. Empty when the document has no readable body."""
    if not html:
        return []
    if _is_scholar_cache(html):
        return _cache_sections(html)
    return _article_sections(html)


def select_bundle(sections: list[dict], limit: int = 7000) -> str:
    """The sections that say how a dataset was used, which task, and which techniques.

    Results, discussion, and related work stay out, so the model is not handed findings
    or methods that belong to other papers.
    """
    grouped = {"abstract": [], "data": [], "method": [], "setup": [], "intro": []}
    for section in sections:
        kind = _heading_kind(section.get("heading") or "")
        if kind in grouped:
            grouped[kind].append(section)
    chunks: list[str] = []
    used = 0

    def add(heading: str, text: str, cap: int) -> None:
        nonlocal used
        body = " ".join((text or "").split())
        if not body or used >= limit:
            return
        piece = body[:cap]
        chunks.append(f"{heading}\n{piece}")
        used += len(piece)

    for section in grouped["abstract"][:1]:
        add(section["heading"], section["text"], 1600)
    for section in grouped["data"][:2]:
        add(section["heading"], section["text"], 1600)
    for section in grouped["method"][:2]:
        add(section["heading"], section["text"], 1600)
    for section in grouped["setup"][:1]:
        add(section["heading"], section["text"], 1200)
    for section in grouped["intro"][:1]:
        add(section["heading"], section["text"], 800)
    if not chunks and sections:
        first = next((section for section in sections if _heading_kind(section.get("heading") or "") != "skip"), sections[0])
        text = first.get("text") or ""
        if _paperish(text):
            add(first.get("heading") or "Paper text", text, 1600)
    return "\n\n".join(chunks)[:limit]


def dataset_about(html: str) -> str:
    """Abstract, data description, and usage notes from a PhysioNet project page."""
    kept = []
    for section in parse_paper(html):
        heading = section.get("heading") or ""
        if _SKIP_SECTION.search(heading) or not _ABOUT.search(heading):
            continue
        kept.append(f"{heading}\n{' '.join(section['text'].split())[:900]}")
    return "\n\n".join(kept)[:3500]


_CHROME = re.compile(r"\b(cookie|subscribe|sign in|access provided|institutional login|citation tools)\b", re.I)
_LANDING = re.compile(r"\b(bibtex|mods xml|arxivlabs)\b", re.I)


def _paperish(text: str) -> bool:
    """Prose from a paper, rather than a publisher menu, a citation widget, or a login wall."""
    body = " ".join((text or "").split())
    if len(body) < 200 or _LANDING.search(body[:2500]):
        return False
    return len(_CHROME.findall(body[:2500])) < 2


def _heading_kind(heading: str) -> str:
    name = re.sub(r"^\d+(?:\.\d+)*\s*", "", heading or "").strip()
    if not name or _SKIP_SECTION.search(name):
        return "skip"
    # A paper title often contains a word like "task". A section heading is short.
    if len(name) > 80:
        return ""
    if re.search(r"\babstract\b", name, re.I):
        return "abstract"
    if _METHOD.search(name):
        return "method"
    if _DATA.search(name):
        return "data"
    if _SETUP.search(name):
        return "setup"
    if _INTRO.search(name):
        return "intro"
    return ""


def _is_scholar_cache(html: str) -> bool:
    compact = html.replace(" ", "").casefold()
    return "position:absolute" in compact and "<nobr" in compact


def _cache_sections(html: str) -> list[dict]:
    parser = _CacheLines()
    parser.feed(html)
    parser.close()
    ordered = _reading_order(parser.pages)
    if not ordered:
        return []
    fonts = [line["font"] for line in ordered if line["font"]]
    body = int(median(fonts)) if fonts else 12
    sections: list[dict] = []
    heading = "Paper text"
    buffer: list[str] = []

    def flush() -> None:
        text = _dehyphenate(buffer)
        if text:
            sections.append({"heading": heading, "text": text})

    for line in ordered:
        if _is_heading(line["text"], line["font"], body):
            flush()
            heading = line["text"]
            buffer = []
            continue
        if _number_heavy(line["text"]):
            continue
        buffer.append(line["text"])
    flush()
    return sections


def _reading_order(pages: list[list[dict]]) -> list[dict]:
    ordered: list[dict] = []
    for page in pages:
        if not page:
            continue
        for column in _columns(page):
            ordered.extend(sorted(column, key=lambda line: line["top"]))
    return ordered


def _columns(lines: list[dict]) -> list[list[dict]]:
    lefts = [line["left"] for line in lines]
    if max(lefts) - min(lefts) < 180:
        return [lines]
    split = (min(lefts) + max(lefts)) / 2
    left = [line for line in lines if line["left"] < split]
    right = [line for line in lines if line["left"] >= split]
    return [column for column in (left, right) if column]


def _is_heading(text: str, font: int, body: int) -> bool:
    words = text.split()
    if not words or len(words) > 12 or len(text) > 90:
        return False
    if _number_heavy(text):
        return False
    if font >= body + 1 and len(words) <= 8:
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


def _article_sections(html: str) -> list[dict]:
    parser = _ArticleText()
    parser.feed(html)
    parser.close()
    parser.flush()
    sections = []
    for heading, text in parser.sections:
        if _SKIP_HEAD.search(heading):
            continue
        body = " ".join(text.split())
        if body:
            sections.append({"heading": heading, "text": body})
    return sections


class _CacheLines(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pages: list[list[dict]] = [[]]
        self._font = 0
        self._open = False
        self._depth = 0
        self._top = 0
        self._left = 0
        self._line_font = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        style = attr.get("style", "")
        found = _FONT.search(style)
        if found:
            self._font = int(found.group(1))
        if tag == "hr":
            self._close_line()
            self.pages.append([])
            return
        if tag != "div":
            return
        top = _TOP.search(style)
        left = _LEFT.search(style)
        positioned = "position:absolute" in style.replace(" ", "").casefold() and top and left
        if positioned:
            self._close_line()
            self._open = True
            self._depth = 1
            self._top = int(top.group(1))
            self._left = int(left.group(1))
            self._line_font = self._font
            self._buf = []
            return
        if self._depth:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                self._close_line()

    def _close_line(self) -> None:
        if not self._open:
            return
        text = " ".join("".join(self._buf).split())
        self._open = False
        self._depth = 0
        self._buf = []
        if text:
            self.pages[-1].append({"top": self._top, "left": self._left, "font": self._line_font, "text": text})

    def handle_data(self, data: str) -> None:
        if self._open:
            self._buf.append(data)


class _ArticleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[tuple[str, str]] = []
        self._skip = 0
        self._mode = ""
        self._heading = "Paper text"
        self._buf: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "nav", "header", "footer"}:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in {"h1", "h2", "h3"}:
            self._close_paragraph()
            self._save()
            self._mode = "heading"
            self._buf = []
        elif tag in {"p", "li"}:
            self._mode = "body"
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "nav", "header", "footer"} and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if tag in {"h1", "h2", "h3"} and self._mode == "heading":
            heading = " ".join("".join(self._buf).split())
            if heading:
                self._heading = heading
            self._mode = ""
            self._buf = []
        elif tag in {"p", "li"}:
            self._close_paragraph()

    def handle_data(self, data: str) -> None:
        if self._skip or not self._mode:
            return
        self._buf.append(data)

    def _close_paragraph(self) -> None:
        if self._mode != "body":
            return
        text = " ".join("".join(self._buf).split())
        self._buf = []
        self._mode = ""
        if text:
            self._parts.append(text)

    def _save(self) -> None:
        if not self._parts:
            return
        self.sections.append((self._heading, " ".join(self._parts)))
        self._parts = []

    def flush(self) -> None:
        self._close_paragraph()
        self._save()
