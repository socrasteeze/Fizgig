"""Training Start (server._start): one run at a time, and a Start that doesn't launch leaves the run as it was.

    python -m unittest discover -s checks -p "test_start.py" -v
"""
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import isolate
from fizgig.web import server, tools


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
        # and this machine's free space doesn't decide: plenty, unless a test says otherwise
        room = SimpleNamespace(total=0, used=0, free=500 * 1024 ** 3)
        p = patch.object(server.shutil, "disk_usage", lambda path: room)
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


class Profiler(StartBase):
    def test_start_waits_for_the_profiler(self):
        planned = []
        with patch.object(tools, "holding_gpu", lambda: True), \
                patch.object(server, "_plan", lambda *a, **k: planned.append(1) or _fake_plan()):
            r = server._start("klein", {}, "")
            started, why = server._queue_starter({"family": "klein", "values": {}, "image_folder": ""})
        self.assertIn("Profiler", r.get("error", ""))
        self.assertEqual(planned, [])
        self.assertEqual(server._run["state"], "idle")
        self.assertFalse(started)
        self.assertTrue(why.startswith("wait:"), why)


class Warnings(StartBase):
    """The desktop's two questions before a run: little free disk, and a resume already at Max Train Epochs."""

    def _start(self, free_gb=500, resume="", epochs="10", confirm=()):
        usage = SimpleNamespace(total=0, used=0, free=int(free_gb * 1024 ** 3))
        _d, inputs, plan = _fake_plan()
        inputs["MAX_TRAIN_EPOCHS"] = epochs
        with patch.object(server.shutil, "disk_usage", lambda p: usage), \
                patch.object(server, "_plan", lambda *a, **k: (None, inputs, plan)):
            return server._start("klein", {}, "", resume=resume, confirm=confirm)

    def test_plenty_of_room(self):
        self.assertTrue(self._start().get("ok"))

    def test_low_disk_asks(self):
        r = self._start(free_gb=3)
        self.assertEqual([w["code"] for w in r["warnings"]], ["low_disk"])
        self.assertIn("3.0 GB", r["warnings"][0]["message"])
        self.assertEqual(server._run["state"], "idle")
        self.assertTrue(self._start(free_gb=3, confirm=["low_disk"]).get("ok"))

    def test_resume_at_max_epochs_asks(self):
        state = os.path.join(isolate.ROOT, "out", "fake_lora-000010-state")
        with server._lock:
            server._run.update(state="paused", resume=state)
        r = self._start(resume=state, epochs="10")
        self.assertEqual([w["code"] for w in r["warnings"]], ["resume_epochs"])
        self.assertEqual(server._run["state"], "paused")
        self.assertTrue(self._start(resume=state, epochs="10", confirm=["resume_epochs"]).get("ok"))

    def test_resume_with_epochs_left(self):
        state = os.path.join(isolate.ROOT, "out", "fake_lora-000004-state")
        self.assertTrue(self._start(resume=state, epochs="10").get("ok"))

    def test_queue_holds_with_the_warning(self):
        usage = SimpleNamespace(total=0, used=0, free=1024 ** 3)
        with patch.object(server.shutil, "disk_usage", lambda p: usage), \
                patch.object(server, "_plan", lambda *a, **k: _fake_plan()):
            started, why = server._queue_starter({"family": "klein", "values": {}, "image_folder": ""})
        self.assertFalse(started)
        self.assertIn("GB free", why)
        self.assertFalse(why.startswith("wait:"))


class WarningRoutes(unittest.TestCase):
    def test_start_route_passes_confirm(self):
        from webserve import Served
        s = Served()
        seen = []
        try:
            with patch.object(server, "_start", lambda *a, **k: seen.append(k.get("confirm")) or {"ok": True}):
                status, _d = s.json("POST", "/api/start", {"family": "klein", "values": {}, "image_folder": "",
                                                           "confirm": ["low_disk"]})
        finally:
            s.close()
        self.assertEqual(status, 200)
        self.assertEqual(seen, [["low_disk"]])


if __name__ == "__main__":
    unittest.main()
