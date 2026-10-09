"""Model Area timestep refill (review finding 22) and the read-only Advanced section (finding 23).

    python -m unittest checks.test_web_form_more -v
"""
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fizgig.families.registry import get as get_family
from fizgig.web import form_spec
from fizgig.web.app import advanced_options
from fizgig.web.inputs import build


class WebFormMoreTests(unittest.TestCase):
    def test_model_area_carries_the_desktop_timestep_window(self):
        # Desktop _on_training_preset_changed: a Model Area with a timestep span fills MIN/MAX from it
        # (0-1000), an area without one clears both boxes, and Custom leaves them alone.
        desc = get_family("klein")
        fields = {field.key: field for field in form_spec.fields_for(desc)}
        area = fields["FAMILY_TRAIN_AREA"]
        expected = {}
        for name, _blocks, span in desc.train_areas:
            expected[name] = [str(round(span[0] * 1000)), str(round(span[1] * 1000))] if span else ["", ""]
        self.assertEqual(area.windows, expected)
        self.assertEqual(area.windows["Style"], ["0", "400"])
        self.assertEqual(area.windows["Full Model"], ["", ""])
        self.assertNotIn("Custom", area.windows)

        served = {field["key"]: field for field in form_spec.form_for(desc, [])["fields"]}
        self.assertEqual(served["FAMILY_TRAIN_AREA"]["windows"], expected)
        self.assertIn("MIN_TIMESTEP", served)
        self.assertIn("MAX_TIMESTEP", served)

    def test_advanced_section_is_reference_only_and_never_reaches_the_launch(self):
        # The Advanced section says "Reference only. These are not sent." The server keeps it that way:
        # no entry carries a launch key, and build() ignores a value posted under the option's dest.
        desc = get_family("klein")
        advanced = form_spec.form_for(desc, advanced_options())["advanced"]
        self.assertTrue(advanced)
        sentinel = "fake-advanced-sentinel"
        for item in advanced:
            self.assertNotIn("plan", item, item)
            self.assertNotIn("key", item, item)
            dest = str(item.get("dest") or "")
            if not dest:
                continue
            inputs = build(desc, {dest: sentinel}, {})
            self.assertNotIn(sentinel, repr(inputs), dest)


if __name__ == "__main__":
    unittest.main()
