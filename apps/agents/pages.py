"""Download the visible text of a public paper page.

The model has no web access of its own. A citing paper is readable only when
this fetch returns text. Private hosts, PDFs, and failed downloads stay unread.
"""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

_SKIP_TAGS = {"script", "style", "noscript"}


def fetch_public_text(url: str, limit: int = 8000) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if not _public_host(parsed.hostname):
        return ""
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True, event_hooks={"request": [_reject_private]}) as client:
            response = client.get(url, headers={"User-Agent": "PhysioLens"})
    except (httpx.HTTPError, RuntimeError, socket.gaierror):
        return ""
    if response.status_code >= 400:
        return ""
    kind = (response.headers.get("content-type") or "").casefold()
    if "html" not in kind and "text/plain" not in kind:
        return ""
    text = response.text if "html" not in kind else _html_text(response.text)
    return " ".join(text.split())[:limit]


def _reject_private(request: httpx.Request) -> None:
    host = request.url.host
    if request.url.scheme not in {"http", "https"} or not host or not _public_host(host):
        raise RuntimeError("That page is not a public web address.")


def _public_host(host: str) -> bool:
    name = host.strip("[]").casefold().rstrip(".")
    if not name or name in {"localhost", "localhost.localdomain"} or name.endswith(".local") or name.endswith(".internal"):
        return False
    try:
        infos = socket.getaddrinfo(name, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            return False
    return True


def _html_text(raw: str) -> str:
    parser = _VisibleText()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return ""
    return " ".join(parser.parts)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())
