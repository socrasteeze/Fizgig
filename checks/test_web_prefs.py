"""Preferences never return or overwrite a secret.

    python -m unittest checks.test_web_prefs -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.web.app import app

_SECRET = "zz-secret-value-zz"
_TOKEN = "zz-token-value-zz"


class WebPrefsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.prefs = self.root / "prefs.json"
        self.prefs.write_text(json.dumps({
            "runpod_api_key": _SECRET,
            "custom_token": _TOKEN,
            "base_dit": "D:/models/a.safetensors",
            "cache_dir": "cache",
        }), encoding="utf-8")
        self._env = {
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
        }
        os.environ["FIZGIG_PREFS_FILE"] = str(self.prefs)
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
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

    def test_secrets_stay_out_of_the_response_and_the_file(self):
        response = self.client.get("/api/prefs")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(_SECRET, response.text)
        self.assertNotIn(_TOKEN, response.text)
        body = response.json()
        flags = {item["key"]: item["set"] for item in body["secrets"]}
        self.assertTrue(flags["runpod_api_key"])
        self.assertTrue(flags["custom_token"])
        self.assertNotIn("value", body["secrets"][0])
        keys = {item["key"] for section in body["families"] for item in section["files"]}
        self.assertIn("base_dit", keys)
        self.assertTrue(any(item["key"] == "cache_dir" for item in body["directories"]))

        saved = self.client.put("/api/prefs", json={"values": {
            "runpod_api_key": "replaced",
            "custom_token": "replaced",
            "base_dit": "D:/models/b.safetensors",
            "cache_dir": str(_REPO / "cache" / "phase2-pref"),
        }})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertNotIn(_SECRET, saved.text)
        self.assertNotIn("replaced", saved.text)
        on_disk = json.loads(self.prefs.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["runpod_api_key"], _SECRET)
        self.assertEqual(on_disk["custom_token"], _TOKEN)
        self.assertEqual(on_disk["base_dit"], "D:/models/b.safetensors")
        self.assertEqual(on_disk["cache_dir"], "cache/phase2-pref")

    def test_corrupt_prefs_are_not_replaced(self):
        self.prefs.write_bytes(b"\xff\xfe not json {")
        viewed = self.client.get("/api/prefs")
        self.assertEqual(viewed.status_code, 200, viewed.text)
        listed = self.client.get("/api/fs")
        self.assertEqual(listed.status_code, 200, listed.text)
        saved = self.client.put("/api/prefs", json={"values": {"web_caption_trigger": "ohwx", "cache_dir": "cache"}})
        self.assertEqual(saved.status_code, 409, saved.text)
        self.assertEqual(self.prefs.read_bytes(), b"\xff\xfe not json {")

    def test_caption_trigger_is_saved_and_other_keys_stay(self):
        saved = self.client.put("/api/prefs", json={"values": {"web_caption_trigger": "ohwx"}})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertNotIn(_SECRET, saved.text)
        on_disk = json.loads(self.prefs.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["web_caption_trigger"], "ohwx")
        self.assertEqual(on_disk["runpod_api_key"], _SECRET)
        self.assertEqual(on_disk["custom_token"], _TOKEN)
        self.assertEqual(on_disk["base_dit"], "D:/models/a.safetensors")

    def test_caption_trigger_reads_back_and_fills_a_blank_launch(self):
        from fizgig.families.registry import get as get_family
        from fizgig.web.inputs import build

        saved = self.client.put("/api/prefs", json={"values": {"web_caption_trigger": "ohwx"}})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get("/api/prefs").json()["web_caption_trigger"], "ohwx")
        self.assertEqual(build(get_family("klein"), {}, {"caption_trigger": ""})["caption_trigger"], "ohwx")


if __name__ == "__main__":
    unittest.main()
