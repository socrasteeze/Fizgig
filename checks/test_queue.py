"""The training queue (fizgig.web.queue): add, move and remove keep their order on disk; after a restart, a failed
run or a stopped one it holds (nothing launches by surprise); a finished run moves it on; a busy GPU makes it wait.

    python -m unittest discover -s checks -p "test_queue.py" -v
"""
import json
import os
import unittest
from unittest.mock import patch

import isolate
from fizgig.web import queue as webqueue
from fizgig.web import server


class QueueBase(unittest.TestCase):
    def setUp(self):
        self.folder = os.path.join(isolate.ROOT, "queue_data")
        os.makedirs(self.folder, exist_ok=True)
        self._reset()
        # no timer ever fires in a test: what was scheduled is recorded
        self.scheduled = []
        p = patch.object(webqueue, "schedule", lambda delay, starter: self.scheduled.append(delay))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._reset)

    def _reset(self):
        with webqueue._lock:
            webqueue._q.update(items=[], held=False, reason="", waiting="", timer=None, for_pause=False)
        try:
            os.remove(webqueue.QUEUE_FILE)
        except OSError:
            pass

    def add(self, lora):
        return webqueue.add("klein", {"LORA_NAME": lora}, self.folder, lora, os.path.join(isolate.ROOT, "out"))

    def on_disk(self):
        with open(webqueue.QUEUE_FILE, encoding="utf-8") as f:
            return [i["lora"] for i in json.load(f)]

    def shown(self):
        return [i["lora"] for i in webqueue.status()["items"]]


class Order(QueueBase):
    def test_add_move_remove(self):
        a, b, c = self.add("fake_a"), self.add("fake_b"), self.add("fake_c")
        self.assertEqual(self.on_disk(), ["fake_a", "fake_b", "fake_c"])
        webqueue.move(c["id"], -1)
        self.assertEqual(self.on_disk(), ["fake_a", "fake_c", "fake_b"])
        webqueue.move(a["id"], -1)                     # already first: stays
        webqueue.move(b["id"], 1)                      # already last: stays
        self.assertEqual(self.shown(), ["fake_a", "fake_c", "fake_b"])
        webqueue.remove(a["id"])
        self.assertEqual(self.on_disk(), ["fake_c", "fake_b"])

    def test_same_output_clashes(self):
        a = self.add("fake_a")
        self.assertEqual(webqueue.clashes(os.path.join(isolate.ROOT, "out"), "FAKE_A"), 1)
        self.assertIsNone(webqueue.clashes(os.path.join(isolate.ROOT, "out"), "fake_a", skip=a["id"]))


class Holds(QueueBase):
    def test_restart_holds(self):
        self.add("fake_a")
        with webqueue._lock:
            webqueue._q.update(items=[], held=False)          # the server stops
        webqueue.load()                                      # and starts again
        st = webqueue.status()
        self.assertEqual([i["lora"] for i in st["items"]], ["fake_a"])
        self.assertTrue(st["held"])

    def test_failed_or_stopped_run_holds(self):
        for result in ("failed", "stopped", "paused"):
            with self.subTest(result=result):
                self._reset()
                self.add("fake_a")
                webqueue.on_run_ended(result, "fake_run", lambda item: self.fail("nothing starts"))
                self.assertTrue(webqueue.status()["held"])
                self.assertEqual(self.scheduled, [])

    def test_finish_moves_on(self):
        self.add("fake_a")
        webqueue.on_run_ended("finished", "fake_run", lambda item: (True, ""))
        self.assertFalse(webqueue.status()["held"])
        self.assertEqual(self.scheduled, [10])

    def test_held_queue_starts_nothing(self):
        self.add("fake_a")
        webqueue.hold("fake hold")
        webqueue.start_next(lambda item: self.fail("nothing starts"))
        self.assertEqual(self.shown(), ["fake_a"])


class StartNext(QueueBase):
    def test_started_leaves_the_queue(self):
        self.add("fake_a"), self.add("fake_b")
        webqueue.start_next(lambda item: (True, ""))
        self.assertEqual(self.on_disk(), ["fake_b"])

    def test_busy_gpu_waits(self):
        self.add("fake_a")
        webqueue.start_next(lambda item: (False, "wait: a fake caption job"))
        st = webqueue.status()
        self.assertEqual((st["held"], st["waiting"], self.scheduled), (False, "a fake caption job", [webqueue.WAIT_S]))
        self.assertEqual(self.shown(), ["fake_a"])

    def test_refused_run_holds_at_the_head(self):
        self.add("fake_a"), self.add("fake_b")
        webqueue.start_next(lambda item: (False, "fake problem"))
        st = webqueue.status()
        self.assertTrue(st["held"])
        self.assertIn("fake problem", st["reason"])
        self.assertEqual(self.shown(), ["fake_a", "fake_b"])

    def test_missing_folder_holds(self):
        webqueue.add("klein", {}, os.path.join(isolate.ROOT, "fake_gone"), "fake_a", "")
        webqueue.start_next(lambda item: self.fail("nothing starts"))
        self.assertTrue(webqueue.status()["held"])


class Routes(QueueBase):
    def test_move_and_remove_routes(self):
        from webserve import Served
        a, b = self.add("fake_a"), self.add("fake_b")
        s = Served()
        try:
            self.assertEqual(s.json("POST", "/api/queue/move", {"id": b["id"], "delta": -1})[0], 200)
            self.assertEqual(self.shown(), ["fake_b", "fake_a"])
            self.assertEqual(s.json("POST", "/api/queue/remove", {"id": a["id"]})[0], 200)
            self.assertEqual(self.shown(), ["fake_b"])
            with server._lock:
                server._run["state"] = "paused"
            try:
                status, d = s.json("POST", "/api/queue/start", {})
            finally:
                with server._lock:
                    server._run["state"] = "idle"
            self.assertEqual(status, 400)                       # a paused run is resumed first
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
