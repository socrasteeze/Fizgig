"""Training Start (server._start): one run at a time, and a Start that doesn't launch leaves the run as it was.

    python -m unittest discover -s checks -p "test_start.py" -v
"""
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import isolate
from fizgig.web import server


def _fake_plan(problems=(), out_dir=None):
    out_dir = out_dir or os.path.join(isolate.ROOT, "start_out")
    plan = SimpleNamespace(problems=list(problems), dirs=[out_dir], files=[], console=[],
                           stages=[SimpleNamespace(name="Training", cmd=["fake"])])
    return None, {"LORA_OUTPUT_DIR": out_dir, "LORA_NAME": "fake_lora"}, plan


class StartBase(unittest.TestCase):
    def setUp(self):
        with server._lock:
            server._run.update(proc=None, state="idle", lora="", resume="", resume_mode="")
        # no stage ever runs: the test only sees what Start decides
        p = patch.object(server, "_run_stages", lambda stages, out_dir: None)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        with server._lock:
            server._run.update(proc=None, state="idle", lora="", resume="", resume_mode="")


class DoubleStart(StartBase):
    def test_second_start_refused_while_first_plans(self):
        planning, release = threading.Event(), threading.Event()

        def slow_plan(*a, **k):
            planning.set()
            release.wait(10)
            return _fake_plan(problems=["fake problem"])

        out = {}
        with patch.object(server, "_plan", slow_plan):
            t = threading.Thread(target=lambda: out.setdefault("first", server._start("klein", {}, "")))
            t.start()
            self.assertTrue(planning.wait(10))
            second = server._start("klein", {}, "")
            release.set()
            t.join(10)
        self.assertIn("already going", second.get("error", ""))
        self.assertEqual(out["first"], {"problems": ["fake problem"]})
        self.assertEqual(server._run["state"], "idle")

    def test_problems_keep_a_paused_run(self):
        with server._lock:
            server._run.update(state="paused", resume="fake-state-dir")
        with patch.object(server, "_plan", lambda *a, **k: _fake_plan(problems=["fake problem"])):
            r = server._start("klein", {}, "", resume="fake-state-dir")
        self.assertEqual(r, {"problems": ["fake problem"]})
        self.assertEqual(server._run["state"], "paused")

    def test_plan_error_gives_the_claim_back(self):
        def broken(*a, **k):
            raise ValueError("Unknown family: fake")
        with patch.object(server, "_plan", broken):
            with self.assertRaises(ValueError):
                server._start("fake", {}, "")
        self.assertEqual(server._run["state"], "idle")
        with patch.object(server, "_plan", lambda *a, **k: _fake_plan()):
            self.assertTrue(server._start("klein", {}, "").get("ok"))
        self.assertEqual(server._run["state"], "starting")

    def test_captions_busy_gives_the_claim_back(self):
        with patch.object(server.captions, "status", lambda: {"state": "running"}):
            r = server._start("klein", {}, "")
        self.assertIn("Captions are being made", r["error"])
        self.assertEqual(server._run["state"], "idle")


if __name__ == "__main__":
    unittest.main()
