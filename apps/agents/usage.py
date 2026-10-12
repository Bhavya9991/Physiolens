"""Classify candidate papers and write usage cards.

An AI Overview is a signal. The model turns that paragraph into a class.
A usage card is written only after the paper HTML supports actual use.
The model does not parse HTML. A parser hands it the abstract, data, and methods.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from apps.agents.llm import ask
from apps.backend.paper_html import _heading_kind, _paperish, fetch_article_html, parse_paper, select_bundle
from apps.backend.paper_pdf import fetch_pdf, pdf_sections
from apps.backend.scholar import google_overview

CLASSES = {
    "experimental_use",
    "secondary_analysis",
    "background_reference",
    "methodological_reference",
    "mention_only",
    "unclear",
}
USE_CLASSES = {"experimental_use", "secondary_analysis"}
USE_TAGS = {"training", "testing", "validation", "benchmarking", "retrospective_analysis"}
CLASS_LABEL = {
    "experimental_use": "Dataset used in experiments",
    "secondary_analysis": "Secondary analysis",
    "background_reference": "Background reference",
    "methodological_reference": "Methodological reference",
    "mention_only": "Mention only",
    "unclear": "Usage could not be established",
}


class PaperClass(BaseModel):
    index: int = Field(description="The paper number from the prompt.")
    usage_class: str = Field(description="experimental_use, secondary_analysis, background_reference, methodological_reference, mention_only, or unclear.")
    usage_tags: list[str] = Field(description="Roles such as training, testing, validation, benchmarking, retrospective_analysis. Empty when none apply.")
    confidence: str = Field(description="high, medium, or low.")
    evidence: str = Field(description="A short passage from the overview, or empty.")
    why: str = Field(description="One sentence on how the paper refers to the dataset.")


class ClassBatch(BaseModel):
    papers: list[PaperClass]


class PaperReading(BaseModel):
    uses_dataset: bool = Field(description="True only when the supplied sections show this dataset was used in the paper's own work.")
    how_used: str = Field(description="How the dataset was used, with no scores and no findings. Empty when it was not used.")
    dataset_role: list[str] = Field(description="Role tags such as training or benchmarking. Empty when it was not used.")
    research_tasks: list[str] = Field(description="The paper's own tasks, such as classification or question answering.")
    techniques: list[str] = Field(description="Named methods in the paper. Not signal types or recording settings.")
    why_open: str = Field(description="One sentence on what a reader learns by opening the paper. About the paper's own work.")


class UsageCard(BaseModel):
    actually_used: bool = Field(description="True only when the supplied sections show this dataset was used in the work.")
    how_used: str = Field(description="Two or three sentences on what the dataset contributed to the study. No metrics and no findings.")
    dataset_role: list[str] = Field(description="Short role tags such as training, testing, external validation, benchmarking, or exploratory analysis. Empty when the text does not say.")
    research_tasks: list[str] = Field(description="The problems the paper works on, such as classification or question answering. Not signal types or note types.")
    techniques: list[str] = Field(description="Named methods or model families the paper applies. Not signal types or recording settings.")
    why_explore: str = Field(description="One sentence telling a researcher what they can learn by opening this paper. Not a result and not a restatement of the abstract.")


class DatasetBrief(BaseModel):
    summary: str = Field(description="Three or four sentences on what the dataset contains and what research it supports. No papers and no citation counts.")


class Insights(BaseModel):
    research_tasks: str = Field(description="Two or three sentences on problems studied with the dataset.")
    methods_and_models: str = Field(description="Two or three sentences on approaches across the cards.")
    setups_and_findings: str = Field(description="Two or three sentences on splits, evaluation, and results stated in the cards.")


def overview_query(title: str, dataset: str) -> str:
    return (
        f'Does the paper "{title}" actually use {dataset} in its experiments or analyses, '
        'or does it cite it for another purpose? Answer just "yes" if it actually uses it, or else "NO".'
    )


def read_overview_answer(text: str, query: str = "") -> str:
    """The first yes or no in the answer, after the question itself is set aside."""
    body = text or ""
    folded = body.casefold()
    asked = (query or "").casefold()
    if asked and asked in folded:
        body = body[folded.find(asked) + len(query):]
    else:
        marker = folded.rfind("or else")
        if marker != -1:
            tail = re.search(r"or else\s+[\"']?no[\"']?[.!]?\s*(.*)$", body[marker:], re.I | re.S)
            body = tail.group(1) if tail else body[marker:]
    match = re.search(r"\b(yes|no)\b", body, re.I)
    return match.group(1).casefold() if match else ""


def answer_class(text: str, query: str = "") -> dict:
    """Yes goes to a usage card. Any other answer is a background or other citation."""
    if not (text or "").strip():
        return blank_class("No AI Overview was returned.")
    if read_overview_answer(text, query) == "yes":
        return {
            "usage_class": "experimental_use",
            "usage_tags": [],
            "confidence": "high",
            "evidence": " ".join(text.split())[:500],
            "why": "The overview answered yes, so this paper is read for a usage card.",
            "routing": "usage_card",
        }
    return {
        "usage_class": "background_reference",
        "usage_tags": [],
        "confidence": "high",
        "evidence": " ".join(text.split())[:500],
        "why": "This paper cites the dataset for background context or another purpose.",
        "routing": "report_only",
    }


def blank_class(why: str) -> dict:
    return {
        "usage_class": "unclear",
        "usage_tags": [],
        "confidence": "low",
        "evidence": "",
        "why": why,
        "routing": "report_only",
    }


def apply_class(raw: PaperClass) -> dict:
    """Weak or off-schema model output stays unclear and does not get a card."""
    usage_class = (raw.usage_class or "").strip()
    if usage_class not in CLASSES:
        usage_class = "unclear"
    confidence = (raw.confidence or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    tags = []
    for tag in raw.usage_tags or []:
        cleaned = " ".join(tag.split()).casefold().replace(" ", "_")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    used = usage_class in USE_CLASSES or bool(set(tags) & USE_TAGS)
    if confidence == "low":
        used = False
        if usage_class in USE_CLASSES:
            usage_class = "unclear"
    return {
        "usage_class": usage_class,
        "usage_tags": tags,
        "confidence": confidence,
        "evidence": " ".join((raw.evidence or "").split())[:500],
        "why": " ".join((raw.why or "").split())[:400] or CLASS_LABEL[usage_class],
        "routing": "usage_card" if used else "report_only",
    }


def classify_overviews(papers: list[dict], dataset: str) -> str:
    """Read yes or no from each overview. The model is not asked to classify."""
    yes = 0
    for paper in papers:
        query = overview_query(paper.get("title") or "", dataset)
        paper.update(answer_class(paper.get("overview") or "", query))
        if paper.get("routing") == "usage_card":
            yes += 1
    if not papers:
        return "There are no papers to check."
    if yes == 0 and all(not (paper.get("overview") or "").strip() for paper in papers):
        return "No overview text was returned, so every paper stays unclear."
    return f"Checked {len(papers)} overviews. {yes} judged true."


def paper_html_url(paper: dict) -> tuple[str, str]:
    """The first HTML link already on the Scholar row. Cache first, then an article URL."""
    found = html_candidates(paper)
    return found[0] if found else ("", "")


def html_candidates(paper: dict) -> list[tuple[str, str]]:
    """Cache, an HTML article link, then the paper page. PDF links are left out."""
    found: list[tuple[str, str]] = []

    def add(url: str, kind: str) -> None:
        link = (url or "").strip()
        if not link.startswith(("http://", "https://")):
            return
        if link.split("?", 1)[0].casefold().endswith(".pdf"):
            return
        if any(link == current for current, _kind in found):
            return
        found.append((link, kind))

    add(paper.get("cached_page_link") or "", "Scholar cache")
    add(paper.get("html_version") or "", "HTML article")
    add(paper.get("html_resource") or "", "HTML article")
    add(_arxiv_html(paper.get("html_version") or ""), "HTML article")
    add(_arxiv_html(paper.get("link") or ""), "HTML article")
    link = paper.get("link") or ""
    if not _arxiv_html(link):
        add(link, "paper page")
    return found


def load_paper_sections(paper: dict, api_key: str, record=None) -> tuple[list[dict], str, list[str]]:
    """HTML first. One PDF is read when that HTML has no usable paper text."""
    html, kind, notes = load_card_html(paper, api_key, record)
    html_sections = parse_paper(html) if html else []

    def say(message: str) -> None:
        notes.append(message)
        if record:
            record(message)

    if _rich(html_sections):
        return html_sections, kind, notes
    # A title page or an abstract landing page is not the paper. Read one PDF before keeping it.
    pdfs: list[dict] = []
    if not _headed(html_sections):
        pdfs, _pdf_kind = _read_pdfs(pdf_candidates(paper), say)
        if pdfs:
            return pdfs, "PDF", notes
    if _usable(html_sections):
        return html_sections, kind, notes
    if not pdfs:
        pdfs, _pdf_kind = _read_pdfs(pdf_candidates(paper), say)
        if pdfs:
            return pdfs, "PDF", notes
    return [], "", notes


def pdf_candidates(paper: dict) -> list[str]:
    found: list[str] = []

    def add(url: str) -> None:
        link = (url or "").strip()
        if link.startswith(("http://", "https://")) and link not in found:
            found.append(link)

    for url in paper.get("pdf_links") or []:
        add(url)
    link = paper.get("link") or ""
    if link.split("?", 1)[0].casefold().endswith(".pdf"):
        add(link)
    add(_arxiv_pdf(link))
    add(_arxiv_pdf(paper.get("html_version") or ""))
    add(_anthology_pdf(link))
    add(_anthology_pdf(paper.get("html_version") or ""))
    return found


def _read_pdfs(urls: list[str], say) -> tuple[list[dict], str]:
    best: list[dict] = []
    for url in urls:
        host = urlparse(url).netloc or "the host"
        say(f"Waiting for the PDF at {host}.")
        data, note = fetch_pdf(url)
        say(note)
        if not data:
            continue
        sections = pdf_sections(data)
        if _rich(sections) or (sections and not best):
            best = sections
        if _rich(sections):
            break
    return best, "PDF"


def _headed(sections: list[dict]) -> bool:
    """True when a real paper heading is present, not only the page title."""
    kinds = {_heading_kind(section.get("heading") or "") for section in sections}
    return bool(kinds & {"abstract", "intro", "method", "data", "setup"})


def _rich(sections: list[dict]) -> bool:
    kinds = {_heading_kind(section.get("heading") or "") for section in sections}
    return bool(kinds & {"method", "data", "setup"})


def _usable(sections: list[dict]) -> bool:
    if _rich(sections):
        return True
    text = " ".join(section.get("text") or "" for section in sections)
    if _paperish(text):
        return True
    kinds = {_heading_kind(section.get("heading") or "") for section in sections}
    return len(text) >= 400 and bool(kinds & {"abstract", "intro", "method", "data", "setup"})


def _anthology_pdf(url: str) -> str:
    match = re.search(r"aclanthology\.org/([A-Za-z0-9._-]+?)(?:\.pdf)?/?$", url or "", re.I)
    if not match:
        return ""
    return f"https://aclanthology.org/{match.group(1)}.pdf"


def _arxiv_html(url: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?", url or "", re.I)
    if not match:
        return ""
    return f"https://arxiv.org/html/{match.group(1)}"


def _arxiv_pdf(url: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?", url or "", re.I)
    if not match:
        return ""
    return f"https://arxiv.org/pdf/{match.group(1)}.pdf"


def read_paper(paper: dict, dataset: str, sections: list[dict]) -> dict | None:
    """One reading of the extracted sections. A card when the dataset was used, otherwise a reason to open the paper."""
    bundle = select_bundle(sections)
    if len(bundle) < 250:
        paper["card_note"] = "The extracted text had no usable sections."
        return None
    try:
        reading = ask(
            PaperReading,
            "uses_dataset is true only when this dataset is used in the paper's own experiment, benchmark, training, or analysis. "
            "A citation or a related-work mention is not use. "
            "When it is true, how_used and dataset_role describe that use, and why_open says what a reader learns about that use. "
            "When it is false, leave how_used and dataset_role empty. why_open then describes the paper's own work, not this dataset. "
            "research_tasks and techniques name the paper's problem and methods either way. "
            "Do not report a score or a finding. Do not use a signal type or a recording setting as a task or a technique. "
            f"The dataset name is {dataset}.",
            f"Paper: {paper.get('title') or 'Untitled'}\n\n{bundle}",
            timeout=60,
        )
    except RuntimeError as exc:
        paper["card_note"] = str(exc)[:220]
        return None
    why = _clean(reading.why_open, 320)
    tasks = _tags(reading.research_tasks)
    techniques = _tags(reading.techniques)
    if reading.uses_dataset:
        return {
            "card": {
                "how_used": _clean(reading.how_used, 700),
                "dataset_role": _tags(reading.dataset_role),
                "research_tasks": tasks,
                "techniques": techniques,
                "why_explore": why,
            },
            "explore": None,
        }
    if not why:
        paper["card_note"] = "The reading did not say what the paper is about."
        return None
    return {"card": None, "explore": {"why_open": why, "research_tasks": tasks, "techniques": techniques}}


def write_card(paper: dict, dataset: str, source) -> dict | None:
    """None when the text does not show use. The caller then keeps the paper without a card."""
    sections = source if isinstance(source, list) else parse_paper(source or "")
    bundle = select_bundle(sections)
    if len(bundle) < 250:
        paper["card_note"] = "The page had no usable sections."
        return None
    try:
        card = ask(
            UsageCard,
            "Read only the supplied sections. actually_used is true only when this dataset is used in the paper's own experiment, "
            "benchmark, training run, or analysis. A citation or a related-work mention is not use. "
            "how_used says what the dataset contributed. It does not report a score, a finding, or a contribution claim. "
            "dataset_role tags name the role, such as training, testing, external validation, benchmarking, or exploratory analysis. "
            "research_tasks name the problem, such as classification, forecasting, segmentation, retrieval, or question answering. "
            "techniques name the methods, such as a transformer, contrastive learning, or retrieval-augmented generation, when the text names them. "
            "Do not use a signal, a note type, an image type, or a recording setting as a task or a technique. "
            "why_explore is one practical reason to open the paper, such as how the dataset was used for external validation. "
            "Leave a tag list empty when the sections do not support it. "
            f"The dataset name is {dataset}.",
            f"Paper: {paper.get('title') or 'Untitled'}\n\n{bundle}",
            timeout=60,
        )
    except RuntimeError as exc:
        paper["card_note"] = str(exc)[:220]
        return None
    if not card.actually_used:
        return None
    return {
        "how_used": _clean(card.how_used, 700),
        "dataset_role": _tags(card.dataset_role),
        "research_tasks": _tags(card.research_tasks),
        "techniques": _tags(card.techniques),
        "why_explore": _clean(card.why_explore, 320),
    }


def write_dataset_brief(name: str, description: str) -> str:
    """What the dataset is, from the PhysioNet page, when no citing papers were found."""
    text = " ".join((description or "").split())
    if not text:
        return f"{name} is listed on PhysioNet. The project page did not include a description."
    try:
        brief = ask(
            DatasetBrief,
            "Use only the supplied description. Say what the dataset contains and what kind of research it supports. "
            "Do not mention a paper, a citation count, or a result.",
            f"Dataset: {name}\n\n{text[:3500]}",
        )
    except RuntimeError:
        return text[:700]
    return _clean(brief.summary, 900) or text[:700]


def write_insights(dataset: str, cards: list[dict]) -> dict:
    if not cards:
        return {
            "research_tasks": "No usage card was verified, so there is no cross-paper summary.",
            "methods_and_models": "",
            "setups_and_findings": "",
        }
    lines = []
    for card in cards:
        lines.append(
            "\n".join(
                [
                    card.get("title") or "Untitled",
                    card.get("research_objective") or "",
                    card.get("dataset_role") or "",
                    card.get("methods_and_models") or "",
                    card.get("evaluation_and_findings") or "",
                ]
            )
        )
    try:
        insights = ask(
            Insights,
            "Summarize only what these usage cards state about the dataset. Do not add a paper or a result that is not written here.",
            f"Dataset: {dataset}\n\n" + "\n\n".join(lines)[:8000],
        )
    except RuntimeError:
        return {
            "research_tasks": "The usage cards were written, and the cross-paper summary could not be generated.",
            "methods_and_models": "",
            "setups_and_findings": "",
        }
    return {
        "research_tasks": _clean(insights.research_tasks),
        "methods_and_models": _clean(insights.methods_and_models),
        "setups_and_findings": _clean(insights.setups_and_findings),
    }


def fetch_overview(title: str, dataset: str, api_key: str) -> str:
    found = google_overview(overview_query(title, dataset), api_key)
    return (found.get("text") or "").strip()


def load_card_html(paper: dict, api_key: str, record=None) -> tuple[str, str, list[str]]:
    """Try each HTML link. A blocked Scholar cache does not hide the paper page.

    record, when given, hears each wait and each result as it happens.
    """
    notes: list[str] = []

    def say(message: str) -> None:
        notes.append(message)
        if record:
            record(message)

    def one(url: str, kind: str, prefix: str = "") -> str:
        host = urlparse(url).netloc or "the host"
        label = f"{prefix}{kind}".strip()
        say(f"Waiting for {label} at {host}.")
        html, note = fetch_article_html(url)
        say(f"{label}: {note}")
        return html

    for url, kind in html_candidates(paper):
        html = one(url, kind)
        if html:
            return html, kind, notes
    if not notes:
        say("The Scholar row had no cache link, HTML link, or paper page.")
    return "", "", notes


def _clean(value: str, limit: int = 700) -> str:
    return " ".join((value or "").split())[:limit]


def _tags(values: list[str], limit: int = 6) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        text = " ".join(str(raw).split())
        key = text.casefold()
        if not text or len(text) > 48 or key in seen:
            continue
        seen.add(key)
        found.append(text)
        if len(found) >= limit:
            break
    return found
