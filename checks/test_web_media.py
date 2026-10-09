"""HTTP Range for one clip, and a path outside the roots.

    python -m unittest checks.test_web_media -v
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

from fizgig.web import jobs
from fizgig.web.app import app


class WebMediaTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
        }), encoding="utf-8")
        self.payload = bytes(range(32))
        self.clip = self.root / "clip.mp4"
        self.clip.write_bytes(self.payload)
        self._env = {
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.root)
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

    def test_range_and_outside(self):
        served = self.client.get(
            "/api/gizmo/media",
            params={"path": str(self.clip)},
            headers={"Range": "bytes=0-3"},
        )
        self.assertEqual(served.status_code, 206, served.text)
        self.assertEqual(served.headers["content-range"], f"bytes 0-3/{len(self.payload)}")
        self.assertEqual(len(served.content), 4)
        self.assertEqual(served.content, self.payload[:4])

        with tempfile.TemporaryDirectory() as outside:
            stray = Path(outside) / "clip.mp4"
            stray.write_bytes(self.payload)
            denied = self.client.get("/api/gizmo/media", params={"path": str(stray)})
            self.assertEqual(denied.status_code, 403, denied.text)

        unc = self.client.get("/api/gizmo/media", params={"path": "//no-such/share/clip.mp4"})
        self.assertEqual(unc.status_code, 403, unc.text)


if __name__ == "__main__":
    unittest.main()
