"""Run one project action on its LangGraph agent.

Each action is a fixed sequence. This module turns the final state into the
groups the page and the HTML report already show.
"""

from __future__ import annotations

from apps.agents.control import RunStopped, checkpoint
from apps.agents.published import build_published
from apps.agents.records import paper
from apps.agents.resources import build_resources
from apps.backend.catalog_view import project_by_slug
from apps.backend.runlog import append_log
from apps.backend.store import finish_run, get_run

GRAPHS = {
    "published": build_published(),
    "resources": build_resources(),
}


def execute(run_id: str) -> None:
    run = get_run(run_id)
    if run is None:
        return
    project = project_by_slug(run["slug"])
    if project is None:
        finish_run(run_id, status="failed", steps=[], result=_empty(), error="Project is no longer in the catalog.")
        return
    action = run["action_id"]
    graph = GRAPHS.get(action)
    if graph is None:
        finish_run(run_id, status="failed", steps=[], result=_empty(), error=f"Unknown action {action}.")
        return
    append_log(run_id, "run", f"Started {action} for {project.get('title') or run['slug']}.")
    try:
        final = graph.invoke({"run_id": run_id, "action": action, "project": project, "steps": []})
        checkpoint(run_id)
        result = {"summary": final.get("summary") or "", "groups": _groups(action, final)}
        if final.get("report"):
            result["report"] = final["report"]
        finish_run(run_id, status="completed", steps=final.get("steps") or [], result=result)
        append_log(run_id, "run", "Run completed.")
    except RunStopped:
        _stop(run_id)
    except Exception as exc:
        append_log(run_id, "run", f"Run failed: {exc}")
        current = get_run(run_id) or {}
        finish_run(
            run_id,
            status="failed",
            steps=current.get("steps") or [],
            result=_empty(),
            error=str(exc),
        )


def _stop(run_id: str) -> None:
    current = get_run(run_id) or {}
    finish_run(
        run_id,
        status="stopped",
        steps=current.get("steps") or [],
        result=current.get("result") or _empty(),
        error="Stopped before this run finished.",
    )
    append_log(run_id, "run", "Run stopped.")


def _groups(action: str, state: dict) -> list[dict]:
    if action == "resources":
        return [
            {"heading": "In this catalog", "items": [_resource_item(item) for item in state.get("peers") or []]},
            {"heading": "Outside PhysioNet", "items": [_resource_item(item) for item in state.get("outside") or []]},
            {"heading": "Related on this page", "items": [_resource_item(item) for item in state.get("family") or []]},
        ]
    if action == "published":
        return [
            {"heading": "Scholar records", "items": state.get("seed_items") or []},
            {"heading": "Top-cited candidate papers", "items": state.get("candidate_items") or []},
        ]
    return []


def _resource_item(item: dict) -> dict:
    if item.get("source_url") or item.get("slug"):
        return {
            "title": item.get("title") or "Untitled",
            "link": item.get("source_url") or item.get("link") or "",
            "detail": item.get("resource_type") or item.get("detail") or "",
            "label": "catalog",
            "access": item.get("access_policy") or item.get("access") or "",
            "slug": item.get("slug") or "",
        }
    record = paper(item, "web")
    record["access"] = ""
    return record


def _empty() -> dict:
    return {"summary": "", "groups": []}
