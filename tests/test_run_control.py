"""Two running jobs, and a stop that the worker can see."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.agents.control import RunStopped, checkpoint
from apps.agents.records import remember, step
from apps.backend.store import TooManyRuns, create_run, finish_run, request_stop


def _run(label: str) -> dict:
    return create_run(
        slug="mitdb",
        project_title="MIT-BIH",
        action_id="published",
        action_label=label,
        path={},
    )


class RunControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "runs.sqlite3"
        self.patch = patch("apps.backend.store.DB_PATH", self.db)
        self.patch.start()
        from apps.backend import store

        store.init_db()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_a_third_running_job_is_refused(self):
        _run("one")
        _run("two")
        with self.assertRaises(TooManyRuns):
            _run("three")

    def test_a_job_that_is_stopping_still_occupies_a_slot(self):
        first = _run("one")
        _run("two")
        stopped = request_stop(first["id"])
        self.assertEqual(stopped["status"], "stopping")
        with self.assertRaises(TooManyRuns):
            _run("three")

    def test_stop_leaves_a_finished_run_alone(self):
        run = _run("one")
        finish_run(run["id"], status="completed", steps=[], result={}, error="")
        again = request_stop(run["id"])
        self.assertEqual(again["status"], "completed")

    def test_a_stopping_run_is_visible_at_the_next_step(self):
        run = _run("one")
        request_stop(run["id"])
        with self.assertRaises(RunStopped):
            remember(
                {"run_id": run["id"], "steps": []},
                step("page_citations", "Read", "Stopped after this step.", "physionet", "", []),
            )
        saved = request_stop(run["id"])
        self.assertEqual(saved["steps"][0]["id"], "page_citations")
        with self.assertRaises(RunStopped):
            checkpoint(run["id"])


if __name__ == "__main__":
    unittest.main()
