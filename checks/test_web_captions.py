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
sys.path.insert(0, str(_REPO / "checks"))

from fastapi.testclient import TestClient

from fizgig.web.app import app
import runner_guard

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
        self._client.__exit__(None, None, None)
        runner_guard.end_runs(Path(os.environ["FIZGIG_WEB_JOBS"]))
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
        fields = {item["key"]: item for item in form.json()["fields"]}
        self.assertEqual(fields["max_tokens"]["default"], 120)
        self.assertIn("training caption", fields["instruction"]["default"].lower())
        self.assertEqual(fields["model"]["default"], "MiaoshouAI/Florence-2-base-PromptGen")
        self.assertNotIn("Qwen3-VL", fields["model"]["choices"])
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

    def test_defaults_follow_prefs_and_a_fail_line_ends_the_job(self):
        import json
        encoder = self.root / "encoder.safetensors"
        encoder.write_bytes(b"not a model")
        (self.root / "prefs.json").write_text(json.dumps({
            "krea2_text_encoder": str(encoder),
            "caption_qwen_instructions": {"training": "use this exact training caption"},
        }), encoding="utf-8")
        form = self.client.get("/api/captions/form").json()
        fields = {item["key"]: item for item in form["fields"]}
        self.assertEqual(fields["model"]["default"], "Qwen3-VL 4B (Krea 2 text encoder)")
        self.assertIn("Qwen3-VL 4B (Krea 2 text encoder)", fields["model"]["choices"])
        self.assertEqual(fields["instruction"]["default"], "use this exact training caption")
        self.assertEqual(fields["max_tokens"]["default"], 120)

        script = self.root / "hang_fail.py"
        script.write_text(
            "import sys\n"
            "print('READY', flush=True)\n"
            "for line in sys.stdin:\n"
            "    if line.strip().startswith('RUN'):\n"
            "        print('FAIL: boom', flush=True)\n"
            "    if line.strip() == 'QUIT':\n"
            "        break\n",
            encoding="utf-8",
        )
        os.environ["FIZGIG_WEB_FAKE_CAPTION"] = str(script)
        self.client.put("/api/start", json={"folder": str(self.dataset)})
        started = self.client.post("/api/captions/jobs", json={"trigger": "ohwx", "model": "MiaoshouAI/Florence-2-base-PromptGen"})
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        body = self._wait(lambda: (item := self.client.get(f"/api/jobs/{job_id}").json())["status"] in {"done", "failed", "stopped"} and item)
        self.assertEqual(body["status"], "failed")

    def test_per_image_fail_is_not_fatal(self):
        script = self.root / "per_image_fail.py"
        script.write_text(
            "import sys\n"
            "print('READY', flush=True)\n"
            "for line in sys.stdin:\n"
            "    text = line.strip()\n"
            "    if text.startswith('RUN'):\n"
            "        print('PROGRESS: 1 2', flush=True)\n"
            "        print('FAIL: a.png (empty caption)', flush=True)\n"
            "        print('PROGRESS: 2 2', flush=True)\n"
            "        print('OK: b.png', flush=True)\n"
            "        print('DONE', flush=True)\n"
            "    if text == 'QUIT':\n"
            "        break\n",
            encoding="utf-8",
        )
        os.environ["FIZGIG_WEB_FAKE_CAPTION"] = str(script)
        self.client.put("/api/start", json={"folder": str(self.dataset)})
        started = self.client.post("/api/captions/jobs", json={"trigger": "ohwx", "model": "MiaoshouAI/Florence-2-base-PromptGen"})
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        body = self._wait(lambda: (item := self.client.get(f"/api/jobs/{job_id}").json())["status"] in {"done", "failed", "stopped"} and item)
        self.assertEqual(body["status"], "done", body)

    def test_job_level_fail_then_done_is_failed(self):
        script = self.root / "job_fail.py"
        script.write_text(
            "import sys\n"
            "print('READY', flush=True)\n"
            "for line in sys.stdin:\n"
            "    text = line.strip()\n"
            "    if text.startswith('RUN'):\n"
            "        print('FAIL: job (boom)', flush=True)\n"
            "        print('DONE', flush=True)\n"
            "    if text == 'QUIT':\n"
            "        break\n",
            encoding="utf-8",
        )
        os.environ["FIZGIG_WEB_FAKE_CAPTION"] = str(script)
        self.client.put("/api/start", json={"folder": str(self.dataset)})
        started = self.client.post("/api/captions/jobs", json={"trigger": "ohwx", "model": "MiaoshouAI/Florence-2-base-PromptGen"})
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        body = self._wait(lambda: (item := self.client.get(f"/api/jobs/{job_id}").json())["status"] in {"done", "failed", "stopped"} and item)
        self.assertEqual(body["status"], "failed", body)

    def test_unc_folder_is_refused_with_403_on_the_caption_routes(self):
        listing = self.client.get("/api/captions", params={"folder": r"\\example-nas\share\pics"})
        self.assertEqual(listing.status_code, 403, listing.text)
        image = self.client.get(
            "/api/captions/image",
            params={"folder": r"\\example-nas\share\pics", "name": "a.png"},
        )
        self.assertEqual(image.status_code, 403, image.text)
        static = self.client.post(
            "/api/captions/static",
            json={"folder": r"\\example-nas\share\pics", "trigger": "ohwx"},
        )
        self.assertEqual(static.status_code, 403, static.text)


if __name__ == "__main__":
    unittest.main()
