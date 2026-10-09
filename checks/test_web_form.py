"""GET /api/form for every described family.

    python -m unittest checks.test_web_form -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from fizgig.families.registry import FAMILIES
from fizgig.web.app import app


class WebFormTests(unittest.TestCase):
    def setUp(self):
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        self._client.__exit__(None, None, None)

    def test_form_for_every_family(self):
        for key, desc in FAMILIES.items():
            with self.subTest(family=key):
                response = self.client.get("/api/form", params={"family": key})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["family"], key)
                self.assertGreaterEqual(len(body["fields"]), 50)
                sections = [field["section"] for field in body["fields"]]
                self.assertLess(sections.index("Output"), sections.index("Training Parameters"))
                self.assertLess(sections.index("Training Parameters"), sections.index("Run"))
                covered = {flag for field in body["fields"] for flag in (field["flag"],) if flag}
                advanced_flags = {flag for item in body["advanced"] for flag in item["flags"]}
                self.assertTrue(covered.isdisjoint(advanced_flags))
                self.assertNotIn("runpod_api_key", response.text)
                self.assertTrue(desc.display_name)

    def test_unknown_family_is_404(self):
        response = self.client.get("/api/form", params={"family": "no-such-family"})
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("runpod_api_key", response.text)

    def test_optimizer_catalog_and_area_pins(self):
        from fizgig.web.form_spec import optimizer_names
        from fizgig.web.mirrors import source_hash

        names = list(optimizer_names())
        self.assertEqual(names[0], "adamw8bit")
        self.assertIn("automagic3", names)
        self.assertEqual(
            source_hash("_refresh_optimizer_choices"),
            "414afe37be41cd75642da0c5eec016ac387db29d58f622ba19a10442e044b922",
        )
        self.assertEqual(
            source_hash("_on_training_preset_changed"),
            "a405fe8e8dd99c3948ac526be7adc7c9d944242f0d2c8848eb355f297b83a842",
        )
        response = self.client.get("/api/form", params={"family": "qwen_image21"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        optimizer = next(field for field in body["fields"] if field["key"] == "OPTIMIZER_TYPE")
        self.assertEqual(optimizer["choices"], names)
        self.assertEqual(optimizer["default"], "adamw8bit")
        klein = self.client.get("/api/form", params={"family": "klein"})
        self.assertEqual(klein.status_code, 200, klein.text)
        area = next(field for field in klein.json()["fields"] if field["key"] == "FAMILY_TRAIN_AREA")
        self.assertEqual(area["windows"]["Style"], ["0", "400"])
        self.assertEqual(area["windows"]["Full Model"], ["", ""])
        self.assertNotIn("Custom", area["windows"])
        fast = body["presets"][0]["values"]
        self.assertEqual(fast["ADAPTIVE_LR_MIN"], "2e-4")
        self.assertNotIn("LORA_OUTPUT_DIR", fast)
        self.assertNotIn("LORA_NAME", fast)
        self.assertNotIn("CONTEXT_LORA_PATH", fast)
        self.assertNotIn("RESUME_TRAINING", fast)
        self.assertNotIn("METADATA_TITLE", fast)
        minimum = next(field for field in body["fields"] if field["key"] == "ADAPTIVE_LR_MIN")
        self.assertNotIn("2e-4", minimum["choices"])

    def test_preset_overlay_keeps_kind(self):
        from fizgig.families.registry import get
        from fizgig.web.form_spec import web_values

        desc = get("qwen_image21")
        _name, preset = desc.presets[0]
        values = web_values(desc, dict(preset))
        self.assertEqual(values["kind"], "Standard LoRA")
        self.assertIn("LEARNING_RATE", values)
        self.assertNotIn("LORA_OUTPUT_DIR", values)


class WebInputFillTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.prefs_path = self.root / "prefs.json"
        self.prefs_path.write_text("{}", encoding="utf-8")
        self._env = {
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
        }
        os.environ["FIZGIG_PREFS_FILE"] = str(self.prefs_path)
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_invalid_numbers_stay_raw(self):
        from fizgig.families.checks import learning_rate, numbers
        from fizgig.families.registry import get
        from fizgig.web.inputs import build

        desc = get("klein")
        bad = build(desc, {"LEARNING_RATE": "1,5e-4", "MAX_TRAIN_EPOCHS": "3O"}, {})
        self.assertEqual(bad["LEARNING_RATE"], "1,5e-4")
        self.assertEqual(bad["MAX_TRAIN_EPOCHS"], "3O")
        self.assertTrue(learning_rate(bad))
        self.assertTrue(any("3O" in item for item in numbers(bad)))
        good = build(desc, {"LEARNING_RATE": "4e-4", "MAX_TRAIN_EPOCHS": 12, "NETWORK_DIM": "4"}, {})
        self.assertAlmostEqual(good["LEARNING_RATE"], 4e-4)
        self.assertEqual(good["MAX_TRAIN_EPOCHS"], 12)
        self.assertEqual(good["NETWORK_DIM"], 4)
        self.assertFalse(learning_rate(good))

    def test_blank_context_uses_preferences(self):
        from fizgig.families.registry import get
        from fizgig.web.inputs import build

        desc = get("klein")
        key = desc.model_files[0].pref_key
        model = self.root / "model.safetensors"
        model.write_bytes(b"not-a-real-model")
        cache = self.root / "cache"
        cache.mkdir()
        captioner = self.root / "captioner.safetensors"
        captioner.write_bytes(b"fake-captioner-not-real")
        other = self.root / "other.safetensors"
        other.write_bytes(b"explicit-model")
        self.prefs_path.write_text(json.dumps({
            key: str(model),
            "cache_dir": str(cache),
            "krea2_text_encoder": str(captioner),
            "caption_qwen_instructions": {"training": "look closely"},
            "caption_qwen_instruction": "legacy custom text",
            "web_caption_trigger": "ohwx",
        }), encoding="utf-8")
        filled = build(desc, {}, {})
        self.assertEqual(filled["models"][key], str(model))
        self.assertEqual(os.path.normcase(filled["cache_root"]), os.path.normcase(str(cache)))
        self.assertEqual(filled["captioner"], str(captioner))
        self.assertEqual(filled["caption_overrides"]["training"], "look closely")
        self.assertEqual(filled["caption_overrides"]["custom"], "legacy custom text")
        self.assertEqual(filled["caption_trigger"], "ohwx")
        blank_key = build(desc, {}, {"models": {key: ""}, "cache_root": "", "captioner": ""})
        self.assertEqual(blank_key["models"][key], str(model))
        kept = build(desc, {}, {
            "models": {key: str(other)},
            "cache_root": str(self.root / "elsewhere"),
            "captioner": str(other),
            "caption_overrides": {"training": "keep"},
            "caption_trigger": "keep-word",
        })
        self.assertEqual(kept["models"][key], str(other))
        self.assertEqual(kept["cache_root"], str(self.root / "elsewhere"))
        self.assertEqual(kept["captioner"], str(other))
        self.assertEqual(kept["caption_overrides"], {"training": "keep"})
        self.assertEqual(kept["caption_trigger"], "keep-word")
        placeholder = build(desc, {}, {"caption_trigger": "trigger_word"})
        self.assertEqual(placeholder["caption_trigger"], "ohwx")
        self.prefs_path.write_text(json.dumps({
            "web_caption_trigger": "trigger_word",
            "krea2_text_encoder": str(self.root / "missing.bin"),
        }), encoding="utf-8")
        skipped = build(desc, {}, {})
        self.assertEqual(skipped["caption_trigger"], "")
        self.assertEqual(skipped["captioner"], "")


_REPO = Path(__file__).resolve().parents[1]


class WebPageSourceTests(unittest.TestCase):
    def test_page_presets_advanced_and_controls(self):
        app = (_REPO / "webui" / "src" / "App.tsx").read_text(encoding="utf-8")
        extra = (_REPO / "webui" / "src" / "extra.tsx").read_text(encoding="utf-8")
        self.assertIn("body.presets[0]", app)
        self.assertIn("mergePreset", app)
        self.assertIn("withCurrentChoice", app)
        self.assertIn("Reference only. These are not sent.", app)
        self.assertIn("disabled", app)
        self.assertIn("confirmWarnings", app)
        self.assertIn("body.detail", app)
        self.assertIn("EventSource.CLOSED", app)
        self.assertIn("2000", app)
        self.assertIn('fetch("/api/jobs")', app)
        self.assertIn("keep polling after one failed fetch", app)
        self.assertIn('loading="lazy"', app)
        self.assertIn(".slice(-48)", app)
        self.assertIn("web_caption_trigger", extra)
        self.assertIn("extraFor", extra)
        self.assertIn('offset=-1', extra)
        self.assertIn('fetch("/api/profile/engine")', extra)
        self.assertIn('status === "done"', extra)
        self.assertIn('status === "failed"', extra)
        self.assertIn('status === "running"', extra)
        self.assertIn("showNotification", extra)
        self.assertIn("keep polling after one failed fetch", extra)
        self.assertIn('fetch("/api/prefs")', app)
        repair = (_REPO / "webui" / "src" / "repair.tsx").read_text(encoding="utf-8")
        self.assertIn("draft.current", repair)
        self.assertIn("function finiteNumber", repair)
        self.assertIn("setArmed(false)", repair)
        self.assertIn("/api/repair/presets?family=", repair)
        gizmo = (_REPO / "webui" / "src" / "gizmo.tsx").read_text(encoding="utf-8")
        self.assertNotIn("attempts > 80", gizmo)
        self.assertIn("stopped", gizmo)


if __name__ == "__main__":
    unittest.main()
