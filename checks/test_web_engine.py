"""Engine host: protocol, newest-gen wins, idle unload, crash restart, GPU lock.

The worker is the fake engine. Nothing here loads a model or touches CUDA.

    python -m unittest checks.test_web_engine -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.gpu_lock import held
from fizgig.web import jobs
from fizgig.web.app import app
from fizgig.web.engine_host import EngineError, get_host, shutdown

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class WebEngineTests(unittest.TestCase):
    def setUp(self):
        shutdown()
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
        self.lora = self.output / "Demo.safetensors"
        self.lora.write_bytes(b"not a model")
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
            "profiles_dir": str(self.root / "profiles"),
        }), encoding="utf-8")
        self._env = {
            key: os.environ.get(key) for key in (
                "FIZGIG_WEB_JOBS", "FIZGIG_PREFS_FILE", "FIZGIG_NO_PERSIST",
                "FIZGIG_WEB_FAKE_ENGINE", "FIZGIG_WEB_FAKE_STEP", "FIZGIG_WEB_ENGINE_IDLE",
                "FIZGIG_WEB_FAKE_TRAINER", "FIZGIG_FAKE_STEPS", "FIZGIG_FAKE_SLEEP",
                "FIZGIG_WEB_PRESET_ROOT",
            )
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_FAKE_ENGINE"] = "1"
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.08"
        os.environ["FIZGIG_WEB_ENGINE_IDLE"] = "600"
        os.environ["FIZGIG_WEB_FAKE_TRAINER"] = str(_REPO / "checks" / "fake_trainer.py")
        os.environ["FIZGIG_FAKE_STEPS"] = "40"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.1"
        os.environ["FIZGIG_WEB_PRESET_ROOT"] = str(self.root / "presets")
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        shutdown()
        try:
            for job in jobs.list_jobs():
                if job["status"] in {"queued", "running"}:
                    self.client.post(f"/api/jobs/{job['id']}/stop")
        except Exception:
            pass
        self._client.__exit__(None, None, None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _wait(self, fn, timeout=8):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.02)
        self.fail(f"timed out; last={last!r}")

    def _collect(self, host, timeout=5):
        seen = []
        found = self._wait(lambda: seen.extend(host.drain()) or any(
            item.get("event") == "done" for item in seen) and seen, timeout)
        return found

    def test_protocol_round_trip(self):
        host = get_host()
        reply = host.load("repair", "klein", {"primary": str(self.lora)})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["engine"], "repair")
        gen = host.render({"steps": 2, "state": {"prompt": "a cat", "seed": 7}})
        seen = []
        self._wait(lambda: seen.extend(host.drain()) or any(item.get("event") == "done" for item in seen))
        done = [item for item in seen if item.get("event") == "done"]
        frames = [item for item in seen if item.get("event") == "frame"]
        self.assertEqual([item["gen"] for item in done], [gen])
        self.assertGreaterEqual(len(frames), 1)
        self.assertTrue(all(item["gen"] == gen for item in frames))
        image = Path(done[0]["image"])
        self.assertTrue(image.is_file())
        self.assertTrue(str(image).startswith(str(self.root / "jobs" / "engine")))
        served = self.client.get("/api/engine/file", params={"path": str(image)})
        self.assertEqual(served.status_code, 200, served.text)
        self.assertTrue(served.content.startswith(b"\x89PNG"))
        outside = self.root / "outside.png"
        outside.write_bytes(_PNG)
        denied = self.client.get("/api/engine/file", params={"path": str(outside)})
        self.assertEqual(denied.status_code, 403, denied.text)
        host.unload()
        self.assertFalse(host.status()["loaded"])
        self.assertFalse(held())

    def test_newest_gen_wins(self):
        host = get_host()
        host.load("repair", "klein", {"primary": str(self.lora)})
        first = host.render({"steps": 6}, gen=1)
        second = host.render({"steps": 2}, gen=2)
        self.assertEqual((first, second), (1, 2))
        seen = []
        self._wait(lambda: seen.extend(host.drain()) or any(
            item.get("event") == "done" and item.get("gen") == 2 for item in seen))
        dones = [item for item in seen if item.get("event") == "done"]
        frames = [item for item in seen if item.get("event") == "frame"]
        self.assertEqual([item["gen"] for item in dones], [2])
        self.assertTrue(frames)
        self.assertTrue(all(item["gen"] == 2 for item in frames))

    def test_idle_unload(self):
        os.environ["FIZGIG_WEB_ENGINE_IDLE"] = "0.35"
        shutdown()
        host = get_host()
        host.load("repair", "klein", {"primary": str(self.lora)})
        self.assertTrue(held())
        self._wait(lambda: host.status().get("loaded") is False, timeout=3)
        self.assertFalse(held())

    def test_worker_crash_restarts(self):
        host = get_host()
        with self.assertRaises(EngineError):
            host.load("repair", "klein", {"crash": True})
        events = []
        self._wait(lambda: events.extend(host.drain()) or any(item.get("restarted") for item in events))
        self.assertTrue(any(item.get("event") == "error" and item.get("restarted") for item in events))
        body = host.status()
        self.assertFalse(body["loaded"])
        self.assertTrue(body["restarted"])
        again = host.load("repair", "klein", {"primary": str(self.lora)})
        self.assertTrue(again["ok"])
        self.assertFalse(host.status()["restarted"])

    def test_gpu_lock_both_ways(self):
        self.assertFalse(held(), "a lock is already held")
        os.environ["FIZGIG_FAKE_STEPS"] = "40"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.1"
        created = self.client.post("/api/jobs", json={
            "family": "sdxl",
            "values": {
                "LORA_OUTPUT_DIR": str(self.output),
                "LORA_NAME": "WebRun",
                "LEARNING_RATE": 1e-4,
                "NETWORK_DIM": 4,
                "NETWORK_ALPHA": 4,
                "MAX_TRAIN_EPOCHS": 4,
                "SAVE_EVERY_N_EPOCHS": 1,
                "SEED": 1,
            },
            "context": {
                "models": {"sdxl_checkpoint": str(self.checkpoint)},
                "image_folder": str(self.images),
                "DATASET_CONFIG": str(self.output / "dataset.toml"),
            },
        })
        self.assertEqual(created.status_code, 200, created.text)
        self._wait(held)
        denied = self.client.post("/api/repair/load", json={"family": "klein", "primary": str(self.lora)})
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertIn("training or caption", denied.json()["detail"])
        self.client.post(f"/api/jobs/{created.json()['id']}/stop")
        self._wait(lambda: not held())

        loaded = self.client.post("/api/repair/load", json={"family": "klein", "primary": str(self.lora)})
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self._wait(held)
        blocked = self.client.post("/api/jobs", json={"family": "klein", "values": {}})
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("Unload it", blocked.json()["detail"])
        released = self.client.post("/api/engine/unload")
        self.assertEqual(released.status_code, 200, released.text)
        self._wait(lambda: not held())
        later = self.client.post("/api/jobs", json={"family": "klein", "values": {}})
        self.assertNotIn("Unload it", later.text)


if __name__ == "__main__":
    unittest.main()
