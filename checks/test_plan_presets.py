"""Every built-in preset of every model plans a run with no problems: the form's defaults, the preset applied as the
page applies it, a model file for every Preferences key, and the folders each kind of run asks for. No GPU and no
real model files; catches a preset or plan an upstream sync breaks.

    python -m unittest discover -s checks -p "test_plan_presets.py" -v
"""
import os
import unittest

import isolate
from fizgig.families import form
from fizgig.families.registry import training_families
from fizgig.web import server

_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


def _photos(folder, captions=True):
    os.makedirs(folder, exist_ok=True)
    for i in range(3):
        with open(os.path.join(folder, f"p{i}.png"), "wb") as f:
            f.write(_PNG)
        if captions:
            with open(os.path.join(folder, f"p{i}.txt"), "w", encoding="utf-8") as f:
                f.write("a photo")
    return folder


class PlanEveryPreset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.path.join(isolate.ROOT, "plan_presets")
        cls.families = list(training_families())
        models = {}
        for desc in cls.families:
            for key in form.model_keys(desc):
                path = os.path.join(root, "models", key + ".safetensors")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(b"\0" * 16)
                models[key] = path
        isolate.write_prefs(**models)
        cls.folder = _photos(os.path.join(root, "photos"))
        # what an Edit or a Slider run asks for besides its presets: the originals, the -1 end, the prompts
        cls.kind_inputs = {"FAMILY_EDIT_DIR": _photos(os.path.join(root, "originals"), captions=False),
                           "FAMILY_SLIDER_DIR": _photos(os.path.join(root, "minus"), captions=False),
                           "FAMILY_SLIDER_BASE": "a photo of a person", "FAMILY_SLIDER_POS": "smiling",
                           "FAMILY_SLIDER_NEG": "frowning"}

    @classmethod
    def tearDownClass(cls):
        isolate.write_prefs()

    def test_families_have_presets(self):
        self.assertTrue(self.families)
        for desc in self.families:
            self.assertTrue(desc.presets, desc.key)

    def test_every_preset_plans(self):
        for desc in self.families:
            rows = [r for sec in form.form(desc)["sections"] for r in sec["rows"] if r]
            defaults = {r["key"]: r["default"] for r in rows}
            for name, preset in desc.presets:
                with self.subTest(family=desc.key, preset=name):
                    values = form.apply_preset(desc, {**defaults, **self.kind_inputs}, preset)
                    _desc, _inputs, plan = server._plan(desc.key, values, self.folder)
                    self.assertEqual(plan.problems, [])
                    self.assertTrue(plan.stages)


if __name__ == "__main__":
    unittest.main()
