"""Start-tab folder summary.

    python -m unittest checks.test_web_start -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.web.app import app

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class WebStartTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dataset = self.root / "dataset"
        self.dataset.mkdir()
        for name in ("a.png", "b.png", "c.png"):
            (self.dataset / name).write_bytes(_PNG)
        (self.dataset / "a.txt").write_text("one", encoding="utf-8")
        (self.dataset / "b.txt").write_text("two", encoding="utf-8")
        self._env = {
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
        }
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.dataset)
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
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

    def test_counts(self):
        saved = self.client.put("/api/start", json={"folder": str(self.dataset)})
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(body["images"], 3)
        self.assertEqual(body["captions"], 2)
        self.assertEqual(body["missing"], 1)
        self.assertTrue(body["ready"])
        again = self.client.get("/api/start").json()
        self.assertEqual(again["images"], 3)
        self.assertEqual(again["missing"], 1)
        refused = self.client.put("/api/start", json={"folder": str(self.root / "missing")})
        self.assertEqual(refused.status_code, 403)


if __name__ == "__main__":
    unittest.main()
