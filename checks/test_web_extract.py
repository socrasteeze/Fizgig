"""Extract job and the extract_lora.py command for the same choices.

Preset and Custom blocks follow _run_extract. The worker is the fake script.

    python -m unittest checks.test_web_extract -v
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
from fizgig.web.extract import suggested_name
import runner_guard


class WebExtractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
        }), encoding="utf-8")
        self.source = self.output / "Photo.safetensors"
        self.source.write_bytes(b"not a model")
        self._env = {
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
            "FIZGIG_WEB_FAKE_EXTRACT": os.environ.get("FIZGIG_WEB_FAKE_EXTRACT"),
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_FAKE_EXTRACT"] = str(_REPO / "checks" / "fake_extract.py")
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.output)
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
            last = self.client.post("/api/extract/jobs", json=payload)
            if last.status_code != 409:
                return last
            time.sleep(0.05)
        return last

    def test_preset_custom_and_collision(self):
        form = self.client.get("/api/extract/form", params={"family": "klein"})
        self.assertEqual(form.status_code, 200, form.text)
        body = form.json()
        self.assertIn("Identity", body["presets"])
        self.assertIn("Custom", body["presets"])
        self.assertTrue(body["groups"])
        self.assertEqual(suggested_name(str(self.source), "Identity", "8"), "Photo_identity_r8.safetensors")
        self.assertEqual(suggested_name(str(self.source), "Style+Composition", "4"), "Photo_style_composition_r4.safetensors")

        empty = self.client.post("/api/extract/jobs", json={
            "family": "klein", "source": str(self.source), "preset": "Custom", "blocks": [], "rank": "4",
        })
        self.assertEqual(empty.status_code, 422, empty.text)
        self.assertIn("no blocks are ticked", empty.text)

        output = self.output.resolve() / "Photo_identity_r8.safetensors"
        started = self._post({
            "family": "klein",
            "source": str(self.source),
            "preset": "Identity",
            "rank": "8",
            "output_name": "Photo_identity_r8.safetensors",
        })
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        expected = [
            sys.executable, "-m", "fizgig.scripts.extract_lora",
            "--family", "klein",
            "--source", str(self.source.resolve()),
            "--output", str(output),
            "--rank", "8",
            "--preset", "Identity",
        ]
        self.assertEqual(self._command(job_id), expected)
        done = self._wait(job_id)
        self.assertEqual(done["status"], "done", (self.root / "jobs" / job_id / "log.txt").read_text(encoding="utf-8", errors="replace"))
        argv = output.with_suffix(".argv.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(argv, expected[3:])
        self.assertNotIn("--blocks", expected)

        again = self._post({
            "family": "klein",
            "source": str(self.source),
            "preset": "Identity",
            "rank": "8",
            "output_name": "Photo_identity_r8.safetensors",
        })
        self.assertEqual(again.status_code, 200, again.text)
        second = self._command(again.json()["id"])
        self.assertTrue(second[second.index("--output") + 1].endswith("Photo_identity_r8_2.safetensors"))
        self._wait(again.json()["id"])

        ids = [body["groups"][0]["blocks"][0]["id"], body["groups"][1]["blocks"][0]["id"]]
        custom = self._post({
            "family": "klein",
            "source": str(self.source),
            "preset": "Custom",
            "blocks": ids,
            "rank": "4",
            "output_name": "custom_out.safetensors",
        })
        self.assertEqual(custom.status_code, 200, custom.text)
        command = self._command(custom.json()["id"])
        self.assertEqual(command[command.index("--blocks") + 1], ",".join(ids))
        self.assertNotIn("--preset", command)
        self._wait(custom.json()["id"])


if __name__ == "__main__":
    unittest.main()
