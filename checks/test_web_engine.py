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
sys.path.insert(0, str(_REPO / "checks"))

from fastapi.testclient import TestClient

from fizgig.gpu_lock import held
from fizgig.web.app import app
from fizgig.web.engine_host import EngineError, get_host, shutdown
import runner_guard

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
        self.root = Path(self._tmp.name).resolve()
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
                "FIZGIG_WEB_PRESET_ROOT", "FIZGIG_WEB_ROOTS",
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
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.root)
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        shutdown()
        self._client.__exit__(None, None, None)
        runner_guard.end_runs(Path(os.environ["FIZGIG_WEB_JOBS"]))
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

    def _finished(self, host, gen, timeout=8):
        """Wait for the done event of ``gen``. Returns every event read on the way."""
        seen = []

        def check():
            seen.extend(host.drain())
            return any(item.get("event") == "done" and item.get("gen") == gen for item in seen)

        self._wait(check, timeout)
        return seen

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
        second = host.render({"steps": 2}, gen=1)
        self.assertEqual(second, first + 1)
        self.assertNotEqual(first, 1)
        seen = []
        self._wait(lambda: seen.extend(host.drain()) or any(
            item.get("event") == "done" and item.get("gen") == second for item in seen))
        dones = [item for item in seen if item.get("event") == "done"]
        frames = [item for item in seen if item.get("event") == "frame"]
        self.assertEqual([item["gen"] for item in dones], [second])
        self.assertTrue(frames)
        self.assertTrue(all(item["gen"] == second for item in frames))

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

    def test_events_since_does_not_consume(self):
        from fizgig.web.engine_host import events_since, get_host
        shutdown()
        self.assertEqual(events_since(4), ([], 4))
        host = get_host()
        seq = host.publish({"event": "frame", "gen": 3, "_token": "hidden", "private": "hidden"})
        self.assertEqual(seq, 1)
        first, cursor = host.events_since(0)
        second, _again = host.events_since(0)
        self.assertEqual(first, second)
        self.assertEqual(cursor, 1)
        self.assertEqual(first[0]["event"], "frame")
        self.assertNotIn("_token", first[0])
        self.assertNotIn("private", first[0])
        self.assertEqual(host.drain(), first)
        self.assertEqual(host.drain(), [])
        self.assertEqual(host.events_since(0)[0], first)
        for index in range(200):
            host.publish({"event": "tick", "n": index})
        batch, _cursor = host.events_since(0)
        self.assertEqual(len(batch), 200)
        self.assertNotIn(1, [item.get("seq") for item in batch])
        host.publish({"event": "old"})
        host._times[:] = [time.monotonic() - 121] * len(host._times)
        host.publish({"event": "fresh"})
        kept = [item.get("event") for item in host.events_since(0)[0]]
        self.assertNotIn("old", kept)
        self.assertEqual(kept, ["fresh"])

    def test_stale_render_raises(self):
        from fizgig.web.engine_host import EngineError, get_host
        host = get_host()
        host.request = lambda payload, timeout=30: {"ok": True, "stale": True, "gen": payload.get("gen")}
        with self.assertRaises(EngineError):
            host.render({"steps": 1}, gen=9)
        self.assertFalse(host.busy)

    def test_failed_load_unloads_before_unlock(self):
        from fizgig.web.engine_host import EngineError, get_host
        marker = self.root / "unloaded.txt"
        host = get_host()
        with self.assertRaises(EngineError):
            host.load("repair", "klein", {"fail_load": True, "fail_marker": str(marker), "primary": str(self.lora)})
        self.assertTrue(marker.is_file())
        self.assertFalse(held())
        self.assertFalse(host.loaded)

    def test_set_device_refuses_while_a_request_is_in_flight(self):
        import threading
        from fizgig.web.engine_host import EngineError, get_host
        host = get_host()
        errors = []

        def loader():
            try:
                host.load("repair", "klein", {"primary": str(self.lora), "delay": 0.6})
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=loader)
        thread.start()
        self._wait(lambda: bool(host._waiters), timeout=3)
        with self.assertRaises(EngineError) as caught:
            host.set_device(1)
        self.assertIn("busy", caught.exception.message.lower())
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(host.loaded)

    def test_long_load_and_render_are_not_idle_immediately(self):
        os.environ["FIZGIG_WEB_ENGINE_IDLE"] = "0.25"
        shutdown()
        host = get_host()
        host.load("repair", "klein", {"primary": str(self.lora), "delay": 0.7})
        time.sleep(0.1)
        self.assertTrue(host.status()["loaded"])
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.2"
        shutdown()
        host = get_host()
        host.load("repair", "klein", {"primary": str(self.lora)})
        host.render({"steps": 3})
        self._wait(lambda: host.busy is False, timeout=5)
        time.sleep(0.1)
        self.assertTrue(host.loaded)

    def test_stuck_render_is_not_unloaded(self):
        from fizgig.web.engine_host import EngineError, get_host
        marker = self.root / "stuck.txt"
        host = get_host()
        host.load("repair", "klein", {"primary": str(self.lora), "stuck_marker": str(marker)})
        host.render({"stuck": True, "steps": 1})
        self._wait(lambda: host.busy, timeout=3)
        started = time.time()
        try:
            host.unload()
        except EngineError:
            pass
        self.assertLess(time.time() - started, 20)
        self.assertFalse(marker.exists())
        self._wait(lambda: not held(), timeout=5)

    def _spawn_without_worker(self, host):
        """Run ``_spawn`` up to the Popen call, and return the env it would start the worker with."""
        from fizgig.web import engine_host as hostmod
        seen = {}

        def spy(*_args, **kwargs):
            seen["env"] = kwargs.get("env") or {}
            raise RuntimeError("stop")

        original = hostmod.subprocess.Popen
        hostmod.subprocess.Popen = spy
        try:
            with self.assertRaises(RuntimeError):
                host._spawn()
        finally:
            hostmod.subprocess.Popen = original
            if host._stderr is not None:
                host._stderr.close()
        return seen["env"]

    def test_spawn_drops_old_sessions_and_sets_pci_order(self):
        from fizgig.web import engine_host as hostmod
        from fizgig.web.jobs import jobs_root
        old = jobs_root() / "engine" / "old-session"
        old.mkdir(parents=True)
        (old / hostmod._SESSION_MARK).write_text("session\n", encoding="utf-8")
        (old / "junk.txt").write_text("x", encoding="utf-8")
        host = hostmod.get_host()
        host.load("repair", "klein", {"primary": str(self.lora)})
        self.assertFalse(old.exists())
        self.assertTrue(host.session is not None and host.session.is_dir())
        bare = hostmod.EngineHost()
        env = self._spawn_without_worker(bare)
        self.assertEqual(env.get("CUDA_DEVICE_ORDER"), "PCI_BUS_ID")
        self.assertEqual(env.get("CUDA_VISIBLE_DEVICES"), str(bare.device))

    def test_spawn_keeps_folders_a_person_made_under_engine(self):
        from fizgig.web import engine_host as hostmod
        from fizgig.web.jobs import jobs_root
        root = jobs_root() / "engine"
        mine = root / "run1"
        mine.mkdir(parents=True)
        (mine / "Demo.safetensors").write_bytes(b"not a model")
        host = hostmod.get_host()
        host.load("repair", "klein", {"primary": str(self.lora)})
        self.assertTrue((mine / "Demo.safetensors").is_file())

    def test_spawn_keeps_sessions_while_a_job_may_read_them(self):
        from fizgig.web import engine_host as hostmod
        from fizgig.web.jobs import jobs_root
        root = jobs_root() / "engine"
        held = root / "held-session"
        held.mkdir(parents=True)
        (held / hostmod._SESSION_MARK).write_text("session\n", encoding="utf-8")
        job = jobs_root() / "export1"
        job.mkdir(parents=True)
        job_file = job / "job.json"
        job_file.write_text(json.dumps({
            "id": "export1", "kind": "royale", "status": "running", "device": 0,
            "created": "2020-01-01T00:00:00Z",
        }), encoding="utf-8")
        self._spawn_without_worker(hostmod.EngineHost())
        self.assertTrue(held.is_dir())
        job_file.write_text(json.dumps({
            "id": "export1", "kind": "royale", "status": "done", "device": 0,
            "created": "2020-01-01T00:00:00Z",
        }), encoding="utf-8")
        self._spawn_without_worker(hostmod.EngineHost())
        self.assertFalse(held.exists())

    def test_render_after_unload_and_reload_is_accepted(self):
        host = get_host()
        host.load("repair", "klein", {"primary": str(self.lora)})
        host.unload()
        host.load("repair", "klein", {"primary": str(self.lora)})
        gen = host.render({"steps": 2})
        self.assertEqual(gen, host.latest)
        self._finished(host, gen)
        self.assertFalse(host.busy)
        self.assertEqual(host.status()["gen"], gen)
        host.unload()
        self.assertFalse(host.status()["loaded"])

    def test_cancelled_render_clears_worker_busy(self):
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.05"
        shutdown()
        host = get_host()
        host.load("repair", "klein", {"primary": str(self.lora)})
        gen = host.render({"steps": 200})
        seen = []
        self._wait(lambda: seen.extend(host.drain()) or any(
            item.get("event") == "frame" and item.get("gen") == gen for item in seen))
        started = time.monotonic()
        host.unload()
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse(host.status()["busy"])
        host.load("repair", "klein", {"primary": str(self.lora)})
        again = host.render({"steps": 1})
        self._finished(host, again)
        self.assertFalse(host.status()["busy"])

    def test_timed_out_request_does_not_block_set_device(self):
        import threading
        from fizgig.web.engine_host import EngineError
        host = get_host()
        errors = []

        def loader():
            try:
                host.load("repair", "klein", {"primary": str(self.lora), "delay": 0.6})
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=loader)
        thread.start()
        self._wait(lambda: bool(host._waiters), timeout=3)
        with self.assertRaises(EngineError) as caught:
            host.request({"op": "status"}, timeout=0.05)
        self.assertIn("did not answer", caught.exception.message)
        thread.join(3)
        self.assertEqual(errors, [])
        self.assertTrue(host.loaded)
        self.assertEqual(host._waiters, {})
        host.unload()
        host.set_device(1)
        self.assertEqual(host.device, 1)
        self.assertEqual(host._replies, {})

    def test_epoch_frames_survive_later_travel_renders(self):
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.01"
        shutdown()
        host = get_host()
        host.load("royale", "klein", {"lora": str(self.lora)})
        epochs = host.render({"mode": "epochs", "steps": 2, "epochs": []})
        self._finished(host, epochs)
        folder = host.session
        self.assertIsNotNone(folder)
        shown = [folder / f"g{epochs}-s{step}.png" for step in (1, 2)]
        self.assertTrue(all(path.is_file() for path in shown))
        for _ in range(4):
            travel = host.render({"mode": "travel", "kind": "seed", "steps": 2, "seeds": [1, 2]})
            self._finished(host, travel)
        self.assertTrue(all(path.is_file() for path in shown), [path.name for path in folder.iterdir()])
        self.assertTrue(any(path.name.startswith(f"g{travel}-") for path in folder.iterdir()))

    def test_old_preview_files_are_dropped(self):
        from fizgig.web.engine_host import get_host
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.01"
        shutdown()
        host = get_host()
        host.load("repair", "klein", {"primary": str(self.lora)})
        gens = []
        for _ in range(4):
            gen = host.render({"steps": 1})
            gens.append(gen)
            self._wait(lambda gen=gen: any(
                item.get("event") == "done" and item.get("gen") == gen for item in host.drain()
            ))
        folder = host.session
        self.assertIsNotNone(folder)
        names = [path.name for path in folder.iterdir()]
        self.assertFalse(any(name.startswith(f"g{gens[0]}-") for name in names))
        self.assertTrue(any(name.startswith(f"g{gens[-1]}-") for name in names))

    def test_repair_clip_uses_worker_gen(self):
        from fizgig.web.engine_host import WorkbenchAdapter, _clip_file
        folder = self.root / "clips"
        folder.mkdir()
        previous = os.environ.get("FIZGIG_WEB_ENGINE_DIR")
        os.environ["FIZGIG_WEB_ENGINE_DIR"] = str(folder)

        class Img:
            def save(self, target, format=None):
                if hasattr(target, "write"):
                    target.write(b"png")
                else:
                    Path(target).write_bytes(b"png")

        try:
            stale = folder / "g7-clip-frames"
            stale.mkdir()
            (stale / "stale.png").write_bytes(b"old")
            _clip_file([Img()], folder / "g7-clip.mp4", 24)
            self.assertFalse((stale / "stale.png").exists())
            self.assertTrue((stale / "f0000.png").is_file())

            class Eng:
                def baseline_clip(self, state, frames=None, with_audio=False):
                    return {"middle": Img()}

                def render_clip(self, state, frames=None, with_audio=False, early_step=0, on_early=None):
                    return {"middle": Img(), "frames": [Img()]}

            adapter = WorkbenchAdapter("repair")
            adapter.engine = Eng()
            adapter._repair({"video": True, "state": {}, "fps": 24}, lambda *_args: None, 7)
            self.assertTrue((folder / "g7-clip-frames" / "f0000.png").is_file())
            self.assertFalse((folder / "g0-clip.mp4").exists())
        finally:
            if previous is None:
                os.environ.pop("FIZGIG_WEB_ENGINE_DIR", None)
            else:
                os.environ["FIZGIG_WEB_ENGINE_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
