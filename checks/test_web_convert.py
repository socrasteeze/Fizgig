"""Checkpoint-to-LoRA job and the convert command for the same choices.

Ranks follow the desktop order. The worker is the fake script.

    python -m unittest checks.test_web_convert -v
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
sys.path.insert(0, str(_REPO / "checks"))

from fastapi.testclient import TestClient

from fizgig.web.app import app
import runner_guard


class WebConvertTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
        }), encoding="utf-8")
        self.base = self.root / "base.safetensors"
        self.tuned = self.root / "tuned.safetensors"
        self.base.write_bytes(b"base")
        self.tuned.write_bytes(b"tuned")
        self._env = {
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
            "FIZGIG_WEB_FAKE_CONVERT": os.environ.get("FIZGIG_WEB_FAKE_CONVERT"),
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_FAKE_CONVERT"] = str(_REPO / "checks" / "fake_convert.py")
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.root)
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        self._client.__exit__(None, None, None)
        runner_guard.end_runs(Path(os.environ["FIZGIG_WEB_JOBS"]))
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _wait(self, job_id):
        end = time.time() + 20
        last = None
        while time.time() < end:
            last = self.client.get(f"/api/jobs/{job_id}").json()
            if last["status"] in {"done", "failed", "stopped"}:
                return last
            time.sleep(0.05)
        self.fail(f"timed out; last={last!r}")

    def _command(self, job_id):
        return json.loads((self.root / "jobs" / job_id / "job.json").read_text(encoding="utf-8"))["command"]

    def _post(self, payload):
        end = time.time() + 10
        last = None
        while time.time() < end:
            last = self.client.post("/api/convert/jobs", json=payload)
            if last.status_code != 409:
                return last
            time.sleep(0.05)
        return last

    def test_form(self):
        form = self.client.get("/api/convert/form")
        self.assertEqual(form.status_code, 200, form.text)
        body = form.json()
        self.assertEqual(body["ranks"], [8, 16, 32, 64, 128, 256])
        self.assertEqual(body["default_ranks"], [32, 64])
        self.assertEqual(body["name"], "extracted")
        self.assertEqual(body["output_dir"], str(self.output.resolve()))

    def test_job_uses_desktop_rank_order(self):
        started = self._post({
            "base": str(self.base),
            "tuned": str(self.tuned),
            "ranks": [64, 32],
            "name": "extracted",
        })
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        done = self._wait(job_id)
        log_path = self.root / "jobs" / job_id / "log.txt"
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        self.assertEqual(done["status"], "done", log)
        command = self._command(job_id)
        expected = [
            sys.executable, str(_REPO / "checks" / "fake_convert.py"),
            "--base", str(self.base.resolve()),
            "--tuned", str(self.tuned.resolve()),
            "--output", str(self.output.resolve()),
            "--name", "extracted",
            "--ranks", "32,64",
        ]
        self.assertEqual(command, expected)
        # _work(base, tuned, out, ranks, name) passes these to extract_diff_loras.
        # Read them from the argv. Do not call extract_diff_loras.
        flags = command[2:]
        values = dict(zip(flags[0::2], flags[1::2]))
        self.assertEqual(values["--base"], str(self.base.resolve()))
        self.assertEqual(values["--tuned"], str(self.tuned.resolve()))
        self.assertEqual(values["--output"], str(self.output.resolve()))
        self.assertEqual(values["--name"], "extracted")
        self.assertEqual([int(part) for part in values["--ranks"].split(",")], [32, 64])
        folder = Path(values["--output"])
        for rank in (32, 64):
            placeholder = folder / f"extracted_fake_r{rank}.safetensors"
            self.assertEqual(placeholder.read_bytes(), b"fake")

    def test_same_path_no_ranks_and_outside(self):
        same = self.client.post("/api/convert/jobs", json={
            "base": str(self.base),
            "tuned": str(self.base),
            "ranks": [32],
            "name": "extracted",
        })
        self.assertEqual(same.status_code, 422, same.text)
        self.assertIn("same", same.text.lower())

        empty = self.client.post("/api/convert/jobs", json={
            "base": str(self.base),
            "tuned": str(self.tuned),
            "ranks": [],
            "name": "extracted",
        })
        self.assertEqual(empty.status_code, 422, empty.text)

        with tempfile.TemporaryDirectory() as outside:
            other = Path(outside) / "other.safetensors"
            other.write_bytes(b"outside")
            denied = self.client.post("/api/convert/jobs", json={
                "base": str(other),
                "tuned": str(self.tuned),
                "ranks": [32],
                "name": "extracted",
            })
            self.assertEqual(denied.status_code, 403, denied.text)

    def test_output_name_cannot_escape(self):
        for name in ("C:extracted", "a<b", "quote\"x", "star*"):
            denied = self.client.post("/api/convert/jobs", json={
                "base": str(self.base),
                "tuned": str(self.tuned),
                "ranks": [32],
                "name": name,
            })
            self.assertEqual(denied.status_code, 422, denied.text)
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
