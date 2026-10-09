"""Job supervisor, GPU lock, and the phase 1 routes.

A stand-in trainer prints progress and writes one sample. Nothing here loads a model
or touches CUDA.

    python -m unittest checks.test_web_jobs -v
"""
import json
import os
import shutil
import subprocess
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

from fizgig.gpu_lock import GpuLock, held
from fizgig.web import jobs, queue
from fizgig.web.app import app
from fizgig.web.procs import creationflags
import runner_guard

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
_EDIT = "Edit LoRA is on: set the Originals folder (Training tab, Training Parameters)"


def _reset_queue() -> None:
    queue._SEEN.clear()
    queue._ACTIVE_SEEN.clear()
    queue._READY.clear()
    queue._HOLD.clear()
    queue._DEVICE.clear()


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
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "CUDA_DEVICE_ORDER": os.environ.get("CUDA_DEVICE_ORDER"),
        }
        _reset_queue()
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.root)
        os.environ["FIZGIG_WEB_FAKE_TRAINER"] = str(_REPO / "checks" / "fake_trainer.py")
        os.environ["FIZGIG_FAKE_STEPS"] = "3"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.02"
        self._holder = None
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        if self._holder is not None:
            self._holder.kill()
            try:
                self._holder.wait(timeout=5)
            except Exception:
                pass
        self._client.__exit__(None, None, None)
        runner_guard.end_runs(Path(os.environ["FIZGIG_WEB_JOBS"]))
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _reset_queue()
        self._tmp.cleanup()

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

    def _log_text(self, job_id):
        path = self.root / "jobs" / job_id / "log.txt"
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

    def _hold_gpu(self):
        """Another process takes GPU 0's lock and keeps it until the test kills it."""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_REPO / "src")
        script = (
            "import time\n"
            "from fizgig.gpu_lock import GpuLock\n"
            "lock = GpuLock(0)\n"
            "while not lock.acquire():\n"
            "    time.sleep(0.01)\n"
            "time.sleep(30)\n"
        )
        self._holder = subprocess.Popen([sys.executable, "-c", script], env=env, creationflags=creationflags())
        self.wait_for(lambda: held(0))

    def _wait_terminal(self, job_id, timeout=30):
        return self.wait_for(
            lambda: (body := self.client.get(f"/api/jobs/{job_id}").json())["status"] in {"done", "failed", "stopped"} and body,
            timeout=timeout,
        )

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
        sample = self.output / "sample"
        sample.mkdir(exist_ok=True)
        (sample / "WebRun_e000001.png").write_bytes(_PNG)
        (sample / "other_e000001.png").write_bytes(_PNG)
        listed = self.client.get(f"/api/jobs/{job_id}/samples").json()
        self.assertEqual([item["name"] for item in listed["samples"]], ["WebRun_e000001.png"])
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
        self.wait_for(lambda: not jobs.pid_alive(running["pid"]))
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

    def test_run_waits_for_a_lock_released_inside_the_grace(self):
        self._hold_gpu()
        # The server's check passed a moment before the engine worker let go of the card.
        with patch("fizgig.web.jobs.held", return_value=False), patch.dict(os.environ, {"FIZGIG_WEB_LOCK_GRACE": "15"}):
            created = self._create()
        job_id = created["id"]
        self.wait_for(lambda: "Waiting up to" in self._log_text(job_id), timeout=30)
        time.sleep(1)
        self._holder.kill()
        self._holder.wait(timeout=5)
        self._holder = None
        body = self._wait_terminal(job_id)
        log = self._log_text(job_id)
        self.assertEqual(body["status"], "done", f"{body}\n{log}")
        self.assertIn("Waiting up to 15 s for GPU 0", log)
        self.assertTrue((self.root / "jobs" / job_id / "runner.err").is_file())

    def test_run_fails_with_a_reason_when_the_lock_outlasts_the_grace(self):
        self._hold_gpu()
        with patch("fizgig.web.jobs.held", return_value=False), patch.dict(os.environ, {"FIZGIG_WEB_LOCK_GRACE": "1"}):
            created = self._create()
        job_id = created["id"]
        body = self._wait_terminal(job_id)
        log = self._log_text(job_id)
        self.assertEqual(body["status"], "failed", log)
        self.assertIn("Waiting up to 1 s for GPU 0", log)
        self.assertIn("GPU 0 is in use by another run; job not started.", log)

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

    def test_finished_job_does_not_reread_its_log(self):
        folder = self.root / "jobs" / "logged"
        folder.mkdir(parents=True)
        job = {
            "id": "logged",
            "kind": "train",
            "family": "sdxl",
            "status": "done",
            "step": 3,
            "total": 4,
            "loss": 0.1,
            "created": "2020-01-01T00:00:00Z",
            "output_dir": str(self.output),
            "values": {"LORA_NAME": "Logged", "MAX_TRAIN_EPOCHS": 1},
        }
        (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
        line = "steps: 9/10 [00:01<00:01, 1.00it/s, avr_loss=0.99]\n"
        (folder / "log.txt").write_text(line * 20000, encoding="utf-8")
        shown = self.client.get("/api/jobs/logged").json()
        self.assertEqual(shown["step"], 3)
        self.assertEqual(shown["loss"], 0.1)
        past = self.client.get("/api/history").json()["jobs"]
        row = next(item for item in past if item["id"] == "logged")
        self.assertEqual(row["step"], 3)

    def test_active_log_parses_only_new_bytes(self):
        folder = self.root / "jobs" / "live-log"
        folder.mkdir(parents=True)
        job = {
            "id": "live-log",
            "kind": "train",
            "family": "sdxl",
            "status": "running",
            "pid": os.getpid(),
            "step": 0,
            "total": 0,
            "loss": None,
            "created": "2020-01-01T00:00:00Z",
            "output_dir": str(self.output),
            "values": {"MAX_TRAIN_EPOCHS": 1},
        }
        (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
        log = folder / "log.txt"
        log.write_text("steps: 1/4 [00:01<00:03, 1.00it/s, avr_loss=0.20]\n", encoding="utf-8")
        self.assertEqual(self.client.get("/api/jobs/live-log").json()["step"], 1)
        with log.open("a", encoding="utf-8") as handle:
            handle.write("steps: 2/4 [00:02<00:02, 1.00it/s, avr_loss=0.30]\n")
        body = self.client.get("/api/jobs/live-log").json()
        self.assertEqual(body["step"], 2)
        self.assertEqual(body["loss"], 0.3)

    def test_launch_paths_stay_inside_roots(self):
        denied = self.client.post("/api/jobs", json=self._payload(LORA_OUTPUT_DIR=r"Z:\fizgig-outside-root\nope"))
        self.assertEqual(denied.status_code, 403, denied.text)
        body = self._payload()
        body["values"]["image_folder"] = r"Z:\fizgig-outside-root\images"
        body["context"]["image_folder"] = body["values"]["image_folder"]
        denied_images = self.client.post("/api/jobs", json=body)
        self.assertEqual(denied_images.status_code, 403, denied_images.text)
        created = self.root / "brand-new-lora"
        body = self._payload(LORA_OUTPUT_DIR=str(created))
        body["context"]["DATASET_CONFIG"] = str(created / "dataset.toml")
        ok = self.client.post("/api/jobs", json=body)
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertTrue(created.is_dir())

        folder = self.root / "jobs" / "evil-out"
        folder.mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({
            "id": "evil-out",
            "status": "done",
            "output_dir": "\\\\no-such-host\\share\\out",
            "created": "2020-01-01T00:00:00Z",
        }), encoding="utf-8")
        from fizgig.web import fs
        started = time.time()
        roots = fs.output_roots()
        self.assertLess(time.time() - started, 2)
        self.assertFalse(any("no-such-host" in str(path) for path in roots))

    def test_confine_refuses_every_client_path_outside_roots(self):
        outside = Path(tempfile.mkdtemp(prefix="fizgig-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "pic.png").write_bytes(_PNG)
        (outside / "dir").mkdir()
        picture = str(outside / "pic.png")
        cases = [
            ({"FAMILY_MULTICONCEPT": "1", "MINIMAX_CONCEPT_DIRS": [str(outside / "dir")]}, {}),
            ({}, {"captioner": picture}),
            ({}, {"ft_resume": {"checkpoint": picture}}),
            ({"METADATA_THUMBNAIL": picture}, {}),
            ({"FAMILY_EDIT_REF": picture}, {}),
            ({}, {"models": {"sdxl_vae": str(outside / "gone.safetensors")}}),
        ]
        for values, context in cases:
            with self.subTest(values=values, context=context):
                with self.assertRaises(jobs.JobError) as caught:
                    jobs._confine_paths(dict(values), dict(context))
                self.assertEqual(caught.exception.status, 403)

    def test_missing_model_path_does_not_block_the_run(self):
        context = {
            "models": {
                "speed_lora": str(self.root / "moved" / "speed.safetensors"),
                "sdxl_checkpoint": str(self.checkpoint),
            },
        }
        jobs._confine_paths({}, context)
        self.assertEqual(context["models"]["speed_lora"], str(self.root / "moved" / "speed.safetensors"))
        self.assertEqual(context["models"]["sdxl_checkpoint"], str(self.checkpoint.resolve()))

    def test_stale_optional_preference_does_not_block_the_run(self):
        outside = Path(tempfile.mkdtemp(prefix="fizgig-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        prefs = self.root / "prefs.json"
        prefs.write_text(json.dumps({"sdxl_vae": str(outside / "stale-vae.safetensors")}), encoding="utf-8")
        before = os.environ.get("FIZGIG_PREFS_FILE")
        os.environ["FIZGIG_PREFS_FILE"] = str(prefs)

        def restore_prefs_env():
            if before is None:
                os.environ.pop("FIZGIG_PREFS_FILE", None)
            else:
                os.environ["FIZGIG_PREFS_FILE"] = before

        self.addCleanup(restore_prefs_env)
        created = self.client.post("/api/jobs", json=self._payload())
        self.assertEqual(created.status_code, 200, created.text)

    def test_pause_records_tidied_name_or_failure(self):
        output = self.root / "tidy-out"
        output.mkdir()
        state = output / "WebRun-000001-state"
        state.mkdir()
        (state / "training_state.json").write_text("{}", encoding="utf-8")
        folder = self.root / "jobs" / "tidy-pause"
        folder.mkdir(parents=True)
        job = {
            "id": "tidy-pause",
            "status": "running",
            "output_dir": str(output),
            "values": {"LORA_NAME": "WebRun."},
            "dataset_config": str(output / "dataset.toml"),
        }
        (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
        jobs.mark_paused(folder, job)
        saved = json.loads((folder / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "paused")
        self.assertTrue(str(saved["state_path"]).endswith("WebRun-000001-state"))

        missing = self.root / "jobs" / "no-state"
        missing.mkdir(parents=True)
        (missing / "job.json").write_text(json.dumps({
            "id": "no-state", "status": "running", "output_dir": str(self.output),
            "values": {"LORA_NAME": "Missing"},
        }), encoding="utf-8")
        jobs.mark_paused(missing, {
            "id": "no-state", "status": "running", "output_dir": str(self.output),
            "values": {"LORA_NAME": "Missing"},
        })
        saved = json.loads((missing / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["exit_code"], 0)
        self.assertTrue(saved["ended"])

    def test_pause_flag_survives_a_cache_stage(self):
        from fizgig.web.runner import run_folder

        output = self.root / "cache-pause"
        output.mkdir()
        (output / ".pause_requested").write_text("", encoding="utf-8")
        script = self.root / "see_flag.py"
        script.write_text(
            "import os\nfrom pathlib import Path\n"
            "out = Path(os.environ['FIZGIG_FAKE_OUTPUT'])\n"
            "flag = out / '.pause_requested'\n"
            "(out / 'cache_saw_flag').write_text('1' if flag.is_file() else '0', encoding='utf-8')\n",
            encoding="utf-8",
        )
        folder = self.root / "jobs" / "cache-pause"
        folder.mkdir(parents=True)
        job = {
            "id": "cache-pause",
            "kind": "train",
            "family": "sdxl",
            "device": 0,
            "status": "queued",
            "pid": 0,
            "values": {"LORA_NAME": "WebRun", "MAX_TRAIN_EPOCHS": 1, "RESUME_TRAINING": ""},
            "plan": {"stages": [
                {"name": "Cache Preparation", "cmd": [sys.executable, str(script)]},
                {"name": "Training", "cmd": [sys.executable, str(_REPO / "checks" / "fake_trainer.py")]},
            ]},
            "output_dir": str(output),
            "created": "2020-01-01T00:00:00Z",
        }
        (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
        os.environ["FIZGIG_FAKE_STEPS"] = "4"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.01"
        run_folder(folder)
        saved = json.loads((folder / "job.json").read_text(encoding="utf-8"))
        self.assertEqual((output / "cache_saw_flag").read_text(encoding="utf-8"), "1")
        self.assertEqual(saved["status"], "paused", (folder / "log.txt").read_text(encoding="utf-8", errors="replace") if (folder / "log.txt").is_file() else saved)
        self.assertTrue((output / "WebRun-000001-state").is_dir())

    def test_status_write_does_not_kill_the_trainer(self):
        from fizgig.web import runner

        output = self.root / "write-skip"
        output.mkdir()
        folder = self.root / "jobs" / "write-skip"
        folder.mkdir(parents=True)
        job = {
            "id": "write-skip",
            "kind": "train",
            "family": "sdxl",
            "device": 0,
            "status": "queued",
            "pid": 0,
            "values": {"LORA_NAME": "WebRun", "MAX_TRAIN_EPOCHS": 1},
            "plan": {"stages": [
                {"name": "Training", "cmd": [sys.executable, str(_REPO / "checks" / "fake_trainer.py")]},
            ]},
            "output_dir": str(output),
            "created": "2020-01-01T00:00:00Z",
        }
        (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
        os.environ["FIZGIG_FAKE_STEPS"] = "2"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.01"
        real = runner.save
        calls = {"n": 0}

        def flaky(target, record):
            if record.get("step") and calls["n"] < 2:
                calls["n"] += 1
                raise PermissionError("busy")
            return real(target, record)

        with patch("fizgig.web.runner.save", side_effect=flaky):
            runner.run_folder(folder)
        saved = json.loads((folder / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "done")
        self.assertGreaterEqual(calls["n"], 1)

    def test_spawn_failure_and_stale_queue_are_failed(self):
        with patch("fizgig.web.jobs.subprocess.Popen", side_effect=OSError("nope")):
            created = self._create()
        job_id = created["id"]
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["status"], "failed")

        folder = self.root / "jobs" / "stuck"
        folder.mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({
            "id": "stuck", "status": "queued", "pid": 0, "kind": "train",
            "created": "2020-01-01T00:00:00Z", "output_dir": str(self.output),
        }), encoding="utf-8")
        jobs.reconcile()
        self.assertEqual(json.loads((folder / "job.json").read_text(encoding="utf-8"))["status"], "queued")
        old = time.time() - 60
        os.utime(folder / "job.json", (old, old))
        jobs.reconcile()
        self.assertEqual(json.loads((folder / "job.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_runner_that_cannot_start_records_the_reason(self):
        with patch("fizgig.web.jobs.subprocess.Popen", side_effect=OSError("nope")):
            created = self._create()
        job_id = created["id"]
        job = self._job_file(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("nope", job["error"])
        self.assertIn("nope", self._log_text(job_id))

    def test_log_is_capped_and_tail_is_marked(self):
        created = self._create()
        job_id = created["id"]
        self.wait_for(lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"] == "done")
        path = self.root / "jobs" / job_id / "log.txt"
        blob = b"A" * (300 * 1024)
        path.write_bytes(blob)
        part = self.client.get(f"/api/jobs/{job_id}/log", params={"offset": 0}).json()
        self.assertEqual(set(part), {"offset", "next", "text"})
        self.assertEqual(part["offset"], 0)
        self.assertLessEqual(len(part["text"].encode("utf-8")), 256 * 1024)
        self.assertEqual(part["next"], len(part["text"].encode("utf-8")))
        tail = self.client.get(f"/api/jobs/{job_id}/log", params={"offset": -1}).json()
        self.assertEqual(tail["offset"], len(blob) - 256 * 1024)
        self.assertEqual(tail["next"], len(blob))
        self.assertEqual(len(tail["text"].encode("utf-8")), 256 * 1024)

    def test_samples_keep_this_lora_and_the_latest(self):
        folder = self.root / "jobs" / "gallery"
        folder.mkdir(parents=True)
        output = self.root / "gallery-out"
        sample = output / "sample"
        sample.mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({
            "id": "gallery", "status": "done", "output_dir": str(output),
            "values": {"LORA_NAME": "Web Run"}, "created": "2020-01-01T00:00:00Z",
        }), encoding="utf-8")
        now = time.time()
        for index in range(50):
            path = sample / f"Web Run_e{index:06d}.png"
            path.write_bytes(_PNG)
            stamp = now + index
            os.utime(path, (stamp, stamp))
        (sample / "Other_e000001.png").write_bytes(_PNG)
        (sample / "sample_0001.png").write_bytes(_PNG)
        listed = self.client.get("/api/jobs/gallery/samples").json()["samples"]
        self.assertEqual(len(listed), 48)
        self.assertTrue(all(item["name"].startswith("Web Run_") for item in listed))
        self.assertEqual(listed[0]["name"], "Web Run_e000049.png")
        self.assertIn("%20", listed[0]["url"])
        image = self.client.get(listed[0]["url"])
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.content.startswith(b"\x89PNG"))

    def test_corrupt_record_can_be_deleted(self):
        folder = self.root / "jobs" / "broken"
        folder.mkdir(parents=True)
        (folder / "job.json").write_bytes(b"\xff\xfe not json")
        (folder / "log.txt").write_text("keep", encoding="utf-8")
        listed = self.client.get("/api/jobs").json()["jobs"]
        self.assertTrue(any(item["id"] == "broken" and item["status"] == "corrupt" for item in listed))
        removed = self.client.delete("/api/jobs/broken")
        self.assertEqual(removed.status_code, 204, removed.text)
        self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
