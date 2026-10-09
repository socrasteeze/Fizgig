"""Samples form round-trip into the launch dict and the queue.

    python -m unittest checks.test_web_samples -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.families.registry import get as get_family
from fizgig.web.app import app
from fizgig.web.inputs import build
from fizgig.web.samples import pack, resolutions


class WebSampleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = {
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        self._client.__exit__(None, None, None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_form_round_trip_and_queue(self):
        klein = self.client.get("/api/samples/form", params={"family": "klein"})
        self.assertEqual(klein.status_code, 200, klein.text)
        self.assertIn("Distilled 4-step", klein.json()["wording"]["banner"])
        self.assertEqual(klein.json()["resolutions"], resolutions())
        steps = next(field for field in klein.json()["fields"] if field["key"] == "steps")
        self.assertEqual(steps["disabled_when"], "checkpoint")

        minimax = self.client.get("/api/samples/form", params={"family": "minimax"})
        self.assertEqual(minimax.status_code, 200, minimax.text)
        self.assertIn("short clips", minimax.json()["wording"]["banner"])
        self.assertTrue(any(field["key"] == "FAMILY_TURBO_PACE" for field in minimax.json()["fields"]))

        sdxl = self.client.get("/api/samples/form", params={"family": "sdxl"})
        self.assertEqual(sdxl.status_code, 200, sdxl.text)
        steps = next(field for field in sdxl.json()["fields"] if field["key"] == "steps")
        self.assertIn("DPM++", steps["help"])
        width = next(field for field in sdxl.json()["fields"] if field["key"] == "width")
        self.assertEqual(width["choices"], resolutions())

        missing = self.client.get("/api/samples/form", params={"family": "no-such-family"})
        self.assertEqual(missing.status_code, 404, missing.text)

        values = {field["key"]: field["default"] for field in sdxl.json()["fields"]}
        values["prompts"] = "a red chair in an empty room\na blue cup on a table"
        values["width"] = "1280"
        values["height"] = "640"
        values["every"] = "3"
        values["seed"] = "4242"
        values["at_first"] = False
        packed = pack(values)
        self.assertEqual(packed["samples"]["prompts"], ["a red chair in an empty room", "a blue cup on a table"])
        self.assertEqual(packed["samples"]["width"], "1280")
        self.assertEqual(packed["samples"]["every"], "3")
        self.assertFalse(packed["samples"]["at_first"])

        desc = get_family("sdxl")
        built = build(desc, {"image_folder": "dataset"}, packed)
        self.assertEqual(built["samples"]["seed"], "4242")
        self.assertEqual(built["samples"]["height"], "640")
        self.assertEqual(built["samples"]["steps"], str(values["steps"]))

        posted = self.client.post("/api/queue", json={
            "family": "sdxl",
            "values": {"image_folder": "dataset"},
            "context": packed,
        })
        self.assertEqual(posted.status_code, 200, posted.text)
        self.assertEqual(posted.json()["context"]["samples"]["prompts"][1], "a blue cup on a table")
        self.assertEqual(posted.json()["context"]["samples"]["seed"], "4242")

        text = build(desc, {}, {"samples": {"prompts": "one\ntwo"}})
        self.assertEqual(text["samples"]["prompts"], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
