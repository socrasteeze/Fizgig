"""Job supervisor, GPU lock, and the phase 1 routes.

A stand-in trainer prints progress and writes one sample. Nothing here loads a model
or touches CUDA.

    python -m unittest checks.test_web_jobs -v
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.gpu_lock import GpuLock, held
from fizgig.web import jobs
from fizgig.web.app import app
from fizgig.web.procs import creationflags

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
_EDIT = "Edit LoRA is on: set the Originals folder (Training tab, Training Parameters)"


class WebJobTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
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
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_WEB_FAKE_TRAINER"] = str(_REPO / "checks" / "fake_trainer.py")
        os.environ["FIZGIG_FAKE_STEPS"] = "3"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.02"
        self._holder = None
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        try:
            for job in jobs.list_jobs():
                if job["status"] in {"queued", "running"}:
                    self.client.post(f"/api/jobs/{job['id']}/stop")
        except Exception:
            pass
        if self._holder is not None:
            self._holder.kill()
            try:
                self._holder.wait(timeout=5)
            except Exception:
                pass
        self._client.__exit__(None, None, None)
        deadline = time.time() + 5
        while time.time() < deadline:
            if not any(self._job_runner_alive(job) for job in jobs._each()):
                break
            time.sleep(0.05)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _job_runner_alive(self, job):
        pid = int(job.get("pid") or 0)
        created = job.get("pid_create_time")
        if created is None:
            return jobs.pid_alive(pid)
        return jobs.pid_alive(pid, created)

    def wait_for(self, fn, timeout=12):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.05)
        self.fail(f"timed out; last={last!r}")

    def _payload(self, **values):
        body = {
            "LORA_OUTPUT_DIR": str(self.output),
            "LORA_NAME": "WebRun",
            "LEARNING_RATE": 1e-4,
            "NETWORK_DIM": 4,
            "NETWORK_ALPHA": 4,
            "MAX_TRAIN_EPOCHS": 4,
            "SAVE_EVERY_N_EPOCHS": 1,
            "SEED": 1,
        }
        body.update(values)
        return {
            "family": "sdxl",
            "values": body,
            "context": {
                "models": {"sdxl_checkpoint": str(self.checkpoint)},
                "image_folder": str(self.images),
                "DATASET_CONFIG": str(self.output / "dataset.toml"),
            },
        }

    def _create(self, **values):
        response = self.client.post("/api/jobs", json=self._payload(**values))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("runpod_api_key", response.text)
        return response.json()

    def _job_file(self, job_id):
        return json.loads((self.root / "jobs" / job_id / "job.json").read_text(encoding="utf-8"))

    def test_create_run_done_log_and_progress(self):
        created = self._create()
        job_id = created["id"]
        self.assertEqual(created["status"], "queued")

        def progressed():
            body = self.client.get(f"/api/jobs/{job_id}").json()
            if body["status"] == "failed":
                log = (self.root / "jobs" / job_id / "log.txt").read_text(encoding="utf-8", errors="replace")
                self.fail(log)
            if body["step"] >= 1 and body["loss"] == 0.42:
                return body
            return None

        body = self.wait_for(progressed)
        self.assertGreaterEqual(body["total"], body["step"])
        self.assertEqual(body["stage"], "Training")

        part = self.client.get(f"/api/jobs/{job_id}/log", params={"offset": 0}).json()
        self.assertEqual(part["offset"], 0)
        self.assertGreater(part["next"], 0)
        self.assertIn("avr_loss=0.42", part["text"])
        later = self.client.get(f"/api/jobs/{job_id}/log", params={"offset": part["next"]}).json()
        whole = self.client.get(f"/api/jobs/{job_id}/log", params={"offset": 0}).json()
        self.assertTrue(whole["text"].startswith(part["text"]))
        self.assertEqual(later["offset"], part["next"])
        self.assertIn(later["text"], whole["text"])

        def finished():
            body = self.client.get(f"/api/jobs/{job_id}").json()
            if body["status"] in {"done", "failed", "stopped"}:
                return body
            return None

        done = self.wait_for(finished)
        if done["status"] != "done":
            log = (self.root / "jobs" / job_id / "log.txt").read_text(encoding="utf-8", errors="replace")
            self.fail(f"{done}\n{log}")
        listed = self.client.get(f"/api/jobs/{job_id}/samples").json()
        self.assertEqual(listed["samples"][0]["name"], "sample_0001.png")
        image = self.client.get(listed["samples"][0]["url"])
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.content.startswith(b"\x89PNG"))
        self.assertNotIn("runpod_api_key", image.content.decode("latin1"))

    def test_pause_resume_and_stop(self):
        os.environ["FIZGIG_FAKE_STEPS"] = "40"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.1"
        created = self._create()
        job_id = created["id"]
        running = self.wait_for(lambda: (body := self.client.get(f"/api/jobs/{job_id}").json())["status"] == "running" and body["pid"] and body)
        self.assertTrue(jobs.pid_alive(running["pid"]))

        paused = self.client.post(f"/api/jobs/{job_id}/pause")
        self.assertEqual(paused.status_code, 200, paused.text)
        body = self.wait_for(lambda: (item := self.client.get(f"/api/jobs/{job_id}").json())["status"] == "paused" and item)
        self.assertEqual(body["status"], "paused")
        sidecar = json.loads((self.output / ".fizgig_paused.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["mode"], "state")
        self.assertEqual(sidecar["output_name"], "WebRun")
        self.assertTrue(sidecar["state_path"].endswith("WebRun-000001-state"))
        self.assertEqual(set(sidecar), {
            "mode", "state_path", "output_name", "dataset_config",
            "network_dim", "network_alpha", "max_train_epochs",
        })
        self.assertFalse(jobs.pid_alive(running["pid"]))
        previous_child = int((self.output / "child.pid").read_text(encoding="utf-8"))

        os.environ["FIZGIG_FAKE_STEPS"] = "30"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.1"
        resumed = self.client.post(f"/api/jobs/{job_id}/resume", json={})
        self.assertEqual(resumed.status_code, 200, resumed.text)
        command = self._job_file(job_id)["plan"]["stages"][0]["cmd"]
        self.assertIn("--resume", command)
        self.assertTrue(command[-1].endswith("WebRun-000001-state"))
        again = self.wait_for(lambda: (item := self.client.get(f"/api/jobs/{job_id}").json())["status"] == "running" and item.get("pid") and item)

        def live_child():
            try:
                child = int((self.output / "child.pid").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if child != previous_child and jobs.pid_alive(child):
                return child
            return None

        child = self.wait_for(live_child)
        self.assertTrue(jobs.pid_alive(again["pid"]))
        self.assertTrue(jobs.pid_alive(child))
        self.wait_for(lambda: "RESUMING from" in self.client.get(f"/api/jobs/{job_id}/log", params={"offset": 0}).json()["text"])

        stopped = self.client.post(f"/api/jobs/{job_id}/stop")
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertEqual(stopped.json()["status"], "stopped")
        self.wait_for(lambda: not jobs.pid_alive(again["pid"]) and not jobs.pid_alive(child))

    def _write_reused_pid_job(self, job_id):
        folder = self.root / "jobs" / job_id
        folder.mkdir(parents=True)
        job = {
            "id": job_id,
            "family": "sdxl",
            "status": "running",
            "pid": os.getpid(),
            "pid_create_time": 1.0,
            "stage": "",
            "step": 0,
            "total": 0,
            "loss": None,
            "created": "2020-01-01T00:00:00Z",
            "started": "2020-01-01T00:00:00Z",
            "ended": "",
            "output_dir": str(self.output),
            "values": {},
        }
        (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def test_reused_pid_is_not_the_runner(self):
        import psutil
        real = psutil.Process(os.getpid()).create_time()
        self.assertFalse(jobs.pid_alive(os.getpid(), 1.0))
        self.assertTrue(jobs.pid_alive(os.getpid(), real))

        self._write_reused_pid_job("reusedstop")
        stopped = self.client.post("/api/jobs/reusedstop/stop")
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertEqual(stopped.json()["status"], "failed")
        self.assertTrue(jobs.pid_alive(os.getpid()))

        self._write_reused_pid_job("reusedreconcile")
        jobs.reconcile()
        body = self.client.get("/api/jobs/reusedreconcile").json()
        self.assertNotEqual(body["status"], "running")
        self.assertEqual(body["status"], "failed")
        self.assertTrue(jobs.pid_alive(os.getpid()))

    def test_restart_reattaches(self):
        os.environ["FIZGIG_FAKE_STEPS"] = "40"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.1"
        created = self._create()
        job_id = created["id"]
        self.wait_for(lambda: self.client.get(f"/api/jobs/{job_id}").json()["step"] >= 1)
        jobs.reconcile()
        with TestClient(app, base_url="http://127.0.0.1") as fresh:
            body = fresh.get(f"/api/jobs/{job_id}").json()
            log = fresh.get(f"/api/jobs/{job_id}/log", params={"offset": 0}).json()
        self.assertEqual(body["status"], "running")
        self.assertGreaterEqual(body["step"], 1)
        self.assertEqual(body["loss"], 0.42)
        self.assertIn("avr_loss=0.42", log["text"])
        self.assertTrue(jobs.pid_alive(body["pid"]))

    def test_override_matches_desktop_format(self):
        created = self._create()
        job_id = created["id"]
        self.wait_for(lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"] == "done")
        response = self.client.post(f"/api/jobs/{job_id}/override", json={
            "prompt": "a cat", "seed": "nope", "width": 512, "height": 640,
        })
        self.assertEqual(response.status_code, 200, response.text)
        path = self.output / ".sample_override.json"
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            json.dumps({"prompt": "a cat", "seed": 1234, "width": 512, "height": 640}),
        )
        cleared = self.client.post(f"/api/jobs/{job_id}/override", json={"prompt": "  "})
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertFalse(path.exists())

    def test_gpu_lock_both_ways(self):
        self.assertFalse(held(), "a lock is already held; the desktop or another run has this GPU")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_REPO / "src")
        self._holder = subprocess.Popen(
            [sys.executable, "-c", "import time\nfrom fizgig.gpu_lock import GpuLock\nlock = GpuLock()\nassert lock.acquire()\ntime.sleep(30)\n"],
            env=env,
            creationflags=creationflags(),
        )
        self.wait_for(held)
        blocked = self.client.post("/api/jobs", json=self._payload())
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"], "the GPU is in use")
        self._holder.kill()
        self._holder.wait(timeout=5)
        self._holder = None
        self.wait_for(lambda: not held())

        os.environ["FIZGIG_FAKE_STEPS"] = "20"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.1"
        created = self._create()
        job_id = created["id"]
        self.wait_for(held)
        self.assertTrue(held())
        self.client.post(f"/api/jobs/{job_id}/stop")
        self.wait_for(lambda: not held())

    def test_problems_are_422(self):
        response = self.client.post("/api/jobs", json={
            "family": "qwen_image21",
            "values": {
                "kind": "Edit (original + edited photo pairs)",
                "LORA_OUTPUT_DIR": str(self.output),
                "LORA_NAME": "EditRun",
            },
        })
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn(_EDIT, response.text)
        self.assertNotIn("runpod_api_key", response.text)

    def test_paths_host_origin_and_secrets(self):
        created = self._create()
        job_id = created["id"]
        secret = self.root / "secret.txt"
        secret.write_text("runpod_api_key cabinet", encoding="utf-8")
        for name in ("..", "..\\secret.txt", "../secret.txt"):
            with self.assertRaises(jobs.JobError) as caught:
                jobs.sample_path(job_id, name)
            self.assertEqual(caught.exception.status, 404)
        # One URL segment. A raw ".." is collapsed by the HTTP client before it is sent.
        response = self.client.get(f"/api/jobs/{job_id}/samples/%2e%2e%5csecret.txt")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("cabinet", response.text)
        missing = self.client.get("/api/jobs/..")
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn("cabinet", missing.text)
        self.assertNotIn("runpod_api_key", self.client.get("/api/jobs").text)
        self.assertNotIn("runpod_api_key", self.client.get("/api/system").text)
        system = self.client.get("/api/system").json()
        self.assertIn("vram", system)
        self.assertIn("ram", system)

        foreign_origin = self.client.post("/api/jobs", json=self._payload(), headers={"Origin": "https://evil.example"})
        self.assertEqual(foreign_origin.status_code, 403)
        with TestClient(app, base_url="http://evil.example") as client:
            foreign_host = client.get("/api/jobs")
        self.assertEqual(foreign_host.status_code, 403)

        events = self.client.get("/api/events", params={"once": 1})
        self.assertEqual(events.status_code, 200)
        self.assertIn("text/event-stream", events.headers["content-type"])
        self.assertIn("event: job", events.text)
        self.assertIn("event: progress", events.text)
        self.assertIn("event: system", events.text)
        self.assertNotIn("runpod_api_key", events.text)


if __name__ == "__main__":
    unittest.main()
