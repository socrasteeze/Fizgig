"""Profiler job, report list, and the weights CLI command.

The expected command is profile_lora.py with the report path _run_profiler_family
builds. The worker is the fake script.

    python -m unittest checks.test_web_profile -v
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

from fastapi.testclient import TestClient

from fizgig.families.registry import get as get_family
from fizgig.web import jobs
from fizgig.web.app import app


class WebProfileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.output = self.root / "output"
        self.profiles = self.root / "profiles"
        self.outside = self.root / "outside"
        for folder in (self.output, self.profiles, self.outside):
            folder.mkdir()
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
            "profiles_dir": str(self.profiles),
        }), encoding="utf-8")
        self.lora = self.output / "Demo.safetensors"
        self.lora.write_bytes(b"not a model")
        self._env = {
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
            "FIZGIG_WEB_FAKE_PROFILE": os.environ.get("FIZGIG_WEB_FAKE_PROFILE"),
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_FAKE_PROFILE"] = str(_REPO / "checks" / "fake_profile.py")
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.output)
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

    def _wait(self, fn, timeout=20):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.05)
        self.fail(f"timed out; last={last!r}")

    def test_weights_command_and_report(self):
        form = self.client.get("/api/profile/form", params={"family": "klein"})
        self.assertEqual(form.status_code, 200, form.text)
        self.assertEqual(form.json()["defaults"]["mode"], "quick")
        self.assertIn("Likeness and bleed from subject photos", form.json()["gaps"])

        refused = self.client.post("/api/profile/jobs", json={"family": "klein", "lora": str(self.lora), "mode": "quick"})
        self.assertEqual(refused.status_code, 422, refused.text)

        outside = self.outside / "Other.safetensors"
        outside.write_bytes(b"not a model")
        blocked = self.client.post("/api/profile/jobs", json={"family": "klein", "lora": str(outside), "mode": "weights"})
        self.assertEqual(blocked.status_code, 403, blocked.text)

        started = self.client.post("/api/profile/jobs", json={"family": "klein", "lora": str(self.lora), "mode": "weights"})
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        suffix = get_family("klein").lora_name_suffix
        report = self.profiles.resolve() / f"Demo_{suffix}_profile.html"
        expected = [
            sys.executable, "-m", "fizgig.scripts.profile_lora",
            "--lora", str(self.lora.resolve()),
            "--family", "klein",
            "--output", str(report),
        ]
        stored = json.loads((self.root / "jobs" / job_id / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["command"], expected)

        def finished():
            body = self.client.get(f"/api/jobs/{job_id}").json()
            return body if body["status"] in {"done", "failed", "stopped"} else None

        body = self._wait(finished)
        log = (self.root / "jobs" / job_id / "log.txt").read_text(encoding="utf-8", errors="replace")
        self.assertEqual(body["status"], "done", log)
        self.assertIn("PROGRESS:", log)
        self.assertEqual(body["step"], 1)
        self.assertTrue(report.is_file())
        argv = report.with_suffix(".argv.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(argv, expected[3:])

        listed = self.client.get("/api/profiles")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["name"] for item in listed.json()["reports"]], [report.name])
        served = self.client.get("/api/profiles/file", params={"path": str(report)})
        self.assertEqual(served.status_code, 200, served.text)
        self.assertIn(b"fake profile", served.content)
        stray = self.outside / "note.html"
        stray.write_text("nope", encoding="utf-8")
        denied = self.client.get("/api/profiles/file", params={"path": str(stray)})
        self.assertEqual(denied.status_code, 403, denied.text)


class WebProfileEngineTests(unittest.TestCase):
    """Quick and Thorough on the fake engine, and the Repair Studio handoff."""

    def setUp(self):
        from fizgig.web import profile
        from fizgig.web.engine_host import shutdown
        profile._ENGINE.clear()
        shutdown()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.output = self.root / "output"
        self.profiles = self.root / "profiles"
        self.output.mkdir()
        self.profiles.mkdir()
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
            "profiles_dir": str(self.profiles),
        }), encoding="utf-8")
        self.lora = self.output / "Demo.safetensors"
        self.lora.write_bytes(b"not a model")
        self._env = {
            key: os.environ.get(key) for key in (
                "FIZGIG_WEB_JOBS", "FIZGIG_PREFS_FILE", "FIZGIG_NO_PERSIST",
                "FIZGIG_WEB_FAKE_ENGINE", "FIZGIG_WEB_FAKE_STEP", "FIZGIG_WEB_ENGINE_IDLE",
                "FIZGIG_WEB_ROOTS",
            )
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_FAKE_ENGINE"] = "1"
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.01"
        os.environ["FIZGIG_WEB_ENGINE_IDLE"] = "600"
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.output)
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        from fizgig.web.engine_host import shutdown
        shutdown()
        self._client.__exit__(None, None, None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _run(self, mode):
        started = self.client.post("/api/profile/engine", json={
            "family": "klein", "lora": str(self.lora), "mode": mode,
            "prompt": "a person", "class_prompt": "a face", "size": "512",
        })
        self.assertEqual(started.status_code, 200, started.text)
        end = time.time() + 8
        last = None
        while time.time() < end:
            last = self.client.get("/api/profile/engine").json()
            if last.get("status") == "done":
                return last
            time.sleep(0.02)
        self.fail(f"timed out; last={last!r}")

    def test_quick_and_thorough_and_repair_handoff(self):
        quick = self._run("quick")
        self.assertEqual(quick["seeds"], [1234])
        self.assertFalse(quick["per_block"])
        self.assertTrue(Path(quick["report"]).is_file())
        handoff = self.client.post("/api/profile/repair")
        self.assertEqual(handoff.status_code, 200, handoff.text)
        body = handoff.json()
        self.assertEqual(body["lora"], str(self.lora.resolve()))
        self.assertEqual(body["prompt"], "a person")
        self.assertEqual(body["seed"], 1234)
        self.assertEqual(body["size"], 512)
        self.assertIn("little effect", body["message"])
        self.assertTrue(any(row["enabled"] is False for row in body["blocks"].values()))

        thorough = self._run("thorough")
        self.assertEqual(thorough["seeds"], [1234, 5678])
        self.assertTrue(thorough["per_block"])

    def test_engine_view_stored_before_running_and_failed_when_idle(self):
        from fizgig.web import profile
        from fizgig.web.engine_host import get_host
        done = self._run("quick")
        host = get_host()
        host.busy = True
        host.result = None
        view = profile.engine_view()
        self.assertEqual(view["status"], "done")
        self.assertEqual(view["gen"], done["gen"])
        profile._ENGINE["result"] = None
        host.busy = False
        host.restarted = False
        host.profile = None
        host.result = None
        failed = profile.engine_view()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["gen"], done["gen"])
        self.assertTrue(failed.get("message"))
        host.restarted = True
        host.busy = True
        stopped = profile.engine_view()
        self.assertEqual(stopped["status"], "failed")
        self.assertIn("stopped", stopped["message"])


if __name__ == "__main__":
    unittest.main()
