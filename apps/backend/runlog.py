"""One plain-text log for each agent run.

The file lives next to the run database. Deleting the run deletes the file.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LOG_DIR = DATA_DIR / "run-logs"


def append_log(run_id: str, step_id: str, message: str) -> None:
    """One finished action. step_id is the plan step this line belongs to."""
    path = _path(run_id)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H:%M:%S")
    step = "".join(character for character in (step_id or "run") if character.isalnum() or character in "-_") or "run"
    line = " ".join((message or "").split()).replace("\t", " ")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp}\t{step}\t{line}\n")


def read_log(run_id: str) -> str:
    path = _path(run_id)
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def delete_log(run_id: str) -> None:
    path = _path(run_id)
    if path is not None and path.is_file():
        path.unlink()


def delete_all_logs() -> None:
    if not LOG_DIR.is_dir():
        return
    for path in LOG_DIR.glob("*.log"):
        path.unlink()


def _path(run_id: str) -> Path | None:
    safe = "".join(character for character in (run_id or "") if character.isalnum() or character in "-_")
    if not safe:
        return None
    return LOG_DIR / f"{safe}.log"
