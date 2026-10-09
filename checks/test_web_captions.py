"""Caption job, editor, and static captions. The worker is the fake protocol server.

    python -m unittest checks.test_web_captions -v
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.web import jobs
from fizgig.web.app import app

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class WebCaptionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dataset = self.root / "dataset"
        self.dataset.mkdir()
        (self.dataset / "a.png").write_bytes(_PNG)
        (self.dataset / "b.png").write_bytes(_PNG)
        self._env = {
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_WEB_FAKE_CAPTION": os.environ.get("FIZGIG_WEB_FAKE_CAPTION"),
        }
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.dataset)
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_WEB_FAKE_CAPTION"] = str(_REPO / "checks" / "fake_caption.py")
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
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

    def _wait(self, fn, timeout=15):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.05)
        self.fail(f"timed out; last={last!r}")

    def test_job_edit_and_static(self):
        form = self.client.get("/api/captions/form")
        self.assertEqual(form.status_code, 200, form.text)
        self.assertIn("Whisper", form.json()["gaps"])
        saved = self.client.put("/api/start", json={"folder": str(self.dataset)})
        self.assertEqual(saved.status_code, 200, saved.text)
        started = self.client.post("/api/captions/jobs", json={"trigger": "ohwx", "overwrite": True})
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]

        def finished():
            body = self.client.get(f"/api/jobs/{job_id}").json()
            return body if body["status"] in {"done", "failed", "stopped"} else None

        body = self._wait(finished)
        self.assertEqual(body["status"], "done", (self.root / "jobs" / job_id / "log.txt").read_text(encoding="utf-8", errors="replace") if (self.root / "jobs" / job_id / "log.txt").is_file() else body)
        self.assertEqual((self.dataset / "a.txt").read_text(encoding="utf-8"), "ohwx, fake caption")
        log = (self.root / "jobs" / job_id / "log.txt").read_text(encoding="utf-8")
        self.assertIn("PROGRESS:", log)
        self.assertIn("OK:", log)

        edited = self.client.put("/api/captions", json={"folder": str(self.dataset), "name": "a.png", "text": "a red hat"})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual((self.dataset / "a.txt").read_text(encoding="utf-8"), "a red hat")
        found = self.client.get("/api/captions", params={"folder": str(self.dataset), "q": "red hat"})
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual([item["name"] for item in found.json()["items"]], ["a.png"])
        image = self.client.get("/api/captions/image", params={"folder": str(self.dataset), "name": "a.png"})
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content, _PNG)

        (self.dataset / "c.png").write_bytes(_PNG)
        static = self.client.post("/api/captions/static", json={"trigger": "still", "overwrite": False})
        self.assertEqual(static.status_code, 200, static.text)
        self.assertEqual((self.dataset / "c.txt").read_text(encoding="utf-8"), "still")
        self.assertEqual((self.dataset / "a.txt").read_text(encoding="utf-8"), "a red hat")

        removed = self.client.delete(f"/api/jobs/{job_id}")
        self.assertEqual(removed.status_code, 204, removed.text)
        self.assertTrue((self.dataset / "a.txt").is_file())


if __name__ == "__main__":
    unittest.main()
