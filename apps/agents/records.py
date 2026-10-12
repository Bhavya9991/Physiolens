"""Shared step and evidence records for the agent graphs."""

from __future__ import annotations

from urllib.parse import urlparse

from apps.agents.control import checkpoint
from apps.backend.store import save_progress


def remember(state: dict, step: dict) -> list[dict]:
    """Append one visible step and persist it so the page can poll."""
    steps = [*(state.get("steps") or []), step]
    save_progress(state["run_id"], steps, {"summary": state.get("summary") or "", "groups": []})
    checkpoint(state.get("run_id"))
    return steps


def step(step_id: str, title: str, why: str, engine: str, query: str, items: list[dict]) -> dict:
    return {
        "id": step_id,
        "title": title,
        "why": why,
        "engine": engine,
        "query": query,
        "items": items,
    }


def paper(record: dict, label: str) -> dict:
    return {
        "title": record.get("title") or "",
        "link": record.get("link") or "",
        "detail": record.get("summary") or record.get("snippet") or "",
        "label": label,
        "access": "",
        "slug": "",
    }


def is_physionet(link: str) -> bool:
    host = urlparse(link or "").netloc.casefold()
    return host == "physionet.org" or host.endswith(".physionet.org")
