"""Find similar resources.

A fixed sequence for every PhysioNet project. The catalog comparison uses
fields the catalog already stores. A page outside PhysioNet is compared only
after its text has been read. A soft field is kept only when a quote from
that text supports it.
"""

from __future__ import annotations

import os
import re
from datetime import date
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from typing import TypedDict

from apps.agents.control import stopping
from apps.agents.llm import POLICY, ask
from apps.agents.pages import fetch_public_text
from apps.agents.records import is_physionet, remember, step
from apps.backend.catalog_view import label_for, project_by_slug, projects
from apps.backend.citations import fetch_project_html
from apps.backend.paper_html import dataset_about
from apps.backend.runlog import append_log
from apps.backend.scholar import search_web

CATALOG_CAP = 8
FAMILY_CAP = 6
QUERY_CAP = 4
WEB_CAP = 6
_CONTENT_SLUG = re.compile(r"/content/([a-z0-9][a-z0-9-]{1,80})/", re.I)
_KIND_WORD = {
    "Database": "dataset",
    "Challenge": "challenge",
    "Software": "software",
    "Model": "model",
}


class Evidence(BaseModel):
    field: str = Field(description="modality, task, labels, population, annotation, or kind.")
    value: str = Field(description="The short value this quote supports.")
    quote: str = Field(description="A contiguous quote copied from the supplied text.")


class ResourceReading(BaseModel):
    modality: list[str] = Field(description="Recording or data types the text states. Empty when it does not.")
    tasks: list[str] = Field(description="Tasks the text states. Empty when it does not.")
    labels: list[str] = Field(description="Labels or outcomes the text states. Empty when it does not.")
    population: str = Field(description="Who was recorded, or empty.")
    annotation: str = Field(description="How labels were made, or empty.")
    kind: str = Field(description="database, challenge, software, or model, or empty.")
    peer_hints: list[str] = Field(description="Up to two other resource names. Empty for a candidate page.")
    evidence: list[Evidence] = Field(description="One quote for each non-empty value.")


class ComparisonNote(BaseModel):
    title: str = Field(description="The destination title, copied exactly.")
    explanation: str = Field(description="Two sentences. First the shared values, then what differs or was not stated.")


class ComparisonBatch(BaseModel):
    notes: list[ComparisonNote] = Field(description="One note for each destination, in the same order.")


class ResourceState(TypedDict, total=False):
    run_id: str
    action: str
    project: dict
    steps: list
    profile: dict
    page_text: str
    page_html: str
    family: list
    peers: list
    outside: list
    summary: str
    report: dict


def build_resources():
    graph = StateGraph(ResourceState)
    graph.add_node("profile_seed", profile_seed)
    graph.add_node("catalog_peers", catalog_peers)
    graph.add_node("web_queries", web_queries)
    graph.add_node("read_pages", read_pages)
    graph.add_node("compare", compare)
    graph.add_edge(START, "profile_seed")
    graph.add_edge("profile_seed", "catalog_peers")
    graph.add_edge("catalog_peers", "web_queries")
    graph.add_edge("web_queries", "read_pages")
    graph.add_edge("read_pages", "compare")
    graph.add_edge("compare", END)
    return graph.compile()


def profile_seed(state: ResourceState) -> dict:
    project = state["project"]
    text, note, html = _seed_text(state, project)
    reading = _read_model(state, "profile_seed", text, seed=True) if text else _empty_profile()
    profile = keep_quoted(reading, text, allow_hints=True, title=project.get("title") or "")
    profile["kind"] = project.get("resource_type") or ""
    profile["access"] = project.get("access_policy") or ""
    why = note or "The catalog fields are exact. A soft field is kept only when the page text contains its quote."
    steps = remember(
        state,
        step("profile_seed", "Read this resource", why, "physionet", project.get("source_url") or "", []),
    )
    return {"profile": profile, "page_text": text, "page_html": html, "steps": steps}


def catalog_peers(state: ResourceState) -> dict:
    project = state["project"]
    if stopping(state.get("run_id")):
        raise _stopped()
    family = family_projects(state.get("page_html") or "", project.get("slug") or "")
    peers = rank_catalog(project, projects(), {item["slug"] for item in family})
    items = [_peer_item(peer) for peer in peers]
    why = (
        f"{len(peers)} other projects share a subject, a data form, or a topic."
        if peers
        else "No other project shares a subject, a data form, or a topic."
    )
    if family:
        why += f" {len(family)} projects are linked from this page and kept apart from the peers."
    steps = remember(
        {"steps": state.get("steps") or [], "run_id": state.get("run_id")},
        step("catalog_peers", "Find resources in this catalog", why, "catalog", project.get("title") or "", items),
    )
    return {"family": family, "peers": peers, "steps": steps}


def web_queries(state: ResourceState) -> dict:
    project = state["project"]
    queries = build_queries(project, state.get("profile") or {})
    hits = []
    key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not key:
        why = "SERPAPI_API_KEY is not set, so the web search was skipped. The catalog comparison still stands."
    else:
        for query in queries:
            if stopping(state.get("run_id")):
                raise _stopped()
            if len(hits) >= WEB_CAP:
                break
            _log(state, "web_queries", f"Waiting for web results: {query}")
            try:
                batch = search_web(query, key, num=5)
            except RuntimeError as exc:
                _log(state, "web_queries", f"{query}: {exc}")
                continue
            for item in batch:
                link = item.get("link") or ""
                if not link or is_physionet(link) or _seen(hits, link):
                    continue
                hits.append({**item, "found_by": query})
                if len(hits) >= WEB_CAP:
                    break
        why = f"{len(hits)} pages outside PhysioNet, from {len(queries)} fixed queries."
    steps = remember(
        {"steps": state.get("steps") or [], "run_id": state.get("run_id")},
        step("web_queries", "Search the web", why, "google", " · ".join(queries), [_web_item(item) for item in hits]),
    )
    return {"outside": hits, "steps": steps}


def read_pages(state: ResourceState) -> dict:
    pages = []
    for item in state.get("outside") or []:
        if stopping(state.get("run_id")):
            raise _stopped()
        title = item.get("title") or "Untitled"
        _log(state, "read_pages", f"Waiting for {title}.")
        text = fetch_public_text(item.get("link") or "", limit=6000)
        if len(text) < 400:
            pages.append({**item, "relation": "unread", "profile": _empty_profile(), "text": ""})
            _log(state, "read_pages", f"{title}: the page could not be read.")
            continue
        reading = _read_model(state, "read_pages", text, seed=False)
        profile = keep_quoted(reading, text, allow_hints=False, title=title)
        pages.append({**item, "relation": "peer", "profile": profile, "text": text})
        _log(state, "read_pages", f"{title}: read {len(text)} characters.")
    read = sum(1 for page in pages if page["relation"] == "peer")
    why = f"{read} of {len(pages)} outside pages could be read."
    steps = remember(
        {"steps": state.get("steps") or [], "run_id": state.get("run_id")},
        step("read_pages", "Read pages outside PhysioNet", why, "web", "", [_web_item(page) for page in pages]),
    )
    return {"outside": pages, "steps": steps}


def compare(state: ResourceState) -> dict:
    project = state["project"]
    profile = state.get("profile") or _empty_profile()
    seed = seed_card(project, profile)
    catalog_cards = explain_similar(state, seed, [catalog_card(project, peer) for peer in state.get("peers") or []])
    outside_cards = web_cards(project, state.get("outside") or [])
    family_cards = [family_card(item) for item in state.get("family") or []]
    summary = (
        f"{_count(len(catalog_cards), 'similar resource')} in this catalog. "
        f"{_count(len(outside_cards), 'similar page')} outside PhysioNet."
    )
    report = {
        "kind": "resources",
        "retrieved_on": date.today().isoformat(),
        "method": (
            "A catalog resource is shown when it shares a subject, a data form, a topic, or a kind. "
            f"Outside pages are the first results of up to {QUERY_CAP} web searches, capped at {WEB_CAP}. "
            "A web result is kept from its title and snippet when it is a dataset in the same area, including when the page itself could not be opened. "
            "This is not a ranking of every resource."
        ),
        "summary": summary,
        "seed": seed,
        "catalog": catalog_cards,
        "outside": outside_cards,
        "family": family_cards,
    }
    _log(state, "compare", "Assembled the comparison.")
    steps = remember(
        {"steps": state.get("steps") or [], "run_id": state.get("run_id")},
        step("compare", "Assemble the comparison", summary, "catalog", project.get("title") or "", []),
    )
    return {"summary": summary, "report": report, "steps": steps}


def keep_quoted(reading: dict, text: str, *, allow_hints: bool, title: str) -> dict:
    """Drop any soft value whose quote is not in the supplied text."""
    body = _squash(text)
    accepted = []
    for item in reading.get("evidence") or []:
        quote = str(item.get("quote") or "")
        value = str(item.get("value") or "").strip()
        if len(_squash(quote)) < 20 or _squash(quote) not in body:
            continue
        if not value or _squash(value) not in _squash(quote):
            continue
        accepted.append({"field": (item.get("field") or "").casefold(), "value": value})

    def values(field: str) -> list[str]:
        names = {field, "tasks"} if field == "task" else {field}
        seen = []
        for item in accepted:
            if item["field"] in names and item["value"] not in seen:
                seen.append(item["value"])
        return seen[:4]

    kind = values("kind")
    hints = []
    if allow_hints:
        title_norm = _squash(title)
        for hint in reading.get("peer_hints") or []:
            name = " ".join(str(hint).split())
            if not name or _squash(name) in title_norm or name in hints:
                continue
            hints.append(name)
            if len(hints) == 2:
                break
    return {
        "modality": values("modality"),
        "tasks": values("task"),
        "labels": values("labels"),
        "population": (values("population")[:1] or [""])[0],
        "annotation": (values("annotation")[:1] or [""])[0],
        "kind": _canon_kind(kind[0]) if kind else "",
        "access": "",
        "peer_hints": hints,
    }


def build_queries(project: dict, profile: dict) -> list[str]:
    """The dataset name first, then the words that would find a peer dataset."""
    word = _KIND_WORD.get(project.get("resource_type") or "", "resource")
    name = ((project.get("title") or "resource").split(":")[0]).strip()
    queries = [f'"{name}" {word}']
    words = _content_words(name)[:4]
    if len(words) >= 2:
        queries.append(f"{' '.join(words)} {word}")
    for hint in (profile.get("peer_hints") or [])[:2]:
        if _useful_hint(hint):
            queries.append(f'"{hint.strip()}" {word}')
    modality = " ".join(profile.get("modality") or [])
    task = " ".join((profile.get("tasks") or [])[:1])
    if modality and task:
        queries.append(f"{modality} {task} {word}")
    elif modality:
        queries.append(f"{modality} {word}")
    kept = []
    for query in queries:
        clean = " ".join(query.split())
        if clean and clean.casefold() not in {item.casefold() for item in kept}:
            kept.append(clean)
        if len(kept) == QUERY_CAP:
            break
    return kept


def web_cards(project: dict, pages: list[dict]) -> list[dict]:
    """Keep a search hit from its title and snippet. A blocked page still counts."""
    cards = []
    for page in pages:
        if not _web_keep(project, page):
            continue
        cards.append(_web_card(project, page))
        if len(cards) == WEB_CAP:
            break
    return cards


def _web_keep(project: dict, page: dict) -> bool:
    title = page.get("title") or ""
    blob = f"{title} {page.get('snippet') or ''}"
    if _JUNK.search(blob) and not _RESOURCE_WORD.search(title):
        return False
    shared = set(_content_words(project.get("title") or "")) & set(_tokens(blob))
    if not shared:
        return False
    return bool(_RESOURCE_WORD.search(blob)) or any(len(word) >= 8 for word in shared)


def _web_card(project: dict, page: dict) -> dict:
    title = (page.get("title") or "Untitled").replace("...", "").strip()
    about = _first_sentence(page.get("snippet") or "")
    shared = sorted(set(_content_words(project.get("title") or "")) & set(_tokens(f"{title} {page.get('snippet') or ''}")))
    mention = f" It mentions {_join(shared[:3])}." if shared else ""
    why = f"{_short_name(title)}.{mention}"
    if about:
        why = f"{_short_name(title)}. {about}{mention}"
    opened = page.get("relation") != "unread"
    if not opened:
        why = f"{why} The page itself could not be opened, so this is the search result."
    return {
        "title": page.get("title") or "Untitled",
        "link": page.get("link") or "",
        "kind": "",
        "access": "",
        "relation": "web",
        "about": about,
        "dimensions": [],
        "why": " ".join(why.split()),
    }


_STOP = {
    "about", "after", "also", "and", "are", "based", "been", "clinical", "data", "database",
    "dataset", "from", "have", "health", "into", "large", "medical", "multi", "open", "over",
    "patient", "public", "records", "scale", "study", "that", "the", "this", "using", "with",
}
_HOST_HINTS = {"figshare", "kaggle", "github", "zenodo", "physionet", "arxiv", "pubmed"}
_RESOURCE_WORD = re.compile(r"\b(dataset|database|corpus|collection|benchmark|repository)\b", re.I)
_JUNK = re.compile(r"how to |usage metrics|revision history|cite or embed|sign in|cookie policy|download data", re.I)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9-]{2,}", (text or "").casefold())


def _content_words(title: str) -> list[str]:
    words = []
    for token in _tokens(title):
        if token in _STOP or token in words:
            continue
        if len(token) >= 5 or any(character.isdigit() for character in token):
            words.append(token)
    return words


def _useful_hint(hint: str) -> bool:
    text = " ".join((hint or "").split())
    if len(text) < 4 or text.casefold() in _HOST_HINTS:
        return False
    return True


def family_projects(html: str, seed_slug: str) -> list[dict]:
    found = []
    seen = {seed_slug}
    for match in _CONTENT_SLUG.finditer(html or ""):
        slug = match.group(1).casefold()
        if slug in seen:
            continue
        seen.add(slug)
        project = project_by_slug(slug)
        if project is None:
            continue
        found.append(project)
        if len(found) == FAMILY_CAP:
            break
    return found


def rank_catalog(seed: dict, rows: list[dict], skip: set[str], limit: int = CATALOG_CAP) -> list[dict]:
    scored = []
    for other in rows:
        if other.get("slug") == seed.get("slug") or other.get("slug") in skip:
            continue
        shared_subject = set(seed.get("subject") or []) & set(other.get("subject") or [])
        shared_form = set(seed.get("data_form") or []) & set(other.get("data_form") or [])
        shared_topics = {topic.casefold() for topic in seed.get("topics") or []} & {
            topic.casefold() for topic in other.get("topics") or []
        }
        if not shared_subject and not shared_form and not shared_topics:
            continue
        score = 3 * len(shared_subject) + 3 * len(shared_form) + len(shared_topics)
        scored.append((score, (other.get("title") or "").casefold(), other))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [other for _score, _title, other in scored[:limit]]


def catalog_card(seed: dict, other: dict) -> dict:
    dimensions = [
        _set_dim("Subject", seed.get("subject") or [], other.get("subject") or [], seed_required=True),
        _set_dim("Data", seed.get("data_form") or [], other.get("data_form") or [], seed_required=True),
        _shared_only(_set_dim("Topic", seed.get("topics") or [], other.get("topics") or [], seed_required=False)),
        _text_dim("Kind", seed.get("resource_type") or "", other.get("resource_type") or ""),
        _text_dim("Access", seed.get("access_policy") or "", other.get("access_policy") or ""),
    ]
    dimensions = [item for item in dimensions if item]
    return {
        "title": other.get("title") or "Untitled",
        "link": other.get("source_url") or "",
        "kind": other.get("resource_type") or "",
        "access": other.get("access_policy") or "",
        "relation": "peer",
        "about": _first_sentence(other.get("short_description") or ""),
        "dimensions": dimensions,
        "line": why_line(dimensions),
        "why": why_line(dimensions),
    }


def outside_card(seed: dict, profile: dict, page: dict) -> dict:
    other = page.get("profile") or {}
    dimensions = [
        _list_dim("Modality", profile.get("modality") or [], other.get("modality") or []),
        _list_dim("Task", profile.get("tasks") or [], other.get("tasks") or []),
        _text_dim("Kind", _canon_kind(seed.get("resource_type") or ""), other.get("kind") or ""),
    ]
    dimensions = [item for item in dimensions if item]
    return {
        "title": page.get("title") or "Untitled",
        "link": page.get("link") or "",
        "kind": _display_kind(other.get("kind") or ""),
        "access": "",
        "relation": "peer",
        "about": _first_sentence(page.get("snippet") or ""),
        "dimensions": dimensions,
        "line": why_line(dimensions),
        "why": why_line(dimensions),
    }


def explain_similar(state: dict, seed: dict, cards: list[dict]) -> list[dict]:
    """Keep resources that share a field, then ask the model to say what that means."""
    kept = [card for card in cards if _is_similar(card)]
    if not kept:
        return []
    if stopping(state.get("run_id")):
        raise _stopped()
    _log(state, "compare", f"Waiting for the model to explain {_count(len(kept), 'similar resource')}.")
    notes = _ask_notes(state, seed, kept)
    for card in kept:
        card["why"] = notes.get(_squash(card.get("title") or "")) or plain_insight(seed, card)
        card.pop("line", None)
    return kept


def _is_similar(card: dict) -> bool:
    return any(item.get("verdict") == "same" for item in card.get("dimensions") or [])


def _ask_notes(state: dict, seed: dict, cards: list[dict]) -> dict:
    try:
        batch = ask(
            ComparisonBatch,
            "Name the destination, then the source, using their titles. "
            "Say what the destination is, using its description when one is given. "
            "Then say what the two resources share, in ordinary words. "
            "Say the kind of each resource by name, such as 'CXR-LT is a challenge' and 'Chest ImaGenome is a database'. "
            "Never write 'on this project', 'on the other', 'differs', or 'differ'. "
            "Do not invent a resource, a paper, or a number. "
            "Copy each destination title exactly. " + POLICY,
            _note_prompt(seed, cards),
            timeout=60,
        )
    except RuntimeError as exc:
        _log(state, "compare", f"The explanation was not written. {exc}")
        return {}
    found = {}
    notes = list(batch.notes or [])
    for note in notes:
        text = _usable_note(note.explanation)
        title = _squash(note.title)
        if title and text:
            found[title] = text
    if len(notes) == len(cards):
        for card, note in zip(cards, notes):
            key = _squash(card.get("title") or "")
            text = _usable_note(note.explanation)
            if key and text and key not in found:
                found[key] = text
    return found


def _note_prompt(seed: dict, cards: list[dict]) -> str:
    source = [
        f"Title: {seed.get('title') or 'Untitled'}",
        f"Kind: {seed.get('kind') or 'not stated'}",
        f"Access: {seed.get('access') or 'not stated'}",
        f"Subject: {', '.join(seed.get('subjects') or []) or 'not stated'}",
        f"Data: {', '.join(seed.get('forms') or []) or 'not stated'}",
        f"Modality: {', '.join(seed.get('modality') or []) or 'not stated'}",
        f"Task: {', '.join(seed.get('tasks') or []) or 'not stated'}",
    ]
    blocks = ["Source", *source, "", "Destinations"]
    for index, card in enumerate(cards, start=1):
        facts = []
        for item in card.get("dimensions") or []:
            detail = item.get("detail") or item.get("verdict") or ""
            facts.append(f"{item.get('field')}: {detail} ({item.get('verdict')})")
        blocks.append(
            f"{index}. Title: {card.get('title') or 'Untitled'}\n"
            f"Kind: {card.get('kind') or 'not stated'}. Access: {card.get('access') or 'not stated'}.\n"
            f"Description: {card.get('about') or 'none'}\n"
            f"Facts: {'; '.join(facts)}"
        )
    return "\n".join(blocks)


def plain_insight(seed: dict, card: dict) -> str:
    """Name both resources. Say the kind of each one, then what they share."""
    source = _short_name(seed.get("title") or "This project")
    other = _short_name(card.get("title") or "This resource")
    source_kind = _canon_kind(seed.get("kind") or "")
    other_kind = _canon_kind(card.get("kind") or "")
    sentences = []
    if other_kind and source_kind and other_kind == source_kind:
        sentences.append(f"{other} is {_a_kind(other_kind)}, like {source}.")
    elif other_kind:
        sentences.append(f"{other} is {_a_kind(other_kind)}.")
    about = _first_sentence(card.get("about") or "")
    if about and _squash(about) not in _squash(other):
        sentences.append(about if about.endswith(".") else about + ".")
    if source_kind and other_kind and source_kind != other_kind:
        sentences.append(f"{source} is {_a_kind(source_kind)}.")
    shared = _shared_clause(card.get("dimensions") or [])
    access = _access_sentence(source, other, seed.get("access") or "", card.get("access") or "", card.get("dimensions") or [])
    if shared:
        sentences.append(shared)
    if access:
        sentences.append(access)
    return " ".join(sentences) or "The fields that could be checked were not stated."


def _shared_clause(dimensions: list[dict]) -> str:
    sentences = []
    for item in dimensions:
        if item.get("verdict") != "same":
            continue
        detail = _brief_values(item.get("detail") or "")
        field = item.get("field") or ""
        if field == "Data" and detail:
            sentences.append(f"Both include {detail}.")
        elif field == "Subject" and detail:
            sentences.append(f"Both are about {detail}.")
        elif field == "Topic" and detail:
            sentences.append(f"Shared topics are {detail}.")
        elif field in {"Modality", "Task"} and detail:
            sentences.append(f"Both involve {detail}.")
    return " ".join(sentences)


def _access_sentence(source: str, other: str, source_access: str, other_access: str, dimensions: list[dict]) -> str:
    verdict = next((item.get("verdict") for item in dimensions if item.get("field") == "Access"), "")
    left = source_access.strip()
    right = other_access.strip()
    if verdict == "same" and left:
        return f"Both are {left.lower()}."
    if verdict == "different" and left and right:
        return f"{source} is {left.lower()}. {other} is {right.lower()}."
    return ""


def _brief_values(detail: str, limit: int = 3) -> str:
    parts = []
    for piece in str(detail or "").split(","):
        text = " ".join(piece.split())
        if not text or " on this project" in text.casefold() or " on the other" in text.casefold():
            continue
        if text[:1].isupper() and (len(text) < 2 or text[1:2].islower()):
            text = text[0].lower() + text[1:]
        if text not in parts:
            parts.append(text)
        if len(parts) == limit:
            break
    return _join(parts)


def _a_kind(kind: str) -> str:
    word = (_display_kind(_canon_kind(kind)) or kind).lower()
    if word == "software":
        return "a software project"
    return f"a {word}"


def _short_name(title: str) -> str:
    text = " ".join((title or "").split())
    if ":" in text:
        head = text.split(":", 1)[0].strip()
        if len(head) >= 3:
            return head
    return text[:90]


def _first_sentence(text: str) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    for mark in (". ", "? ", "! "):
        at = clean.find(mark)
        if 0 <= at <= 280:
            clean = clean[: at + 1]
            break
    else:
        clean = clean[:220].rstrip(" ,;")
        if clean and not clean.endswith("."):
            clean += "."
    return clean[:240]


def _usable_note(text: str) -> str:
    clean = " ".join((text or "").split())
    folded = clean.casefold()
    if any(phrase in folded for phrase in ("on this project", "on the other", "differs", "differ")):
        return ""
    return clean[:600]


def value_why(dimensions: list[dict]) -> str:
    """Kept for older callers. New cards use plain_insight, which names both resources."""
    return plain_insight({"title": "This project", "kind": "", "access": ""}, {"title": "The other resource", "dimensions": dimensions})


def family_card(project: dict) -> dict:
    return {
        "title": project.get("title") or "Untitled",
        "link": project.get("source_url") or "",
        "kind": project.get("resource_type") or "",
        "access": project.get("access_policy") or "",
        "relation": "family",
        "dimensions": [],
        "why": "Linked from this project page.",
    }


def seed_card(project: dict, profile: dict) -> dict:
    return {
        "title": project.get("title") or "Untitled",
        "url": project.get("source_url") or "",
        "kind": project.get("resource_type") or "",
        "access": project.get("access_policy") or "",
        "subjects": [label_for(item) for item in project.get("subject") or []],
        "forms": [label_for(item) for item in project.get("data_form") or []],
        "topics": list(project.get("topics") or [])[:6],
        "modality": profile.get("modality") or [],
        "tasks": profile.get("tasks") or [],
        "population": profile.get("population") or "",
        "annotation": profile.get("annotation") or "",
    }


def why_line(dimensions: list[dict]) -> str:
    same = [item["field"].lower() for item in dimensions if item["verdict"] == "same"]
    different = [item["field"].lower() for item in dimensions if item["verdict"] == "different"]
    parts = []
    if same:
        parts.append(f"Same {_join(same)}.")
    if different:
        verb = "differs" if len(different) == 1 else "differ"
        parts.append(f"{_join(different).capitalize()} {verb}.")
    if parts:
        return " ".join(parts)
    return "The fields that could be checked were not stated."


def _shared_only(item: dict | None) -> dict | None:
    """A long unmatched list, such as topics, is not a reason to show the resource."""
    if item and item.get("verdict") == "same":
        return item
    return None


def _set_dim(field: str, left: list, right: list, *, seed_required: bool) -> dict | None:
    if not left and not right:
        return None
    shared = [item for item in left if item in set(right)]
    if shared:
        return {"field": field, "verdict": "same", "detail": _named(shared)}
    if left and right:
        return {
            "field": field,
            "verdict": "different",
            "detail": f"{_named(left)} on this project, {_named(right)} on the other",
        }
    if seed_required and left and not right:
        return {"field": field, "verdict": "unknown", "detail": f"{_named(left)} stated only for this project"}
    return None


def _list_dim(field: str, left: list, right: list) -> dict | None:
    if not left and not right:
        return None
    if not left or not right:
        known = left or right
        side = "this project" if left else "the other"
        return {"field": field, "verdict": "unknown", "detail": f"{', '.join(known)} stated only for {side}"}
    shared = [item for item in left if _squash(item) in {_squash(other) for other in right}]
    if shared:
        return {"field": field, "verdict": "same", "detail": ", ".join(shared)}
    return {
        "field": field,
        "verdict": "different",
        "detail": f"{', '.join(left)} on this project, {', '.join(right)} on the other",
    }


def _text_dim(field: str, left: str, right: str) -> dict | None:
    if not left and not right:
        return None
    if not left or not right:
        known = left or right
        side = "this project" if left else "the other"
        return {"field": field, "verdict": "unknown", "detail": f"{_shown(field, known)} stated only for {side}"}
    same = _canon_kind(left) == _canon_kind(right) if field == "Kind" else _squash(left) == _squash(right)
    if same:
        return {"field": field, "verdict": "same", "detail": _shown(field, left)}
    return {
        "field": field,
        "verdict": "different",
        "detail": f"{_shown(field, left)} on this project, {_shown(field, right)} on the other",
    }


def _named(values: list) -> str:
    labels = []
    for item in values:
        label = label_for(str(item))
        if label and label not in labels:
            labels.append(label)
    return ", ".join(labels)


def _shown(field: str, value: str) -> str:
    if field == "Kind":
        return _display_kind(_canon_kind(value)) or value
    return value


def _canon_kind(value: str) -> str:
    text = (value or "").strip().casefold()
    if text in {"database", "dataset", "data"}:
        return "database"
    if text in _KIND_WORD.values() or text in {"database", "challenge", "software", "model"}:
        return text if text != "dataset" else "database"
    for label, word in _KIND_WORD.items():
        if text == label.casefold() or text == word:
            return word if word != "dataset" else "database"
    return text


def _display_kind(kind: str) -> str:
    return {"database": "Database", "challenge": "Challenge", "software": "Software", "model": "Model"}.get(kind, kind)


def _count(number: int, singular: str) -> str:
    word = singular if number == 1 else singular + "s"
    return f"{number} {word}"


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _seed_text(state: ResourceState, project: dict) -> tuple[str, str, str]:
    url = project.get("source_url") or ""
    description = project.get("short_description") or ""
    try:
        _log(state, "profile_seed", "Waiting for the PhysioNet project page.")
        html = fetch_project_html(url)
    except RuntimeError as exc:
        _log(state, "profile_seed", str(exc))
        return description, "The project page could not be read. Catalog fields are still compared.", ""
    about = dataset_about(html)
    text = "\n\n".join(part for part in (description, about) if part)
    if about:
        return text, "", html
    return text, "The page had no abstract or data description to quote. Catalog fields are still compared.", html


def _read_model(state: ResourceState, step_id: str, text: str, *, seed: bool) -> dict:
    role = "This is the seed project. peer_hints may name up to two other resources." if seed else "This is a candidate page. peer_hints must be empty."
    _log(state, step_id, "Waiting for the model to read the page text.")
    try:
        reading = ask(
            ResourceReading,
            "Read only the supplied text. Fill a field only when that text states it. "
            "Every non-empty value needs a quote copied from the text, and the value must appear inside that quote. "
            + role
            + " "
            + POLICY,
            text[:6000],
            timeout=60,
        )
    except RuntimeError as exc:
        _log(state, step_id, f"The model call failed. {exc}")
        return _empty_profile()
    return reading.model_dump()


def _empty_profile() -> dict:
    return {
        "modality": [],
        "tasks": [],
        "labels": [],
        "population": "",
        "annotation": "",
        "kind": "",
        "access": "",
        "peer_hints": [],
        "evidence": [],
    }


def _peer_item(project: dict) -> dict:
    return {
        "title": project.get("title") or "Untitled",
        "link": project.get("source_url") or "",
        "detail": project.get("resource_type") or "",
        "label": "catalog",
        "access": project.get("access_policy") or "",
        "slug": project.get("slug") or "",
    }


def _web_item(item: dict) -> dict:
    return {
        "title": item.get("title") or "Untitled",
        "link": item.get("link") or "",
        "detail": item.get("snippet") or item.get("why") or "",
        "label": "web",
        "access": "",
        "slug": "",
    }


def _seen(hits: list[dict], link: str) -> bool:
    key = _link_key(link)
    return any(_link_key(item.get("link") or "") == key for item in hits)


def _link_key(link: str) -> str:
    parsed = urlparse(link)
    return (parsed.netloc + parsed.path).casefold().rstrip("/")


def _squash(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _log(state: dict, step_id: str, message: str) -> None:
    append_log(state.get("run_id") or "", step_id, message)


def _stopped():
    from apps.agents.control import RunStopped

    return RunStopped()
