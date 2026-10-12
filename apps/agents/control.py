"""Cooperative stop for a run that is already in flight.

A paper fetch or model call that has started is allowed to finish. The next
paper, and the next graph step, sees the stop and leaves the run.
"""

from __future__ import annotations

from apps.backend.store import get_run


class RunStopped(Exception):
    """The user asked this run to stop."""


def stopping(run_id: str | None) -> bool:
    if not run_id:
        return False
    run = get_run(run_id)
    return bool(run and run.get("status") in {"stopping", "stopped"})


def checkpoint(run_id: str | None) -> None:
    if stopping(run_id):
        raise RunStopped()
