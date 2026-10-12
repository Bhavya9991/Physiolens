"""Two overlapping browse trees for the PhysioNet catalog.

A project can sit in more than one place. The trees are how a person starts
looking. Access, date, size, and PhysioNet's own listing kind only narrow a
list that is already open. Topics stay free-text tags.

PhysioNet does not publish these groups. They are inferred from the slug,
title, and topics.
"""

from __future__ import annotations

import re

PUBLISHED_URL = "https://physionet.org/api/v1/projects/published/"

# Two doors. Neither one is a partition of the other.
HIERARCHIES = [
    {
        "id": "subject",
        "label": "What it is about",
        "field": "subject",
        "nodes": [
            {"id": "heart", "label": "Heart and circulation"},
            {"id": "brain", "label": "Brain and nerve"},
            {"id": "sleep", "label": "Sleep"},
            {"id": "breathing", "label": "Breathing"},
            {"id": "movement", "label": "Movement and activity"},
        ],
    },
    {
        "id": "data_form",
        "label": "What the data is",
        "field": "data_form",
        "nodes": [
            {"id": "signals", "label": "Signals and waveforms"},
            {
                "id": "images",
                "label": "Images",
                "children": [
                    {"id": "chest", "label": "Chest imaging"},
                    {"id": "eye", "label": "Eye imaging"},
                ],
            },
            {"id": "text", "label": "Clinical text"},
            {"id": "records", "label": "Structured clinical records"},
            {"id": "audio", "label": "Audio"},
        ],
    },
]

# Closed fields used to narrow a list. Not browse trees.
FILTERS = [
    {"field": "access_policy", "label": "Who can use it"},
    {"field": "publish_date", "label": "When it was published"},
    {"field": "main_storage_size", "label": "How big it is"},
    {"field": "resource_type", "label": "PhysioNet listing kind"},
]

_SUBJECTS = (
    ("heart", re.compile(
        r"ecg|ekg|electrocardiogra|arrhythmia|atrial fibrillation|\bppg\b|"
        r"blood pressure|heart rate|holter|\bqrs\b|rr interval|cardiovascular|"
        r"phonocardiogra|heart sound|\bcardiac\b|heart failure",
        re.I,
    )),
    ("brain", re.compile(
        r"\beeg\b|electroencephalogra|seizure|\becog\b|neuroelectric|"
        r"brain-computer|parkinson",
        re.I,
    )),
    ("sleep", re.compile(r"\bsleep\b|polysomnogra|\bapnea\b", re.I)),
    ("breathing", re.compile(r"respiration|respiratory|\bapnea\b|\bcpap\b|lung sound", re.I)),
    ("movement", re.compile(
        r"\bgait\b|acceleromet|\bemg\b|electromyogra|kinematic|motion capture|"
        r"movements?|wearables?|body sway|posturograph",
        re.I,
    )),
)

_DATA_FORMS = (
    ("signals", re.compile(
        r"ecg|ekg|electrocardiogra|eeg|electroencephalogra|electroretinogra|"
        r"ppg|photoplethysmogra|emg|electromyogra|eog|electrooculogra|"
        r"ehg|electrohysterogra|electrodermal|neuroelectric|holter|\bwfdb\b|"
        r"waveform|phonocardiogra|heart sound|heart rate|rr interval|"
        r"blood pressure|polysomnogra|\bapnea\b|respiration|respiratory|\bcpap\b|"
        r"acceleromet|\bgait\b|pulse oximet|oxygen saturation|oximetry|"
        r"ballistocardiogra|seismocardiogra|plethysmogra|magnetocardiogra|"
        r"magnetomyogra|fnirs|brain-computer|intracranial pressure|"
        r"kinematic|motion capture|wearables?|movements?|body sway|posturograph|"
        r"\bpulse\b|heart failure|sudden cardiac|entropy|lyapunov|poincare|"
        r"multifractal|fluctuation",
        re.I,
    )),
    ("images", re.compile(
        r"x-?rays?|\bcxr\b|radiographs?|\bmri\b|computed tomography|"
        r"\bultrasound\b|fundus|retinal|ophthalm|mammogra|histopath|"
        r"dermoscopy|thermography|thermal imag|endoscop|laparoscop|"
        r"\bmr images?\b|scintigraph|\bspect\b|bounding box|calcium imaging|"
        r"\bimagery\b|\bsatellite\b",
        re.I,
    )),
    ("text", re.compile(
        r"clinical notes?|discharge summar|natural language|\bnlp\b|"
        r"named entit|question answering|free-?text|clinical text|"
        r"medical text|radiology reports?|\bbert\b|entity linking|"
        r"language model|patient notes?",
        re.I,
    )),
    ("records", re.compile(
        r"electronic health records?|\behrs?\b|\behr\b|\bemr\b|icd-?\d+|"
        r"lab results?|\bomop\b|claims data|diagnosis codes?|clinical database|"
        r"clinical data",
        re.I,
    )),
    ("audio", re.compile(r"\bvoice\b|\bspeech\b|\baudio\b|lung sound", re.I)),
)

_IMAGE_CHILDREN = (
    ("chest", re.compile(r"cxr|chest x-?ray|chest radiograph", re.I)),
    ("eye", re.compile(r"fundus|retinal|ophthalm", re.I)),
)

_RECORD_FALLBACK = re.compile(
    r"mimic|eicu|\bicu\b|critical care|intensive care|electronic health",
    re.I,
)


def _blob(project: dict, *, with_description: bool) -> str:
    parts = [
        project.get("slug") or "",
        project.get("title") or "",
        " ".join(project.get("topics") or []),
    ]
    if with_description:
        parts.append(project.get("short_description") or "")
    return " ".join(parts)


def _matching(project: dict, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> list[str]:
    primary = _blob(project, with_description=False)
    found = [name for name, pattern in patterns if pattern.search(primary)]
    if found:
        return found
    description = _blob(project, with_description=True)
    return [name for name, pattern in patterns if pattern.search(description)]


def browse_labels(project: dict) -> dict[str, list[str]]:
    """Labels for both trees. Each list can hold more than one id."""
    subject = _matching(project, _SUBJECTS)
    data_form = _matching(project, _DATA_FORMS)
    primary = _blob(project, with_description=False)
    description = _blob(project, with_description=True)
    if "records" not in data_form and (
        _RECORD_FALLBACK.search(primary) or _RECORD_FALLBACK.search(description)
    ):
        if not any(name in data_form for name in ("signals", "images", "audio")):
            data_form.append("records")
    title = project.get("title") or ""
    if re.search(r"de-?identif", title, re.I) and "text" not in data_form:
        data_form.append("text")
    if "images" in data_form:
        for name, pattern in _IMAGE_CHILDREN:
            if pattern.search(description) and name not in data_form:
                data_form.append(name)
    return {"subject": subject, "data_form": data_form}


def seed_project(project: dict) -> dict:
    labels = browse_labels(project)
    return {
        "slug": project.get("slug") or "",
        "version": project.get("version") or "",
        "title": project.get("title") or "",
        "short_description": project.get("short_description") or "",
        "resource_type": project.get("resource_type") or "",
        "access_policy": project.get("access_policy") or "",
        "topics": project.get("topics") or [],
        "publish_date": project.get("publish_date") or "",
        "core_doi": project.get("core_doi"),
        "version_doi": project.get("version_doi"),
        "source_url": project.get("source_url") or "",
        "main_storage_size": project.get("main_storage_size") or 0,
        "subject": labels["subject"],
        "data_form": labels["data_form"],
    }


def build_seed(projects: list[dict], *, source_rows: int | None = None) -> dict:
    """Keep the latest version of each project and attach both browse trees."""
    if projects and "is_latest_version" in projects[0]:
        chosen = [project for project in projects if project.get("is_latest_version")]
        rows = len(projects)
    else:
        chosen = list(projects)
        rows = source_rows if source_rows is not None else len(projects)
    records = [seed_project(project) for project in chosen]
    records.sort(key=lambda project: project["title"].lower())
    return {
        "source": PUBLISHED_URL,
        "listing": "latest version of each published project",
        "source_rows": source_rows if source_rows is not None else rows,
        "project_count": len(records),
        "hierarchies": HIERARCHIES,
        "filters": FILTERS,
        "tags": {"field": "topics", "label": "Topics", "use": "search"},
        "projects": records,
    }


def _walk(nodes: list[dict], depth: int = 0):
    for node in nodes:
        yield depth, node
        yield from _walk(node.get("children") or [], depth + 1)


def tree_counts(seed: dict) -> list[tuple[str, int]]:
    """One block per hierarchy. Counts overlap, so they do not sum to the catalog size."""
    projects = seed["projects"]
    lines: list[tuple[str, int]] = []
    for hierarchy in seed["hierarchies"]:
        field = hierarchy["field"]
        matched = sum(1 for project in projects if project[field])
        lines.append((hierarchy["label"], matched))
        for depth, node in _walk(hierarchy["nodes"]):
            count = sum(1 for project in projects if node["id"] in project[field])
            lines.append((f"{'  ' * (depth + 1)}{node['label']}", count))
        empty = sum(1 for project in projects if not project[field])
        lines.append((f"  No match in this tree", empty))
    return lines
