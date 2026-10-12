"""PhysioLens API.

Catalog routes read data/physionet_catalog.json. Agent routes write
data/runs.sqlite3. The browser UI lives in web/ and is served from /.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from apps.agents.run import execute
from apps.backend.catalog_view import action_allowed, list_projects, overview, project_detail
from apps.backend.paths import ENV_PATH, WEB_DIR
from apps.backend.report import render_report
from apps.backend.runlog import read_log
from apps.backend.scholar import search_scholar
from apps.backend.store import (
    TooManyRuns,
    create_run,
    delete_all_runs,
    delete_run,
    get_run,
    init_db,
    list_runs,
    request_stop,
)

load_dotenv(ENV_PATH)

app = FastAPI(title="PhysioLens")


@app.on_event("startup")
def startup() -> None:
    init_db()


class ScholarRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class RunRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    action_id: str = Field(min_length=1, max_length=40)
    hierarchy: str = ""
    node: str = ""


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/catalog")
def catalog_overview() -> dict:
    return overview()


@app.get("/api/projects")
def projects(
    hierarchy: str = "",
    node: str = "",
    q: str = "",
    access: str = "",
    resource: str = "",
    published_from: str = "",
    published_to: str = "",
    sort: str = "title_asc",
    page: int = 1,
    page_size: int = 25,
) -> dict:
    try:
        return list_projects(
            hierarchy=hierarchy,
            node=node,
            q=q,
            access=_csv(access),
            resource=_csv(resource),
            published_from=published_from,
            published_to=published_to,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown catalog group.") from exc


@app.get("/api/projects/{slug}")
def one_project(slug: str) -> dict:
    detail = project_detail(slug)
    if detail is None:
        raise HTTPException(status_code=404, detail="Project not in the catalog.")
    return detail


@app.get("/api/runs")
def runs() -> dict:
    return {"runs": list_runs()}


@app.delete("/api/runs")
def clear_runs() -> dict:
    return {"deleted": delete_all_runs()}


@app.get("/api/runs/{run_id}")
def one_run(run_id: str) -> dict:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    from apps.agents.published import apply_logged_reasons

    return apply_logged_reasons(run)


@app.delete("/api/runs/{run_id}")
def remove_run(run_id: str) -> dict:
    if not delete_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"deleted": run_id}


@app.get("/api/runs/{run_id}/log")
def run_log(run_id: str) -> Response:
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return Response(content=read_log(run_id), media_type="text/plain; charset=utf-8")


@app.get("/api/runs/{run_id}/report")
def run_report(run_id: str) -> Response:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    from apps.agents.published import apply_logged_reasons

    apply_logged_reasons(run)
    filename = f"physiolens-{run['slug']}-{run_id}.html"
    return Response(
        content=render_report(run),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/runs", status_code=202)
def start_run(body: RunRequest, background: BackgroundTasks) -> dict:
    detail = project_detail(body.slug)
    if detail is None:
        raise HTTPException(status_code=404, detail="Project not in the catalog.")
    if not action_allowed(detail, body.action_id):
        raise HTTPException(status_code=400, detail="That action is not available for this project.")
    action = next(item for item in detail["actions"] if item["id"] == body.action_id)
    try:
        run = create_run(
            slug=detail["slug"],
            project_title=detail["title"],
            action_id=action["id"],
            action_label=action["label"],
            path={"hierarchy": body.hierarchy, "node": body.node},
        )
    except TooManyRuns:
        raise HTTPException(
            status_code=409,
            detail="Two agent jobs are already running. Wait for one to finish, or stop one, before starting another.",
        ) from None
    background.add_task(execute, run["id"])
    return run


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str) -> dict:
    run = request_stop(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.post("/api/scholar")
def scholar_search(body: ScholarRequest) -> dict:
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Set SERPAPI_API_KEY in .env, then restart the server.")
    try:
        papers = search_scholar(body.query, api_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"query": body.query, "papers": papers}


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


app.mount("/static", StaticFiles(directory=WEB_DIR), name="web")
