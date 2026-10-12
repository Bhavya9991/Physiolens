"""The two citation records on a PhysioNet project page.

The resource citation is the dataset itself. The original publication is the
paper associated with it, when the page has one. The platform citation for
PhysioNet as a whole is ignored.

A Copy BibTeX control is a hidden textarea. That block is the record. A
citation with no BibTeX is read from the labeled paragraph and its link.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import httpx

_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_YEAR = re.compile(r"\((?P<year>\d{4})(?:,[^)]*)?\)")
_BIB_FIELD = re.compile(
    r"(?P<key>[A-Za-z]\w*)\s*=\s*(?:\{(?P<braced>(?:[^{}]|\{[^{}]*\})*)\}|(?P<bare>\d+))",
    re.S,
)


def fetch_project_html(url: str) -> str:
    if not (url or "").startswith(("http://", "https://")):
        raise RuntimeError("This project has no PhysioNet page to read.")
    try:
        response = httpx.get(
            url,
            timeout=40.0,
            follow_redirects=True,
            headers={"User-Agent": "PhysioLens", "Accept": "text/html"},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError("The PhysioNet project page could not be read.") from exc
    return response.text


def parse_citations(html: str) -> list[dict]:
    """Resource citation, then original publication when the page has one."""
    records = []
    for section in _sections(html):
        kind = _kind(section["label"])
        if not kind:
            continue
        record = _from_bibtex(section["bibtex"], kind) if section["bibtex"] else _from_text(section, kind)
        if record and (record["doi"] or record["title"]):
            records.append(record)
    return records


def parse_bibtex(raw: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _BIB_FIELD.finditer(raw or ""):
        value = match.group("braced") if match.group("braced") is not None else match.group("bare") or ""
        fields[match.group("key").lower()] = _unwrap(value.strip())
    return fields


def _from_bibtex(raw: str, kind: str) -> dict:
    fields = parse_bibtex(raw)
    doi = _clean_doi(fields.get("doi") or "")
    url = (fields.get("url") or "").strip()
    if not url and doi:
        url = f"https://doi.org/{doi}"
    return _record(
        kind,
        title=fields.get("title") or "",
        authors=fields.get("author") or "",
        year=fields.get("year") or "",
        doi=doi,
        url=url,
        source="bibtex",
    )


def _from_text(section: dict, kind: str) -> dict:
    text = section["text"]
    links = section["links"]
    doi = ""
    url = ""
    for link in links:
        found = _DOI.search(link)
        if found:
            doi = _clean_doi(found.group(0))
            url = link
            break
    if not doi:
        found = _DOI.search(text)
        doi = _clean_doi(found.group(0)) if found else ""
    if not url and links:
        url = links[0]
    year_match = _YEAR.search(text)
    year = year_match.group("year") if year_match else ""
    authors = ""
    title = text
    if year_match:
        authors = text[: year_match.start()].strip(" .")
        rest = text[year_match.end() :].lstrip(" .")
        title = rest.split(". ")[0].strip().rstrip(".")
    return _record(kind, title=title, authors=authors, year=year, doi=doi, url=url, source="citation_text")


def _record(kind: str, title: str, authors: str, year: str, doi: str, url: str, source: str) -> dict:
    return {
        "kind": kind,
        "title": " ".join((title or "").split()),
        "authors": " ".join((authors or "").split()),
        "year": (year or "").strip(),
        "doi": _clean_doi(doi),
        "url": (url or "").strip(),
        "source": source,
    }


def _kind(label: str) -> str:
    text = (label or "").casefold()
    if "original publication" in text:
        return "original"
    if "standard citation for physionet" in text:
        return ""
    if "using this resource" in text:
        return "resource"
    return ""


def _clean_doi(value: str) -> str:
    text = (value or "").strip()
    lowered = text.casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.strip().rstrip(".").lower()


def _unwrap(value: str) -> str:
    text = value.strip()
    while len(text) >= 2 and text[0] == "{" and text[-1] == "}":
        text = text[1:-1].strip()
    return " ".join(text.split())


def _sections(html: str) -> list[dict]:
    parser = _CitationSections()
    parser.feed(html or "")
    parser.close()
    return parser.sections


class _CitationSections(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict] = []
        self._depth = 0
        self._mode = ""
        self._buf: list[str] = []
        self._current: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())
        if tag == "div" and "citation-section" in classes and self._depth == 0:
            self._current = {"label": "", "text": "", "links": [], "bibtex": ""}
            self._depth = 1
            return
        if not self._depth or self._current is None:
            return
        if tag == "div":
            self._depth += 1
        if tag == "span" and "citation-label" in classes:
            self._mode = "label"
            self._buf = []
        elif tag == "p" and "citation-text" in classes and not self._current["text"]:
            self._mode = "text"
            self._buf = []
        elif tag == "textarea" and not self._current["bibtex"]:
            self._mode = "bibtex"
            self._buf = []
        elif tag == "a" and self._mode == "text" and attr.get("href"):
            self._current["links"].append(attr["href"])

    def handle_endtag(self, tag: str) -> None:
        if self._mode and tag in {"span", "p", "textarea"} and self._current is not None:
            if self._mode == "bibtex":
                self._current["bibtex"] = "".join(self._buf).strip()
            else:
                text = " ".join("".join(self._buf).split())
                if self._mode == "label":
                    self._current["label"] = text
                elif self._mode == "text" and not self._current["text"]:
                    self._current["text"] = text
            self._mode = ""
            self._buf = []
        if self._depth and tag == "div":
            self._depth -= 1
            if self._depth == 0 and self._current is not None:
                self.sections.append(self._current)
                self._current = None

    def handle_data(self, data: str) -> None:
        if self._mode:
            self._buf.append(data)
