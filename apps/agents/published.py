"""Explore published research.

A fixed sequence. The PhysioNet page supplies the resource citation and, when
present, the original publication. Each one is resolved on Scholar. Up to 10
citing papers, after duplicates are removed, are read. A usage card is written
when the paper text shows the dataset was used. Otherwise the report says
whether the paper is worth opening for its own work.
"""

from __future__ import annotations

import os
import re
from datetime import date

from langgraph.graph import END, START, StateGraph
from typing import TypedDict

from apps.agents.control import stopping
from apps.agents.records import remember, step
from apps.agents.usage import (
    CLASS_LABEL,
    answer_class,
    classify_overviews,
    fetch_overview,
    load_paper_sections,
    read_paper,
    overview_query,
    write_dataset_brief,
)
from apps.backend.citations import fetch_project_html, parse_citations
from apps.backend.paper_html import dataset_about, select_bundle
from apps.backend.runlog import append_log
from apps.backend.scholar import search_citing, search_scholar

CITING_PAGE_SIZE = 20
CITING_PAGE_CAP = 5
SAMPLE_SIZE = 10


def sample_note(count: int) -> str:
    return (
        f"These {count} papers are the first citing papers Scholar returned for the resource citation "
        "and the original publication, after duplicates were removed. "
        f"The search stops at {SAMPLE_SIZE} papers. "
        "This is not a ranking by how often those papers were themselves cited."
    )


SAMPLE_NOTE = sample_note(SAMPLE_SIZE)
_DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.I)


class PublishedState(TypedDict, total=False):
    run_id: str
    action: str
    project: dict
    steps: list
    citations: list
    about: str
    seeds: list
    candidates: list
    seed_items: list
    candidate_items: list
    summary: str
    report: dict


def build_published():
    graph = StateGraph(PublishedState)
    graph.add_node("parse_page", parse_page)
    graph.add_node("resolve_seeds", resolve_seeds)
    graph.add_node("collect_citing", collect_citing)
    graph.add_node("usage_cards", usage_cards)
    graph.add_node("insights", insights)
    graph.add_edge(START, "parse_page")
    graph.add_edge("parse_page", "resolve_seeds")
    graph.add_edge("resolve_seeds", "collect_citing")
    graph.add_edge("collect_citing", "usage_cards")
    graph.add_edge("usage_cards", "insights")
    graph.add_edge("insights", END)
    return graph.compile()


def parse_page(state: PublishedState) -> dict:
    project = state["project"]
    url = project.get("source_url") or ""
    _log(state, "page_citations", "Waiting for the PhysioNet project page.")
    html = fetch_project_html(url)
    _log(state, "page_citations", f"Read the project page ({len(html)} characters).")
    citations = parse_citations(html)
    kept = ", ".join(_kind_label(record["kind"]) for record in citations) or "none"
    _log(state, "page_citations", f"Parsed citations: {kept}.")
    about = dataset_about(html) or (project.get("short_description") or "")
    items = [_citation_item(record) for record in citations]
    if citations:
        why = "The resource citation is kept. The original publication is kept when the page has one. The PhysioNet platform citation is ignored."
    else:
        why = "This page has no resource citation to search."
    steps = remember(state, step("page_citations", "Read the PhysioNet citations", why, "physionet", url, items))
    return {"citations": citations, "about": about, "steps": steps}


def resolve_seeds(state: PublishedState) -> dict:
    seeds = []
    items = []
    steps = list(state.get("steps") or [])
    for kind in ("resource", "original"):
        record = next((item for item in state.get("citations") or [] if item["kind"] == kind), None)
        if record is None:
            why = "This page has no original publication, so only the resource citation is searched." if kind == "original" else "No resource citation was parsed."
            steps = remember({"steps": steps, "run_id": state.get("run_id")}, step(f"seed_{kind}", _seed_title(kind), why, "google_scholar", "", []))
            continue
        hit, how = _resolve(record, _logger(state, f"seed_{kind}"))
        if hit is None:
            why = "Scholar returned no matching record for the DOI or the title, so this citation has no trail."
            steps = remember(
                {"steps": steps, "run_id": state.get("run_id")},
                step(f"seed_{kind}", _seed_title(kind), why, "google_scholar", record.get("doi") or record.get("title") or "", []),
            )
            seeds.append({"kind": kind, "citation": record, "hit": None, "query": record.get("doi") or record.get("title") or ""})
            continue
        total = int(hit.get("cited_by_total") or 0)
        band = cite_band(total)
        why = f"Matched by {how}. Scholar reports {total} citations for this record ({band})."
        item = _seed_item(hit, kind, total, band)
        items.append(item)
        steps = remember(
            {"steps": steps, "run_id": state.get("run_id")},
            step(f"seed_{kind}", _seed_title(kind), why, "google_scholar", record.get("doi") or record.get("title") or "", [item]),
        )
        seeds.append({"kind": kind, "citation": record, "hit": hit, "query": record.get("doi") or record.get("title") or "", "cited_by_total": total, "band": band})
    return {"seeds": seeds, "seed_items": items, "steps": steps}


def collect_citing(state: PublishedState) -> dict:
    combined = []
    steps = list(state.get("steps") or [])
    for seed in state.get("seeds") or []:
        if len(dedupe_candidates(combined)) >= SAMPLE_SIZE:
            break
        kind = seed["kind"]
        hit = seed.get("hit") or {}
        cites_id = (hit.get("cited_by") or "").strip()
        if not hit or not cites_id:
            why = "There is no citation id, so no citing papers were requested."
            steps = remember(
                {"steps": steps, "run_id": state.get("run_id")},
                step(f"citing_{kind}", f"Papers that cite the {kind}", why, "google_scholar", "", []),
            )
            continue
        papers, calls = _pages_for_sample(cites_id, combined, kind, _logger(state, f"citing_{kind}"))
        stamped = []
        for paper in papers:
            item = dict(paper)
            item["trails"] = [kind]
            stamped.append(item)
        combined.extend(stamped)
        total = int(seed.get("cited_by_total") or 0)
        why = (
            f"Scholar reports {total} citations for this record. "
            f"{calls} SerpApi {'search' if calls == 1 else 'searches'} collected citing papers. "
            f"Each page is a separate search. The search stops at {SAMPLE_SIZE} papers."
        )
        steps = remember(
            {"steps": steps, "run_id": state.get("run_id")},
            step(f"citing_{kind}", f"Papers that cite the {kind}", why, "google_scholar", f"cites:{cites_id}", [_candidate_item(item) for item in stamped[:8]]),
        )
    candidates = dedupe_candidates(combined)[:SAMPLE_SIZE]
    _log(state, "candidates", f"Kept {len(candidates)} papers after removing duplicates.")
    items = [_candidate_item(item) for item in candidates]
    found = [seed for seed in state.get("seeds") or [] if (seed.get("hit") or {}).get("cited_by")]
    if not state.get("citations"):
        summary = "The PhysioNet page had no resource citation, so no Scholar search was run."
    elif not found:
        summary = "No Google Scholar record with a citation trail was found, so there are no candidate papers."
    else:
        summary = sample_note(len(candidates))
    steps = remember(
        {"steps": steps, "run_id": state.get("run_id")},
        step("candidates", "Deduplicated candidate papers", summary, "google_scholar", "", items[:8]),
    )
    return {"candidates": candidates, "candidate_items": items, "summary": summary, "steps": steps}


def dataset_name(project: dict) -> str:
    title = (project.get("title") or "this dataset").strip()
    short = title.split(":")[0].strip()
    return short or title


def classify(state: PublishedState) -> dict:
    papers = [dict(item) for item in state.get("candidates") or []]
    dataset = dataset_name(state.get("project") or {})
    steps = list(state.get("steps") or [])
    if not papers:
        steps = remember({"steps": steps, "run_id": state.get("run_id")}, step("classify", "Classify how each paper cites the dataset", "There are no candidate papers to classify.", "google", "", []))
        return {"candidates": papers, "steps": steps}
    for paper in papers:
        title = paper.get("title") or "Untitled"
        query = overview_query(title, dataset)
        _log(state, "classify", f"Waiting for the AI Overview of “{title}”.")
        try:
            paper["overview"] = fetch_overview(title, dataset, _serp_key())
        except RuntimeError as exc:
            paper["overview"] = ""
            _log(state, "classify", f"AI Overview failed for “{title}”: {exc}")
        text = (paper.get("overview") or "").strip()
        if text:
            _log(state, "classify", f"AI Overview for “{title}”: {text[:1800]}")
        else:
            _log(state, "classify", f"AI Overview for “{title}”: no text was returned.")
        paper.update(answer_class(text, query))
        _log(state, "classify", _judgement_line(title, text, paper.get("routing") or ""))
    note = classify_overviews(papers, dataset)
    items = [_classified_item(paper) for paper in papers]
    steps = remember(
        {"steps": steps, "run_id": state.get("run_id")},
        step("classify", "Check whether each paper used the dataset", note, "google", overview_query(papers[0].get("title") or "", dataset), items[:8]),
    )
    return {"candidates": papers, "candidate_items": items, "steps": steps}


def usage_cards(state: PublishedState) -> dict:
    papers = [dict(item) for item in state.get("candidates") or []]
    dataset = dataset_name(state.get("project") or {})
    steps = list(state.get("steps") or [])
    written = 0
    halted = False
    for paper in papers:
        if stopping(state.get("run_id")):
            halted = True
            break
        title = paper.get("title") or "Untitled"
        notes: list[str] = []
        try:
            sections, kind, notes = load_paper_sections(paper, _serp_key(), _logger(state, "usage_cards", _short(title)))
        except RuntimeError as exc:
            sections, kind = [], ""
            notes = [str(exc)]
            _log(state, "usage_cards", f"{title}: {exc}")
        bundle = select_bundle(sections) if sections else ""
        names = [block.split("\n", 1)[0] for block in bundle.split("\n\n") if block.strip()]
        if len(bundle) >= 250:
            _log(state, "usage_cards", f"Waiting for the model to read “{_short(title)}”. Sections: {', '.join(names)}.")
            reading = read_paper(paper, dataset, sections)
        else:
            reading = None
            if sections:
                _log(state, "usage_cards", f"“{_short(title)}” had no paper sections, so the model was not called.")
        model_note = paper.pop("card_note", "")
        if model_note:
            _log(state, "usage_cards", f"“{_short(title)}”: {model_note}")
        if reading and reading.get("card"):
            paper["card"] = reading["card"]
            paper["explore"] = None
            paper["card_source"] = kind
            paper["usage_class"] = "experimental_use"
            paper["why"] = reading["card"].get("how_used") or ""
            written += 1
            _log(state, "usage_cards", f"“{_short(title)}” uses the dataset.")
            continue
        paper["card"] = None
        if reading and reading.get("explore"):
            paper["explore"] = reading["explore"]
            paper["routing"] = "report_only"
            paper["usage_class"] = "background_reference"
            paper["why"] = reading["explore"].get("why_open") or ""
            _log(state, "usage_cards", f"“{_short(title)}” does not use the dataset.")
            continue
        paper["explore"] = None
        paper["routing"] = "report_only"
        paper["usage_class"] = "unclear"
        paper["why"] = unread_reason(notes, model_note, bool(sections))
    items = [_classified_item(paper) for paper in papers if paper.get("card")]
    explored = sum(1 for paper in papers if paper.get("explore"))
    unclear = sum(1 for paper in papers if paper.get("usage_class") == "unclear")
    if halted:
        why = "Stopped while reading the citing papers."
    else:
        why = usage_sentence({"users": written, "candidates": len(papers), "other": explored, "unclear": unclear})
    steps = remember({"steps": steps, "run_id": state.get("run_id")}, step("usage_cards", "Read each citing paper", why, "web", "", items[:8]))
    return {"candidates": papers, "steps": steps}


def insights(state: PublishedState) -> dict:
    papers = [dict(item) for item in state.get("candidates") or []]
    counts = _counts(papers)
    if papers:
        _log(state, "insights", "Assembled the report.")
        summary = usage_sentence(counts)
        report = {
            "retrieved_on": date.today().isoformat(),
            "empty": False,
            "method": sample_note(counts["candidates"]),
            "counts": counts,
            "papers": [_report_paper(paper) for paper in papers],
            **_report_sources(state),
        }
    else:
        name = dataset_name(state.get("project") or {})
        description = state.get("about") or (state.get("project") or {}).get("short_description") or ""
        _log(state, "insights", "Waiting for a short description of the dataset.")
        brief = write_dataset_brief(name, description)
        _log(state, "insights", "The description was written from the project page.")
        summary = "No published papers that cite this dataset were found."
        report = {
            "retrieved_on": date.today().isoformat(),
            "empty": True,
            "notice": summary,
            "dataset_summary": brief,
            "method": "",
            "counts": counts,
            "papers": [],
            **_report_sources(state),
        }
    steps = remember(
        {"steps": list(state.get("steps") or []), "run_id": state.get("run_id")},
        step("insights", "Assemble the usage report", summary, "model", dataset_name(state.get("project") or {}), []),
    )
    return {
        "candidates": papers,
        "candidate_items": [_classified_item(paper) for paper in papers],
        "summary": summary,
        "report": report,
        "steps": steps,
    }


def _report_sources(state: PublishedState) -> dict:
    project = state.get("project") or {}
    dois = []
    for record in state.get("citations") or []:
        doi = (record.get("doi") or "").strip().rstrip(".")
        if doi and doi not in dois:
            dois.append(doi)
    return {"source_url": project.get("source_url") or "", "dois": dois}


def cite_band(total: int) -> str:
    """Bands for the seed's Scholar citation count. Scholar supplies the integer."""
    if total >= 200:
        return "heavily cited"
    if total >= 20:
        return "moderately cited"
    return "lightly cited"


def dedupe_candidates(papers: list[dict]) -> list[dict]:
    """One row per paper. A paper that cites both records keeps both trails."""
    order: list[str] = []
    found: dict[str, dict] = {}
    for paper in papers:
        key = _dedupe_key(paper)
        if key in found:
            current = found[key]
            for trail in paper.get("trails") or []:
                if trail not in current["trails"]:
                    current["trails"].append(trail)
            for field in ("cached_page_link", "html_version", "html_resource", "versions_link", "cited_by", "snippet", "summary"):
                if not current.get(field) and paper.get(field):
                    current[field] = paper[field]
            merged = list(current.get("pdf_links") or [])
            for link in paper.get("pdf_links") or []:
                if link not in merged:
                    merged.append(link)
            current["pdf_links"] = merged
            continue
        item = dict(paper)
        item["trails"] = list(paper.get("trails") or [])
        found[key] = item
        order.append(key)
    return [found[key] for key in order]


def _resolve(citation: dict, note=None) -> tuple[dict | None, str]:
    doi = (citation.get("doi") or "").strip()
    title = (citation.get("title") or "").strip()

    def say(message: str) -> None:
        if note:
            note(message)

    if doi:
        say(f"Waiting for Google Scholar: {doi}")
        hits = search_scholar(doi, _serp_key(), num=5)
        say(f"Google Scholar returned {len(hits)} records for that DOI.")
        chosen = _choose(hits, citation)
        if chosen is not None:
            return chosen, "DOI"
    if title:
        say(f"Waiting for Google Scholar: {title}")
        hits = search_scholar(title, _serp_key(), num=5)
        say(f"Google Scholar returned {len(hits)} records for that title.")
        chosen = _choose(hits, citation)
        if chosen is not None:
            return chosen, "title"
    return None, ""


def _choose(hits: list[dict], citation: dict) -> dict | None:
    if not hits:
        return None
    doi = (citation.get("doi") or "").lower()
    if doi:
        for hit in hits:
            if doi in _blob(hit):
                return hit
    if len(hits) == 1:
        return hits[0]
    title = citation.get("title") or ""
    for hit in hits:
        if titles_match(title, hit.get("title") or ""):
            return hit
    return None


def _pages(cites_id: str) -> tuple[list[dict], int]:
    return _pages_until(cites_id, CITING_PAGE_CAP * CITING_PAGE_SIZE)


def _pages_for_sample(cites_id: str, combined: list[dict], kind: str, note=None) -> tuple[list[dict], int]:
    """Keep requesting pages until the shared sample has 10 unique papers."""
    found: list[dict] = []
    calls = 0
    for page in range(CITING_PAGE_CAP):
        stamped = [dict(paper, trails=[kind]) for paper in found]
        if len(dedupe_candidates([*combined, *stamped])) >= SAMPLE_SIZE:
            break
        if note:
            note(f"Waiting for citing papers, page {page + 1}.")
        batch = search_citing(cites_id, _serp_key(), num=CITING_PAGE_SIZE, start=page * CITING_PAGE_SIZE)
        calls += 1
        if note:
            note(f"Page {page + 1} returned {len(batch)} papers.")
        if not batch:
            break
        found.extend(batch)
        if len(batch) < CITING_PAGE_SIZE:
            break
    return found, calls


def _pages_until(cites_id: str, limit: int) -> tuple[list[dict], int]:
    found: list[dict] = []
    calls = 0
    for page in range(CITING_PAGE_CAP):
        if len(found) >= limit:
            break
        batch = search_citing(cites_id, _serp_key(), num=CITING_PAGE_SIZE, start=page * CITING_PAGE_SIZE)
        calls += 1
        if not batch:
            break
        found.extend(batch)
        if len(batch) < CITING_PAGE_SIZE:
            break
    return found[:limit], calls


def _dedupe_key(paper: dict) -> str:
    for source in (paper.get("link") or "", paper.get("snippet") or "", paper.get("summary") or ""):
        match = _DOI_IN_TEXT.search(source)
        if match:
            return "doi:" + match.group(0).lower().rstrip(".")
    title = _norm(paper.get("title") or "")
    if len(title) >= 12:
        return "title:" + title
    if paper.get("result_id"):
        return "id:" + paper["result_id"]
    return "link:" + (paper.get("link") or "").casefold()


def _blob(hit: dict) -> str:
    return " ".join(
        [
            hit.get("link") or "",
            hit.get("snippet") or "",
            hit.get("title") or "",
            hit.get("summary") or "",
        ]
    ).lower()


def _citation_item(record: dict) -> dict:
    detail = record["source"]
    if record.get("doi"):
        detail = f"DOI {record['doi']}"
    elif record.get("url"):
        detail = record["url"]
    return {
        "title": record.get("title") or record["kind"],
        "link": record.get("url") or "",
        "detail": detail,
        "label": record["kind"],
        "access": "",
        "slug": "",
    }


def _seed_item(hit: dict, kind: str, total: int, band: str) -> dict:
    return {
        "title": hit.get("title") or "Untitled",
        "link": hit.get("link") or "",
        "detail": f"{kind}. Scholar reports {total} citations ({band}).",
        "label": "seed",
        "access": "",
        "slug": "",
    }


def _count_phrase(count: int, singular: str, plural: str = "") -> str:
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def _counts(papers: list[dict]) -> dict:
    users = sum(1 for paper in papers if paper.get("card"))
    unclear = sum(1 for paper in papers if paper.get("usage_class") == "unclear")
    return {
        "candidates": len(papers),
        "users": users,
        "other": len(papers) - users - unclear,
        "unclear": unclear,
    }


def usage_sentence(counts: dict) -> str:
    """One sentence for the sample: found to use it, do not use it, could not be read."""
    users = int(counts.get("users") or 0)
    total = int(counts.get("candidates") or 0)
    other = int(counts.get("other") or 0)
    unclear = int(counts.get("unclear") or 0)
    papers = "paper" if total == 1 else "papers"
    lead = f"{users} of {total} {papers} can be found to use this dataset"
    if other and unclear:
        return f"{lead} whereas {other} {_does_not(other)} use it, and {unclear} could not be read."
    if other:
        return f"{lead} whereas {other} {_does_not(other)} use it."
    if unclear:
        return f"{lead}, and {unclear} could not be read."
    return f"{lead}."


def _does_not(count: int) -> str:
    return "does not" if count == 1 else "do not"


_PUBLISHERS = {
    "mdpi.com": "MDPI",
    "sciencedirect.com": "ScienceDirect",
    "ieeexplore.ieee.org": "IEEE Xplore",
    "link.springer.com": "Springer",
    "springer.com": "Springer",
    "journals.sagepub.com": "SAGE Journals",
    "sagepub.com": "SAGE Journals",
    "cell.com": "Cell Press",
    "dl.acm.org": "the ACM Digital Library",
    "nature.com": "Nature",
    "arxiv.org": "arXiv",
    "aclanthology.org": "the ACL Anthology",
    "pmc.ncbi.nlm.nih.gov": "PubMed Central",
}
_STATUS_NOTE = re.compile(r"(?:PDF\s+)?(?P<code>\d{3})\s+from\s+(?P<host>[A-Za-z0-9.-]+)")
_READ_HTML = re.compile(r"read\s+\d+\s+characters\s+from\s+([A-Za-z0-9.-]+)", re.I)
_READ_PDF = re.compile(r"read a PDF of\s+\d+\s+bytes\s+from\s+([A-Za-z0-9.-]+)", re.I)


_GENERIC_UNREAD = "The paper text could not be read."


def apply_logged_reasons(run: dict) -> dict:
    """Fill a plain unread reason from the run log when the stored line is still generic.

    Older runs saved one sentence for every failure. The log already names the
    host and the status, so the report can say that without reading the paper again.
    """
    result = run.get("result") or {}
    report = result.get("report") if isinstance(result, dict) else None
    papers = (report or {}).get("papers") or []
    if not any(paper.get("why") == _GENERIC_UNREAD for paper in papers):
        return run
    from apps.backend.runlog import read_log

    log = read_log(run.get("id") or "")
    buckets = _log_notes(log)
    for paper in papers:
        if paper.get("why") != _GENERIC_UNREAD or paper.get("usage_class") != "unclear":
            continue
        title = paper.get("title") or ""
        notes = _notes_for_title(title, buckets)
        if not notes:
            continue
        paper["why"] = unread_reason(notes, "", _log_had_sections(title, log))
    return run


def _log_notes(log: str) -> list[tuple[str, list[str]]]:
    buckets: dict[str, list[str]] = {}
    order: list[str] = []
    for raw in (log or "").splitlines():
        parts = raw.split("\t")
        if len(parts) < 3 or parts[1] != "usage_cards" or ": " not in parts[2]:
            continue
        stem, note = parts[2].split(": ", 1)
        if stem.startswith("Waiting") or len(stem) < 12:
            continue
        key = stem.removesuffix("…")
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(note)
    return [(key, buckets[key]) for key in order]


def _notes_for_title(title: str, buckets: list[tuple[str, list[str]]]) -> list[str]:
    best = ""
    notes: list[str] = []
    for stem, found in buckets:
        if title.startswith(stem) and len(stem) > len(best):
            best = stem
            notes = found
    return notes


def _log_had_sections(title: str, log: str) -> bool:
    stem = title if len(title) <= 72 else title[:69]
    return any(stem in line and "had no paper sections" in line for line in (log or "").splitlines())


def unread_reason(notes: list[str], card_note: str = "", had_sections: bool = False) -> str:
    """A plain reason when the paper text never became a usage card or an explore note."""
    note = " ".join((card_note or "").split())
    folded = note.casefold()
    if "did not say what the paper is about" in folded:
        return "The paper opened, but the reading never said what the work is about."
    if "no usable sections" in folded:
        return "The page opened, but it did not include enough of the paper to read."
    if note:
        return "The paper was downloaded, but the reading did not finish."

    blocked = ""
    scholar_closed = False
    html_host = ""
    pdf_host = ""
    pdf_refused = False
    failed = False
    missing = False
    too_big = False
    no_link = False
    for raw in notes or []:
        text = " ".join(raw.split())
        lowered = text.casefold()
        if "no cache link" in lowered or "no html link" in lowered:
            no_link = True
            continue
        if "larger than 12 mb" in lowered:
            too_big = True
            continue
        if "did not return a pdf" in lowered or "returned " in lowered and "pdf" in lowered:
            pdf_refused = True
        status = _STATUS_NOTE.search(text)
        if status:
            code = status.group("code")
            host = status.group("host")
            if "scholar" in host.casefold():
                scholar_closed = code in {"401", "403", "429"}
                continue
            if code in {"401", "403", "429"}:
                blocked = host
            elif code == "404":
                missing = True
            continue
        if "request failed" in lowered:
            failed = True
            continue
        read_pdf = _READ_PDF.search(text)
        if read_pdf:
            pdf_host = read_pdf.group(1)
            continue
        read_html = _READ_HTML.search(text)
        if read_html:
            html_host = read_html.group(1)

    if blocked and not pdf_host:
        name = _publisher(blocked)
        if scholar_closed:
            return f"{name} would not serve the paper, and the Scholar copy was unavailable."
        return f"{name} would not serve the paper text."
    if too_big:
        return "The PDF was too large to read."
    if pdf_host and had_sections:
        return "A PDF was downloaded, but it did not include enough of the paper to read."
    if pdf_host:
        return "A PDF was downloaded, but the words could not be pulled out of it."
    if html_host and (pdf_refused or not pdf_host):
        if had_sections:
            return "Only a short publisher page came back, not enough of the paper to read."
        return "The publisher page opened, but it was not the paper itself, and no PDF came back."
    if missing:
        return "The link to the paper no longer opens."
    if failed:
        return "The paper page did not respond."
    if no_link:
        return "Scholar did not include a link to the paper text."
    if scholar_closed:
        return "The Scholar copy of the paper was unavailable, and no other copy could be opened."
    return "The paper text could not be opened."


def _publisher(host: str) -> str:
    name = (host or "").removeprefix("www.").casefold()
    known = _PUBLISHERS.get(name)
    if known:
        return known
    return f"The site {name or 'that hosted the paper'}"


def _report_paper(paper: dict) -> dict:
    return {
        "title": paper.get("title") or "Untitled",
        "link": paper.get("link") or "",
        "byline": paper.get("summary") or "",
        "cited_by_total": int(paper.get("cited_by_total") or 0),
        "usage_class": paper.get("usage_class") or "unclear",
        "label": CLASS_LABEL.get(paper.get("usage_class") or "", CLASS_LABEL["unclear"]),
        "usage_tags": paper.get("usage_tags") or [],
        "confidence": paper.get("confidence") or "low",
        "why": paper.get("why") or "",
        "evidence": paper.get("evidence") or "",
        "card": paper.get("card"),
        "explore": paper.get("explore"),
    }


def _classified_item(paper: dict) -> dict:
    label = CLASS_LABEL.get(paper.get("usage_class") or "", "cites")
    return {
        "title": paper.get("title") or "Untitled",
        "link": paper.get("link") or "",
        "detail": paper.get("why") or "",
        "label": label,
        "access": paper.get("confidence") or "",
        "slug": "",
    }


def _candidate_item(paper: dict) -> dict:
    trails = paper.get("trails") or []
    via = " and ".join(trails)
    sentence = f"Cites the {via} record." if via else "Citing paper."
    total = int(paper.get("cited_by_total") or 0)
    if total:
        sentence += f" This paper lists {total} citations."
    return {
        "title": paper.get("title") or "Untitled",
        "link": paper.get("link") or "",
        "detail": sentence,
        "label": "cites",
        "access": "",
        "slug": "",
    }


def _kind_label(kind: str) -> str:
    if kind == "original":
        return "original publication"
    return kind or "none"


def _seed_title(kind: str) -> str:
    if kind == "original":
        return "Scholar record for the original publication"
    return "Scholar record for the resource"


def titles_match(candidate: str, title: str) -> bool:
    """True when two titles name the same paper, including a shortened Scholar title."""
    left = _norm(candidate)
    right = _norm(title)
    if len(left) < 12 or len(right) < 12:
        return False
    if left in right or right in left:
        return True
    left_tokens = [token for token in left.split() if len(token) > 2]
    right_tokens = set(right.split())
    if len(left_tokens) < 4:
        return False
    overlap = sum(1 for token in left_tokens if token in right_tokens)
    return overlap / len(left_tokens) >= 0.75


def _norm(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).split())


def _log(state: dict, step_id: str, message: str) -> None:
    append_log(state.get("run_id") or "", step_id, message)


def _logger(state: dict, step_id: str, prefix: str = ""):
    def record(message: str) -> None:
        text = f"{prefix}: {message}" if prefix else message
        _log(state, step_id, text)

    return record


def _judgement_line(title: str, overview: str, routing: str) -> str:
    if not (overview or "").strip():
        return f"Judgement for “{title}”: unanswered. No overview text was returned."
    if routing == "usage_card":
        return f"Judgement for “{title}”: true. The overview says this paper uses the dataset."
    return f"Judgement for “{title}”: false. The overview does not say this paper uses the dataset."


def _short(title: str) -> str:
    text = " ".join((title or "Untitled").split())
    return text if len(text) <= 72 else text[:69] + "…"


def _serp_key() -> str:
    key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Set SERPAPI_API_KEY in .env, then restart the server.")
    return key
