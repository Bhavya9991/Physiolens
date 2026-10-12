"""Read the seed catalog. Browse screens and agents share this view.

The seed is data/physionet_catalog.json. Nothing here calls PhysioNet.
"""

from __future__ import annotations

import json
from functools import lru_cache

from apps.backend.paths import DATA_DIR

SEED_PATH = DATA_DIR / "physionet_catalog.json"

DOOR_SUBTITLES = {
    "subject": "The medical area: heart, brain, sleep, breathing, or movement. One project can sit in more than one.",
    "data_form": "The recording or file: waveforms, images, notes, tables, or audio. Chest and eye images are one step further in.",
}

# Shown on the tile, not as a second navigation instruction.
NODE_BLURBS = {
    "heart": "Electrocardiograms, blood pressure, and other cardiovascular recordings.",
    "brain": "EEG and other nervous-system recordings.",
    "sleep": "Polysomnography and other sleep studies.",
    "breathing": "Respiration, airflow, and other lung-related signals.",
    "movement": "Gait, activity, EMG, and other movement recordings.",
    "signals": "Waveforms sampled over time, such as ECG, EEG, and blood pressure.",
    "images": "Radiology, microscopy, and other pictures. Chest and eye are the narrower groups.",
    "chest": "Chest radiographs and other thoracic imaging.",
    "eye": "Retinal photographs and other eye images.",
    "text": "Clinical notes, reports, and other free text.",
    "records": "Stays, events, and other structured clinical tables.",
    "audio": "Speech, heart sounds, lung sounds, and other recordings you can hear.",
}


@lru_cache(maxsize=1)
def load_seed() -> dict:
    return json.loads(SEED_PATH.read_text())


def projects() -> list[dict]:
    return load_seed()["projects"]


def project_by_slug(slug: str) -> dict | None:
    for project in projects():
        if project["slug"] == slug:
            return project
    return None


def label_for(node_id: str) -> str:
    return _labels().get(node_id, node_id)


def overview() -> dict:
    seed = load_seed()
    rows = seed["projects"]
    doors = []
    for hierarchy in seed["hierarchies"]:
        field = hierarchy["field"]
        doors.append(
            {
                "id": hierarchy["id"],
                "label": hierarchy["label"],
                "subtitle": DOOR_SUBTITLES.get(hierarchy["id"], ""),
                "count": sum(1 for project in rows if project[field]),
                "nodes": [_node_payload(node, field, rows) for node in hierarchy["nodes"]],
            }
        )
    return {
        "project_count": seed["project_count"],
        "source_rows": seed["source_rows"],
        "no_subject": sum(1 for project in rows if not project["subject"]),
        "no_data_form": sum(1 for project in rows if not project["data_form"]),
        "neither": sum(1 for project in rows if not project["subject"] and not project["data_form"]),
        "doors": doors,
    }


def list_projects(
    *,
    hierarchy: str = "",
    node: str = "",
    q: str = "",
    access: list[str] | None = None,
    resource: list[str] | None = None,
    published_from: str = "",
    published_to: str = "",
    sort: str = "title_asc",
    page: int = 1,
    page_size: int = 25,
) -> dict:
    rows = projects()
    if hierarchy and node:
        field = _field_for(hierarchy)
        if node not in _labels():
            raise KeyError(node)
        rows = [project for project in rows if node in project[field]]
    access_policies = sorted({project["access_policy"] for project in rows if project["access_policy"]})
    resource_types = sorted({project["resource_type"] for project in rows if project["resource_type"]})
    if access:
        allowed = set(access)
        rows = [project for project in rows if project["access_policy"] in allowed]
    if resource:
        allowed = set(resource)
        rows = [project for project in rows if project["resource_type"] in allowed]
    if published_from:
        rows = [project for project in rows if project["publish_date"] >= published_from]
    if published_to:
        rows = [project for project in rows if project["publish_date"] <= published_to]
    if q.strip():
        needle = q.casefold()
        rows = [project for project in rows if needle in _search_blob(project)]
    rows = sorted(rows, key=lambda project: _sort_key(project, sort))
    if sort in {"title_desc", "newest", "largest"}:
        rows.reverse()
    total = len(rows)
    page_size = min(max(int(page_size or 25), 1), 100)
    page_count = max(1, (total + page_size - 1) // page_size) if total else 1
    page = min(max(int(page or 1), 1), page_count)
    start = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "access_policies": access_policies,
        "resource_types": resource_types,
        "projects": [_table_row(project) for project in rows[start : start + page_size]],
    }


def project_detail(slug: str) -> dict | None:
    project = project_by_slug(slug)
    if project is None:
        return None
    return {
        **project,
        "subject_labels": [label_for(node_id) for node_id in project["subject"]],
        "data_form_labels": [label_for(node_id) for node_id in project["data_form"]],
        "size_label": size_label(project.get("main_storage_size") or 0),
        "actions": actions_for(project),
    }


def actions_for(project: dict) -> list[dict]:
    """Every project offers the same two agents."""
    return [
        {
            "id": "published",
            "label": "Explore published research",
            "description": "See which published papers mention this dataset and how they use it.",
            "follow_ups": [],
        },
        {
            "id": "resources",
            "label": "Find similar resources",
            "description": "See other resources that cover the same subject or the same kind of data.",
            "follow_ups": [],
        },
    ]


def action_allowed(project: dict, action_id: str) -> bool:
    return any(action["id"] == action_id for action in actions_for(project))


def size_label(num_bytes: int) -> str:
    if not num_bytes:
        return "Size not listed"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _node_payload(node: dict, field: str, rows: list[dict]) -> dict:
    children = node.get("children") or []
    return {
        "id": node["id"],
        "label": node["label"],
        "blurb": NODE_BLURBS.get(node["id"], ""),
        "count": sum(1 for project in rows if node["id"] in project[field]),
        "has_children": bool(children),
        "children": [_node_payload(child, field, rows) for child in children],
    }


def _labels() -> dict[str, str]:
    labels: dict[str, str] = {}

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            labels[node["id"]] = node["label"]
            walk(node.get("children") or [])

    for hierarchy in load_seed()["hierarchies"]:
        walk(hierarchy["nodes"])
    return labels


def _field_for(hierarchy: str) -> str:
    for item in load_seed()["hierarchies"]:
        if item["id"] == hierarchy:
            return item["field"]
    raise KeyError(hierarchy)


def _search_blob(project: dict) -> str:
    topics = " ".join(project.get("topics") or [])
    return " ".join((project.get("title") or "", project.get("short_description") or "", topics)).casefold()


def _sort_key(project: dict, sort: str):
    if sort in {"newest", "oldest"}:
        return project.get("publish_date") or ""
    if sort in {"largest", "smallest"}:
        return project.get("main_storage_size") or 0
    return (project.get("title") or "").casefold()


def _table_row(project: dict) -> dict:
    description = (project.get("short_description") or "").strip()
    if len(description) > 180:
        description = description[:177].rstrip() + "..."
    return {
        "slug": project["slug"],
        "title": project["title"],
        "short_description": description,
        "access_policy": project["access_policy"],
        "publish_date": project["publish_date"],
        "main_storage_size": project.get("main_storage_size") or 0,
        "size_label": size_label(project.get("main_storage_size") or 0),
        "resource_type": project["resource_type"],
        "source_url": project["source_url"],
    }
