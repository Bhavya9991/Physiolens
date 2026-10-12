"""SerpAPI calls used by agent runs.

Google Scholar finds the PhysioNet citation and the papers that cite it.
Google Search finds pages that are not in the PhysioNet catalog. A Google
AI Overview, when Google returns one, is fetched by a follow-up call.
Browse screens do not call this module.
"""

from __future__ import annotations

import re

import httpx

SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
_CITES_IN_LINK = re.compile(r"[?&]cites=(\d+)")
_NO_RESULTS = "hasn't returned any results"


def search_scholar(query: str, api_key: str, num: int = 5) -> list[dict]:
    """Scholar search by keywords. A cached empty result must not hide the record."""
    return _search(api_key, engine="google_scholar", q=query, num=num, no_cache=True)


def search_citing(cites_id: str, api_key: str, query: str = "", num: int = 5, start: int = 0) -> list[dict]:
    """Papers that cite one Scholar result. With a query, search inside that set.

    start is the next page. Each page is its own SerpApi search.
    """
    params = {"engine": "google_scholar", "cites": cites_id, "num": num, "no_cache": True}
    if start:
        params["start"] = start
    if query.strip():
        params["q"] = query.strip()
    return _search(api_key, **params)


def search_web(query: str, api_key: str, num: int = 5) -> list[dict]:
    """Ordinary Google results."""
    return _search(api_key, engine="google", q=query, num=num)


def google_overview(query: str, api_key: str) -> dict:
    """A Google search plus the AI Overview when Google includes one.

    The overview is prose and source links. It is not a yes or no. Google
    often returns no overview, and then text and references are empty.
    """
    payload = _payload(api_key, engine="google", q=query, no_cache=True)
    overview = _as_overview(payload)
    token = str(overview.get("page_token") or "")
    if token and not overview.get("text_blocks"):
        try:
            followed = _payload(api_key, engine="google_ai_overview", page_token=token, no_cache=True)
        except RuntimeError:
            followed = {}
        richer = _as_overview(followed)
        if richer.get("text_blocks") or richer.get("references"):
            overview = richer
    return {
        "organic": [_record(item) for item in payload.get("organic_results") or []],
        "text": _overview_text(overview),
        "references": _overview_refs(overview),
    }


def _search(api_key: str, **params) -> list[dict]:
    payload = _payload(api_key, **params)
    return [_record(item) for item in payload.get("organic_results") or []]


def _payload(api_key: str, **params) -> dict:
    try:
        response = httpx.get(
            SERPAPI_SEARCH_URL,
            params={**params, "api_key": api_key, "hl": "en"},
            timeout=40.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # The request URL contains the API key, so it must not be shown in the run.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 403 or str(exc).strip() in {"403 Forbidden", "403"}:
            raise RuntimeError(
                "SerpAPI refused the search with 403. The key still has searches left, "
                "so the usual cause is a local proxy blocking serpapi.com. "
                "Start the server in a normal terminal, then try the run again."
            ) from exc
        raise RuntimeError(f"SerpAPI search failed ({status or 'no response'}).") from exc
    payload = response.json()
    if payload.get("error"):
        message = str(payload["error"])
        # Scholar uses this sentence for an empty result set. It is not a failed request.
        if _NO_RESULTS in message.casefold() or "generate an ai overview" in message.casefold():
            return {}
        raise RuntimeError(message)
    return payload


def _as_overview(payload: dict) -> dict:
    overview = payload.get("ai_overview")
    if isinstance(overview, dict):
        return overview
    if payload.get("text_blocks") or payload.get("references"):
        return payload
    return {}


def _overview_text(overview: dict) -> str:
    parts: list[str] = []

    def walk(blocks: object) -> None:
        if not isinstance(blocks, list):
            return
        for block in blocks:
            if not isinstance(block, dict):
                continue
            piece = str(block.get("snippet") or block.get("text") or "").strip()
            if piece:
                parts.append(piece)
            walk(block.get("list"))
            walk(block.get("text_blocks"))

    walk(overview.get("text_blocks"))
    return "\n".join(parts)[:8000]


def _overview_refs(overview: dict) -> list[dict]:
    references = []
    for item in overview.get("references") or []:
        if not isinstance(item, dict):
            continue
        references.append(
            {
                "title": item.get("title") or "",
                "link": item.get("link") or "",
                "snippet": item.get("snippet") or "",
            }
        )
    return references[:8]


def _record(item: dict) -> dict:
    publication = item.get("publication_info") or {}
    inline = item.get("inline_links") or {}
    versions = inline.get("versions") or {}
    cited = inline.get("cited_by") or {}
    html_version = inline.get("html_version") or ""
    if isinstance(html_version, dict):
        html_version = html_version.get("link") or ""
    return {
        "title": item.get("title") or "",
        "link": item.get("link") or "",
        "snippet": item.get("snippet") or "",
        "summary": publication.get("summary") or "",
        "result_id": item.get("result_id") or "",
        "cited_by": _cites_id(item),
        "cited_by_total": int(cited.get("total") or 0),
        "cached_page_link": inline.get("cached_page_link") or item.get("cached_page_link") or "",
        "html_version": html_version,
        "html_resource": _html_resource(item),
        "pdf_links": _pdf_links(item),
        "versions_link": versions.get("serpapi_scholar_link") or "",
    }


def _html_resource(item: dict) -> str:
    for resource in item.get("resources") or []:
        if str(resource.get("file_format") or "").upper() == "HTML" and resource.get("link"):
            return resource["link"]
    return ""


def _pdf_links(item: dict) -> list[str]:
    found: list[str] = []

    def add(url: str) -> None:
        link = (url or "").strip()
        if link.startswith(("http://", "https://")) and link not in found:
            found.append(link)

    link = item.get("link") or ""
    if link.split("?", 1)[0].casefold().endswith(".pdf"):
        add(link)
    for resource in item.get("resources") or []:
        url = resource.get("link") or ""
        kind = str(resource.get("file_format") or "").upper()
        if kind == "PDF" or url.split("?", 1)[0].casefold().endswith(".pdf"):
            add(url)
    return found


def _cites_id(item: dict) -> str:
    cited = (item.get("inline_links") or {}).get("cited_by") or {}
    if cited.get("cites_id"):
        return str(cited["cites_id"])
    match = _CITES_IN_LINK.search(cited.get("link") or "")
    return match.group(1) if match else ""
