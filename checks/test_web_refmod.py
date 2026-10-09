"""RefMod Studio presets, scan, and a fake render.

Nothing here loads a model or touches CUDA.

    python -m unittest checks.test_web_refmod -v
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

from fizgig.web.engine_host import get_host, shutdown
from fizgig.web.jobs import JobError
from fizgig.web.refmod import load, read_preset, render, save_preset, scan


class WebRefmodTests(unittest.TestCase):
    def setUp(self):
        shutdown()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.images = self.root / "images"
        self.images.mkdir()
        self.mods = self.output / "mods"
        self.mods.mkdir()
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

    def tearDown(self):
        shutdown()
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _wait(self, fn, timeout=12):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.02)
        self.fail(f"timed out; last={last!r}")

    def _body(self):
        return {
            "name": "window",
            "base": "Auto (by free VRAM)",
            "model": "Reference (ref2va)",
            "prompt": "a woman smiles at the camera, soft window light",
            "seed": "300",
            "frames": "22 frames (~1s)",
            "width": "640",
            "height": "768",
            "steps": "4",
            "turbo": "1.0",
            "sound": True,
            "early": True,
            "folder": str(self.mods),
            "rows": [{"on": True, "mod": "smile", "value": 1.2345, "copies": 2}],
            "retention": 1.0,
            "scramble": "-1",
            "frame_curve": ["concept_at_start", "ease", 1.0],
            "step_curve": ["concept_at_start", "ease", 1.0],
            "step_on": False,
            "numbered": False,
            "lora": "",
            "compare": "No mod (LoRA alone)",
        }

    def test_preset_round_trip(self):
        body = self._body()
        save_preset(body)
        path = Path(os.environ["FIZGIG_WEB_PRESET_ROOT"]) / "refmod_studio" / "window.json"
        self.assertTrue(path.is_file())
        expected = self._body()
        expected.pop("name")
        expected["rows"] = [{"on": True, "mod": "smile", "value": 1.235, "copies": 2}]
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded, expected)
        self.assertEqual(read_preset("window"), expected)
        self.assertEqual(loaded["rows"][0]["value"], 1.235)

    def test_render_early_frame(self):
        load({})
        render({
            "steps": 3,
            "early": True,
            "seed": "300",
            "prompt": "a woman smiles at the camera, soft window light",
            "compare": "No mod (LoRA alone)",
            "rows": [],
        })
        host = get_host()
        seen = []
        self._wait(lambda: seen.extend(host.drain()) or any(item.get("event") == "done" for item in seen))
        done = [item for item in seen if item.get("event") == "done"]
        frames = [item for item in seen if item.get("event") == "frame"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["records"]["early_step"], 2)
        self.assertTrue(frames)
        self.assertTrue(any(item.get("side") == "early" for item in frames))
        engine = self.root / "jobs" / "engine"
        for key in ("baseline", "image"):
            path = Path(done[0][key])
            self.assertTrue(path.is_file(), key)
            self.assertTrue(str(path).startswith(str(engine)), path)

    def test_newest_gen_wins(self):
        load({})
        first = render({"steps": 6, "gen": 1, "early": False})
        second = render({"steps": 2, "gen": 2, "early": False})
        self.assertEqual((first["gen"], second["gen"]), (1, 2))
        host = get_host()
        seen = []
        self._wait(lambda: seen.extend(host.drain()) or any(
            item.get("event") == "done" and item.get("gen") == 2 for item in seen))
        dones = [item for item in seen if item.get("event") == "done"]
        frames = [item for item in seen if item.get("event") == "frame"]
        self.assertEqual([item["gen"] for item in dones], [2])
        self.assertTrue(all(item["gen"] == 2 for item in frames))

    def test_scan_empty_folder(self):
        name = "fizgig.minimax.refmod_apply"
        had = name in sys.modules
        self.assertEqual(scan({"folder": str(self.mods)}), {"mods": []})
        if not had:
            self.assertNotIn(name, sys.modules)

    def test_scan_rejects_folder_outside_roots(self):
        name = "fizgig.minimax.refmod_apply"
        had = name in sys.modules
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "notes.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(JobError) as caught:
            scan({"folder": str(outside)})
        self.assertEqual(caught.exception.status, 403)
        if not had:
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
