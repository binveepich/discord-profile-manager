"""Background-job shutdown and queue state regression tests."""

import threading
import time
import unittest

from revamped.core import ProfileManagerError
from revamped.product_api import JobManager


class JobManagerTests(unittest.TestCase):
    def test_shutdown_cancels_queued_jobs_and_signals_running_jobs(self):
        manager = JobManager(max_workers=1)
        started = threading.Event()
        release = threading.Event()
        mutations = []

        def running_worker(cancel_event, _progress):
            started.set()
            release.wait(timeout=5)
            if not cancel_event.is_set():
                mutations.append("running job continued")
            return {"finished": True}

        active_id = manager.start("active", running_worker)
        self.assertTrue(started.wait(timeout=2))
        queued_id = manager.start(
            "queued",
            lambda _cancel_event, _progress: mutations.append("queued job ran"),
        )
        shutdown_returned = threading.Event()
        shutdown_thread = threading.Thread(
            target=lambda: (manager.shutdown(), shutdown_returned.set())
        )
        shutdown_thread.start()

        try:
            self.assertFalse(shutdown_returned.wait(timeout=0.05))
            self.assertEqual(manager.get(queued_id)["status"], "cancelled")
        finally:
            release.set()
        self.assertTrue(shutdown_returned.wait(timeout=3))
        shutdown_thread.join(timeout=1)
        with self.assertRaisesRegex(ProfileManagerError, "shut down"):
            manager.start("after shutdown", lambda *_args: None)

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = manager.get(active_id)
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)

        self.assertEqual(state["status"], "cancelled")
        self.assertTrue(state["cancel_requested"])
        self.assertEqual(mutations, [])

    def test_terminal_job_history_is_bounded(self):
        manager = JobManager(max_workers=4)
        job_ids = [
            manager.start("short", lambda _cancel_event, _progress: None)
            for _ in range(manager.MAX_RETAINED_JOBS + 8)
        ]

        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with manager._lock:
                    pending = any(
                        job["status"] in {"queued", "running"}
                        for job in manager._jobs.values()
                    )
                if not pending:
                    break
                time.sleep(0.01)
            with manager._lock:
                self.assertFalse(any(
                    job["status"] in {"queued", "running"}
                    for job in manager._jobs.values()
                ))
                self.assertLessEqual(len(manager._jobs), manager.MAX_RETAINED_JOBS)
                self.assertNotIn(job_ids[0], manager._jobs)
                self.assertIn(job_ids[-1], manager._jobs)
        finally:
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
