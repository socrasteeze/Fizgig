"""Repair presets, the bake arguments, and a fake render.

Nothing here loads a model or touches CUDA.

    python -m unittest checks.test_web_repair -v
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

from fizgig.repair_studio.state import SliderState
from fizgig.web.app import app
from fizgig.web.engine_host import shutdown


class WebRepairTests(unittest.TestCase):
    def setUp(self):
        shutdown()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.output = self.root / "output"
        self.output.mkdir()
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()
        self.lora = self.output / "Demo.safetensors"
        self.lora.write_bytes(b"not a model")
        self.donor = self.output / "Donor.safetensors"
        self.donor.write_bytes(b"not a model")
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
            "profiles_dir": str(self.profiles),
        }), encoding="utf-8")
        self._env = {
            key: os.environ.get(key) for key in (
                "FIZGIG_WEB_JOBS", "FIZGIG_PREFS_FILE", "FIZGIG_NO_PERSIST",
                "FIZGIG_WEB_FAKE_ENGINE", "FIZGIG_WEB_FAKE_STEP", "FIZGIG_WEB_ENGINE_IDLE",
                "FIZGIG_WEB_PRESET_ROOT",
            )
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_FAKE_ENGINE"] = "1"
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.01"
        os.environ["FIZGIG_WEB_ENGINE_IDLE"] = "600"
        os.environ["FIZGIG_WEB_PRESET_ROOT"] = str(self.root / "presets")
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        shutdown()
        self._client.__exit__(None, None, None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _wait(self, fn, timeout=5):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.02)
        self.fail(f"timed out; last={last!r}")

    def test_preset_round_trip_is_slider_state(self):
        form = self.client.get("/api/repair/form", params={"family": "klein"})
        self.assertEqual(form.status_code, 200, form.text)
        body = form.json()
        self.assertIn("✨Identity Only", body["builtins"])
        self.assertEqual(body["debounce_ms"], 400)
        blocks = body["defaults"]["blocks"]
        first = next(iter(blocks))
        blocks[first]["primary_strength"] = 0.25
        blocks[first]["primary_enabled"] = False
        saved = self.client.put("/api/repair/presets", json={
            "family": "klein",
            "name": "Soft",
            "state": {
                "blocks": blocks,
                "prompt": "should not be stored",
                "seed": 99,
                "preview_width": 256,
                "preview_height": 256,
            },
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        on_disk = json.loads(Path(saved.json()["path"]).read_text(encoding="utf-8"))
        self.assertEqual(set(on_disk), {"blocks", "family"})
        self.assertNotIn("prompt", on_disk)
        state = SliderState.from_json(on_disk)
        self.assertFalse(state.blocks[first].primary_enabled)
        self.assertEqual(state.blocks[first].primary_strength, 0.25)
        self.assertEqual(state.prompt, "")
        loaded = self.client.get("/api/repair/presets/file", params={"family": "klein", "name": "Soft"})
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertNotIn("prompt", loaded.json())
        self.assertFalse(loaded.json()["blocks"][first]["primary_enabled"])
        identity = self.client.get("/api/repair/presets/file", params={"family": "klein", "name": "✨Identity Only"})
        self.assertEqual(identity.status_code, 200, identity.text)
        rows = identity.json()["blocks"]
        self.assertFalse(rows["double_0"]["primary_enabled"])
        self.assertTrue(rows["single_2"]["primary_enabled"])

    def test_bake_calls_desktop_function(self):
        import fizgig.repair_studio.bake as bake_mod
        seen = {}

        def fake_bake(primary_path, state, out_path, donor_path=None):
            seen["primary"] = primary_path
            seen["state"] = state
            seen["out"] = out_path
            seen["donor"] = donor_path
            return {
                "keys_in": 1, "keys_out": 1, "dropped_blocks": [],
                "rescaled_blocks": [], "blended_blocks": [], "use_at": 1.0,
            }

        original = bake_mod.save_repaired_lora
        bake_mod.save_repaired_lora = fake_bake
        try:
            plain = self.client.post("/api/repair/bake", json={
                "family": "klein",
                "primary": str(self.lora),
                "state": {"blocks": {"double_0": {
                    "primary_enabled": True, "primary_strength": 0.5,
                    "donor_enabled": False, "donor_strength": 1.0,
                }}},
            })
            self.assertEqual(plain.status_code, 200, plain.text)
            self.assertEqual(seen["primary"], str(self.lora.resolve()))
            self.assertIsNone(seen["donor"])
            self.assertIsInstance(seen["state"], SliderState)
            self.assertEqual(seen["state"].blocks["double_0"].primary_strength, 0.5)
            self.assertTrue(str(seen["out"]).endswith("Demo_repaired.safetensors"))

            mixed = self.client.post("/api/repair/bake", json={
                "family": "klein",
                "primary": str(self.lora),
                "donor": str(self.donor),
                "output_name": "mixed.safetensors",
                "state": {"blocks": {"double_0": {
                    "primary_enabled": True, "primary_strength": 1.0,
                    "donor_enabled": True, "donor_strength": 0.4,
                }}},
            })
            self.assertEqual(mixed.status_code, 200, mixed.text)
            self.assertEqual(seen["donor"], str(self.donor.resolve()))
            self.assertTrue(str(seen["out"]).endswith("mixed.safetensors"))
        finally:
            bake_mod.save_repaired_lora = original

    def test_render_images_and_metrics(self):
        loaded = self.client.post("/api/repair/load", json={"family": "klein", "primary": str(self.lora)})
        self.assertEqual(loaded.status_code, 200, loaded.text)
        started = self.client.post("/api/repair/render", json={
            "family": "klein",
            "steps": 2,
            "state": {"prompt": "a cat", "seed": 3, "preview_width": 512, "preview_height": 512, "blocks": {}},
        })
        self.assertEqual(started.status_code, 200, started.text)
        gen = started.json()["gen"]

        def finished():
            body = self.client.get("/api/repair/status").json()
            result = body.get("result") or {}
            return result if result.get("event") == "done" and result.get("gen") == gen else None

        result = self._wait(finished)
        metrics = self.client.post("/api/repair/metrics", json={
            "family": "klein",
            "baseline": result["baseline"],
            "tweaked": result["image"],
        })
        self.assertEqual(metrics.status_code, 200, metrics.text)
        self.assertIn("grid_delta", metrics.json())

    def test_bake_uses_loaded_engine(self):
        import fizgig.repair_studio.bake as bake_mod
        loaded = self.client.post("/api/repair/load", json={
            "family": "klein", "primary": str(self.lora), "donor": str(self.donor),
        })
        self.assertEqual(loaded.status_code, 200, loaded.text)

        def fake_bake(*_args, **_kwargs):
            raise AssertionError("file baker ran")

        original = bake_mod.save_repaired_lora
        bake_mod.save_repaired_lora = fake_bake
        try:
            saved = self.client.post("/api/repair/bake", json={
                "family": "klein",
                "primary": str(self.lora),
                "donor": str(self.donor),
                "state": {"blocks": {"double_0": {
                    "primary_enabled": True, "primary_strength": 0.5,
                    "donor_enabled": True, "donor_strength": 0.4,
                }}, "prompt": "a cat"},
            })
        finally:
            bake_mod.save_repaired_lora = original
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        payload = json.loads(Path(body["path"]).read_text(encoding="utf-8"))
        self.assertTrue(payload["engine"])
        self.assertEqual(payload["prompt"], "a cat")
        self.assertTrue(payload["include_donor"])
        self.assertTrue(body["summary"].get("engine"))

    def test_bake_refuses_unmapped_family(self):
        for family in ("zimage", "qwen_image21", "sdxl"):
            reply = self.client.post("/api/repair/bake", json={
                "family": family,
                "primary": str(self.lora),
                "state": {"blocks": {}},
            })
            self.assertEqual(reply.status_code, 422, reply.text)
            self.assertIn("cannot be baked", reply.text)
        self.assertEqual(list(self.output.glob("*repaired*")), [])

    def test_bake_rejects_bad_output_name(self):
        reply = self.client.post("/api/repair/bake", json={
            "family": "klein", "primary": str(self.lora),
            "output_name": "bad:name.safetensors", "state": {"blocks": {}},
        })
        self.assertEqual(reply.status_code, 422, reply.text)
        reply = self.client.post("/api/repair/bake", json={
            "family": "klein", "primary": str(self.lora),
            "output_name": "../outside.safetensors", "state": {"blocks": {}},
        })
        self.assertEqual(reply.status_code, 422, reply.text)

    def test_read_preset_stays_in_the_preset_dir(self):
        outside = self.root / "secret.json"
        outside.write_text(json.dumps({
            "blocks": {"double_0": {
                "primary_enabled": True, "primary_strength": 0.13,
                "donor_enabled": False, "donor_strength": 1,
            }},
        }), encoding="utf-8")
        reply = self.client.get("/api/repair/presets/file", params={
            "family": "klein", "name": str(outside.with_suffix("")),
        })
        self.assertNotEqual(reply.status_code, 200, reply.text)
        self.assertNotIn("0.13", reply.text)
        reserved = self.client.put("/api/repair/presets", json={
            "family": "klein", "name": "CON", "state": {"blocks": {}},
        })
        self.assertEqual(reserved.status_code, 422, reserved.text)
        dotted = self.client.put("/api/repair/presets", json={
            "family": "klein", "name": "CON.txt", "state": {"blocks": {}},
        })
        self.assertEqual(dotted.status_code, 422, dotted.text)

    def test_render_checks_reference_root(self):
        from fizgig.web.engine_host import get_host
        loaded = self.client.post("/api/repair/load", json={"family": "klein", "primary": str(self.lora)})
        self.assertEqual(loaded.status_code, 200, loaded.text)
        outside = self.root / "secret.png"
        outside.write_bytes(b"x")
        host = get_host()
        before = host.latest
        denied = self.client.post("/api/repair/render", json={
            "family": "klein",
            "state": {"prompt": "a cat", "ref_image_path": str(outside)},
        })
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertEqual(host.latest, before)
        empty = self.client.post("/api/repair/render", json={
            "family": "klein", "steps": 1,
            "state": {"prompt": "a cat", "ref_image_path": ""},
        })
        self.assertEqual(empty.status_code, 200, empty.text)

    def test_gpu_free_uses_engine_device(self):
        from fizgig.gpu_lock import GpuLock
        from fizgig.web.engine_host import get_host
        from fizgig.web.refmod import _gpu_free as refmod_free
        from fizgig.web.repair import gpu_free
        from fizgig.web.royale import _gpu_free as royale_free
        host = get_host()
        host.set_device(1)
        folder = Path(os.environ["FIZGIG_WEB_JOBS"]) / "busy0"
        folder.mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({
            "id": "busy0", "status": "running", "device": 0, "created": "2020-01-01T00:00:00Z",
        }), encoding="utf-8")
        gpu_free()
        royale_free()
        refmod_free()
        lock = GpuLock(1)
        self.assertTrue(lock.acquire())
        try:
            from fizgig.web.jobs import JobError
            with self.assertRaises(JobError) as caught:
                gpu_free()
            self.assertEqual(caught.exception.status, 409)
        finally:
            lock.release()


if __name__ == "__main__":
    unittest.main()
