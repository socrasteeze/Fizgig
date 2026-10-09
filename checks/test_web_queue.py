"""Queue, auto-advance, desktop import, and job history.

Nothing here loads a model or touches CUDA.

    python -m unittest checks.test_web_queue -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "checks"))

from fastapi.testclient import TestClient

from fizgig.families.registry import get as get_family
from fizgig.gpu_lock import GpuLock
from fizgig.web import jobs, queue
from fizgig.web.app import app
import runner_guard

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _reset_queue() -> None:
    queue._SEEN.clear()
    queue._ACTIVE_SEEN.clear()
    queue._READY.clear()
    queue._HOLD.clear()
    queue._DEVICE.clear()


class WebQueueTests(unittest.TestCase):
    def setUp(self):
        _reset_queue()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "output"
        self.output2 = self.root / "output2"
        self.output.mkdir()
        self.output2.mkdir()
        self.images = self.root / "images"
        self.images.mkdir()
        (self.images / "a.png").write_bytes(_PNG)
        (self.images / "a.txt").write_text("a photo\n", encoding="utf-8")
        self.checkpoint = self.root / "checkpoint.safetensors"
        self.checkpoint.write_bytes(b"not a model")
        self._env = {
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_WEB_FAKE_TRAINER": os.environ.get("FIZGIG_WEB_FAKE_TRAINER"),
            "FIZGIG_FAKE_STEPS": os.environ.get("FIZGIG_FAKE_STEPS"),
            "FIZGIG_FAKE_SLEEP": os.environ.get("FIZGIG_FAKE_SLEEP"),
            "FIZGIG_WEB_DESKTOP_QUEUE": os.environ.get("FIZGIG_WEB_DESKTOP_QUEUE"),
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.root)
        os.environ["FIZGIG_WEB_FAKE_TRAINER"] = str(_REPO / "checks" / "fake_trainer.py")
        os.environ["FIZGIG_FAKE_STEPS"] = "2"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.01"
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        self._client.__exit__(None, None, None)
        runner_guard.end_runs(Path(os.environ["FIZGIG_WEB_JOBS"]))
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _reset_queue()
        self._tmp.cleanup()

    def _status_of(self, label):
        for job in jobs._each():
            if (job.get("values") or {}).get("LORA_NAME") == label:
                return job.get("status")
        return None

    def _body(self, output, name):
        return {
            "family": "sdxl",
            "values": {
                "LORA_OUTPUT_DIR": str(output),
                "LORA_NAME": name,
                "LEARNING_RATE": 1e-4,
                "NETWORK_DIM": 4,
                "NETWORK_ALPHA": 4,
                "MAX_TRAIN_EPOCHS": 2,
                "SAVE_EVERY_N_EPOCHS": 1,
                "SEED": 1,
                "image_folder": str(self.images),
            },
            "context": {
                "models": {"sdxl_checkpoint": str(self.checkpoint)},
                "image_folder": str(self.images),
                "samples": {"enabled": True, "prompts": ["a photo"], "width": "512", "height": "512"},
            },
        }

    def _wait(self, fn, timeout=15):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.05)
        self.fail(f"timed out; last={last!r}")

    def test_add_reorder_remove_and_persist(self):
        first = self.client.post("/api/queue", json=self._body(self.output, "One"))
        second = self.client.post("/api/queue", json=self._body(self.output2, "Two"))
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        ids = [second.json()["id"], first.json()["id"]]
        ordered = self.client.post("/api/queue/order", json={"ids": ids})
        self.assertEqual(ordered.status_code, 200, ordered.text)
        self.assertEqual([item["id"] for item in ordered.json()["items"]], ids)
        self.assertEqual(ordered.json()["items"][0]["context"]["samples"]["width"], "512")

        again = TestClient(app, base_url="http://127.0.0.1")
        with again as restarted:
            listed = restarted.get("/api/queue").json()["items"]
        self.assertEqual([item["id"] for item in listed], ids)
        on_disk = json.loads((self.root / "jobs" / "queue.json").read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in on_disk], ids)

        removed = self.client.delete(f"/api/queue/{ids[0]}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual([item["id"] for item in removed.json()["items"]], [ids[1]])

    def test_auto_advance(self):
        queued = self.client.post("/api/queue", json=self._body(self.output2, "Next"))
        self.assertEqual(queued.status_code, 200, queued.text)
        started = self.client.post("/api/jobs", json=self._body(self.output, "First"))
        self.assertEqual(started.status_code, 200, started.text)

        def advanced():
            rows = self.client.get("/api/jobs").json()["jobs"]
            names = []
            for row in rows:
                folder = self.root / "jobs" / row["id"] / "job.json"
                if folder.is_file():
                    names.append(json.loads(folder.read_text(encoding="utf-8"))["values"].get("LORA_NAME"))
            waiting = self.client.get("/api/queue").json()["items"]
            return len(rows) >= 2 and not waiting and "Next" in names

        self._wait(advanced)
        self.assertEqual(self.client.get("/api/queue").json()["items"], [])

    def test_import_is_read_only(self):
        label = get_family("sdxl").gui_label
        desktop = self.root / "training_queue.json"
        payload = [
            {
                "id": "desktop-1",
                "architecture": label,
                "image_folder": str(self.images),
                "preset": {"LORA_NAME": "Imported", "LORA_OUTPUT_DIR": str(self.output)},
                "samples": {"SAMPLE_ENABLED": True, "SAMPLE_WIDTH": "768", "SAMPLE_EVERY_N_EPOCHS": "2"},
                "model_options": {"NETWORK_DIM": "8"},
                "concept_folders": [],
            },
            {"architecture": "not a family", "preset": {}, "image_folder": "", "samples": {}},
        ]
        raw = json.dumps(payload, indent=2)
        desktop.write_text(raw, encoding="utf-8")
        os.environ["FIZGIG_WEB_DESKTOP_QUEUE"] = str(desktop)
        response = self.client.post("/api/queue/import")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["imported"], 1)
        self.assertEqual(body["skipped"], 1)
        item = body["items"][0]
        self.assertEqual(item["family"], "sdxl")
        self.assertEqual(item["values"]["LORA_NAME"], "Imported")
        self.assertEqual(item["values"]["NETWORK_DIM"], "8")
        self.assertEqual(item["context"]["samples"]["width"], "768")
        self.assertTrue(item["context"]["samples"]["enabled"])
        self.assertEqual(desktop.read_text(encoding="utf-8"), raw)

    def test_delete_keeps_outputs(self):
        started = self.client.post("/api/jobs", json=self._body(self.output, "Kept"))
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]

        def finished():
            body = self.client.get(f"/api/jobs/{job_id}").json()
            return body["status"] in {"done", "failed", "stopped"}

        self._wait(finished)
        past = self.client.get("/api/history").json()["jobs"]
        row = next(item for item in past if item["id"] == job_id)
        self.assertEqual(Path(row["output_dir"]).resolve(), self.output.resolve())
        self.assertIn(row["status"], {"done", "failed", "stopped"})
        self.assertIsInstance(row["duration"], int)
        marker = self.output / "keep-me.txt"
        marker.write_text("output", encoding="utf-8")
        sample = self.output / "sample"
        sample.mkdir(exist_ok=True)
        (sample / "preview.png").write_bytes(_PNG)
        removed = self.client.delete(f"/api/jobs/{job_id}")
        self.assertEqual(removed.status_code, 204, removed.text)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").status_code, 404)
        self.assertFalse((self.root / "jobs" / job_id).exists())
        self.assertEqual(marker.read_text(encoding="utf-8"), "output")
        self.assertTrue((sample / "preview.png").is_file())
        history = self.client.get("/api/history").json()["jobs"]
        self.assertFalse(any(item["id"] == job_id for item in history))

    def _record(self, job_id, status):
        folder = self.root / "jobs" / job_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "job.json").write_text(json.dumps({
            "id": job_id,
            "kind": "train",
            "family": "sdxl",
            "status": status,
            "device": 0,
            "pid": 0,
            "values": {"LORA_NAME": "Old"},
            "created": "2020-01-01T00:00:00Z",
            "output_dir": str(self.output),
        }), encoding="utf-8")

    def _stays(self, label, timeout=6):
        end = time.time() + timeout
        while time.time() < end:
            items = self.client.get("/api/queue").json()["items"]
            self.assertEqual([item["label"] for item in items], [label])
            names = [
                (job.get("values") or {}).get("LORA_NAME")
                for job in jobs._each()
            ]
            self.assertNotIn(label, names)
            time.sleep(0.2)

    def test_one_shot_ready_does_not_start_a_later_add(self):
        self._record("finished-once", "running")
        queue.observe(jobs.list_jobs())
        self._record("finished-once", "done")
        queue.observe(jobs.list_jobs())
        added = self.client.post("/api/queue", json=self._body(self.output2, "Later"))
        self.assertEqual(added.status_code, 200, added.text)
        self._stays("Later")

    def test_already_done_job_does_not_start_the_queue(self):
        _reset_queue()
        self._record("already-done", "done")
        added = self.client.post("/api/queue", json=self._body(self.output2, "Held"))
        self.assertEqual(added.status_code, 200, added.text)
        queue.observe(jobs.list_jobs())
        self._stays("Held")

    def test_failure_does_not_keep_the_queue_armed(self):
        self._record("then-failed", "running")
        queue.observe(jobs.list_jobs())
        bad = self._body(self.output2, "Bad")
        bad["values"]["image_folder"] = r"Z:\fizgig-outside-root\images"
        bad["context"]["image_folder"] = bad["values"]["image_folder"]
        queued = self.client.post("/api/queue", json=bad)
        self.assertEqual(queued.status_code, 200, queued.text)
        self._record("then-failed", "done")
        queue.observe(jobs.list_jobs())
        self.assertEqual(
            [item["label"] for item in self.client.get("/api/queue").json()["items"]],
            ["Bad"],
        )
        removed = self.client.delete(f"/api/queue/{queued.json()['id']}")
        self.assertEqual(removed.status_code, 200, removed.text)
        added = self.client.post("/api/queue", json=self._body(self.output2, "After"))
        self.assertEqual(added.status_code, 200, added.text)
        self._stays("After")

    def test_stale_ready_mark_cannot_launch(self):
        added = self.client.post("/api/queue", json=self._body(self.output2, "Stay"))
        self.assertEqual(added.status_code, 200, added.text)
        queue._READY.add("not-in-this-root")
        queue._DEVICE["not-in-this-root"] = 0
        queue._SEEN["not-in-this-root"] = "done"
        queue.observe(jobs.list_jobs())
        self.assertEqual(
            [item["label"] for item in self.client.get("/api/queue").json()["items"]],
            ["Stay"],
        )

    def test_busy_gpu_keeps_the_ready_mark(self):
        holder = GpuLock(0)
        self.assertTrue(holder.acquire())
        try:
            added = self.client.post("/api/queue", json=self._body(self.output2, "Retry"))
            self.assertEqual(added.status_code, 200, added.text)
            self._record("gpu-busy", "running")
            queue.observe(jobs.list_jobs())
            self._record("gpu-busy", "done")
            queue.observe(jobs.list_jobs())
            self.assertEqual(
                [item["label"] for item in self.client.get("/api/queue").json()["items"]],
                ["Retry"],
            )
        finally:
            holder.release()
        self._wait(lambda: self.client.get("/api/queue").json()["items"] == [], timeout=15)
        # Releasing the GPU let the ready mark launch Retry. Its runner must end here, not in tearDown.
        self._wait(lambda: self._status_of("Retry") in {"done", "failed", "stopped"}, timeout=15)
        self.assertEqual(self._status_of("Retry"), "done")

    def test_unexpected_launch_error_keeps_the_ready_mark(self):
        def record(job_id, status, device):
            folder = self.root / "jobs" / job_id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "job.json").write_text(json.dumps({
                "id": job_id,
                "kind": "train",
                "family": "sdxl",
                "status": status,
                "device": device,
                "pid": 0,
                "values": {"LORA_NAME": "Old"},
                "created": "2020-01-01T00:00:00Z",
                "output_dir": str(self.output),
            }), encoding="utf-8")

        for device, label, output in ((0, "Locked", self.output), (1, "Other", self.output2)):
            body = self._body(output, label)
            body["device"] = device
            added = self.client.post("/api/queue", json=body)
            self.assertEqual(added.status_code, 200, added.text)
        record("slow-disk", "running", 0)
        record("other-gpu", "running", 1)
        queue.observe(jobs.list_jobs())
        record("slow-disk", "done", 0)
        record("other-gpu", "done", 1)

        real_start = jobs.start

        def flaky(family, values, context, confirm, existing=None, device=0):
            if device == 0:
                raise OSError("dataset.toml is locked")
            return real_start(family, values, context, confirm, existing=existing, device=device)

        with patch("fizgig.web.jobs.start", side_effect=flaky):
            queue.observe(jobs.list_jobs())
        self.assertIn("slow-disk", queue._READY)
        self.assertEqual(
            [item["label"] for item in self.client.get("/api/queue").json()["items"]],
            ["Locked"],
        )
        queue.observe(jobs.list_jobs())
        self._wait(lambda: self.client.get("/api/queue").json()["items"] == [], timeout=15)

    def test_queue_write_retries_permission_error(self):
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1 and str(dst).endswith("queue.json"):
                raise PermissionError("busy")
            return real(src, dst)

        with patch("fizgig.web.queue.os.replace", side_effect=flaky):
            added = self.client.post("/api/queue", json=self._body(self.output, "Retried"))
        self.assertEqual(added.status_code, 200, added.text)
        self.assertGreaterEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
