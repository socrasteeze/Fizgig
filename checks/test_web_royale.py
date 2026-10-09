"""LoRA Royale: scan, epoch subset, journey seeds, ffmpeg argv, newest gen, export.

Nothing here loads a model. The export runner is the fake engine flag, so ffmpeg is not started.

    python -m unittest checks.test_web_royale -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "checks"))

from fastapi.testclient import TestClient

from fizgig.lora_royale.scan import scan_checkpoints
from fizgig.web import jobs, royale
from fizgig.web.app import app
from fizgig.web.engine_host import get_host, png, shutdown
from fizgig.web.fs import resolve_dir, resolve_file
import runner_guard


class WebRoyaleTests(unittest.TestCase):
    def setUp(self):
        shutdown()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.output = self.root / "output"
        self.output.mkdir()
        self.lora = self.output / "Demo.safetensors"
        self.lora.write_bytes(b"not a model")
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
            "profiles_dir": str(self.root / "profiles"),
        }), encoding="utf-8")
        self._env = {
            key: os.environ.get(key) for key in (
                "FIZGIG_WEB_JOBS", "FIZGIG_PREFS_FILE", "FIZGIG_NO_PERSIST",
                "FIZGIG_WEB_FAKE_ENGINE", "FIZGIG_WEB_FAKE_STEP", "FIZGIG_WEB_ENGINE_IDLE",
                "FIZGIG_WEB_FAKE_TRAINER", "FIZGIG_FAKE_STEPS", "FIZGIG_FAKE_SLEEP",
                "FIZGIG_WEB_PRESET_ROOT",
            )
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_FAKE_ENGINE"] = "1"
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.08"
        os.environ["FIZGIG_WEB_ENGINE_IDLE"] = "600"
        os.environ["FIZGIG_WEB_FAKE_TRAINER"] = str(_REPO / "checks" / "fake_trainer.py")
        os.environ["FIZGIG_FAKE_STEPS"] = "40"
        os.environ["FIZGIG_FAKE_SLEEP"] = "0.1"
        os.environ["FIZGIG_WEB_PRESET_ROOT"] = str(self.root / "presets")
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        shutdown()
        self._client.__exit__(None, None, None)
        runner_guard.end_runs(Path(os.environ["FIZGIG_WEB_JOBS"]))
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
            time.sleep(0.02)
        self.fail(f"timed out; last={last!r}")

    def test_scan_matches_checkpoints(self):
        folder = self.output / "run"
        folder.mkdir()
        for name in ("run-000001.safetensors", "run-000003.safetensors", "run-000002.safetensors"):
            (folder / name).write_bytes(b"not a model")
        resolved = str(resolve_dir(str(folder)))
        scanned = royale.scan({"folder": str(folder)})
        pairs = scan_checkpoints(resolved)
        self.assertEqual([(item["label"], item["path"]) for item in scanned["items"]], list(pairs))
        self.assertEqual([item["label"] for item in scanned["items"]], [1, 2, 3])
        (folder / "other.safetensors").write_bytes(b"not a model")
        scanned = royale.scan({"folder": str(folder)})
        pairs = scan_checkpoints(resolved)
        self.assertEqual([(item["label"], item["path"]) for item in scanned["items"]], list(pairs))
        one_path = resolve_file(str(self.lora), ".safetensors")
        one = royale.scan({"lora": str(self.lora)})
        self.assertEqual(one["items"], [{"label": one_path.stem, "path": str(one_path)}])
        missing = royale.scan({"folder": str(self.output / "no-such-folder")})
        self.assertEqual(missing["items"], [])
        with self.assertRaises(jobs.JobError) as caught:
            royale.scan({"folder": str(self.root / "no-such-folder")})
        self.assertEqual(caught.exception.status, 403)

    def test_select_epochs(self):
        items = [f"e{i}" for i in range(10)]
        n = 6
        idx = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
        self.assertEqual(royale.select_epochs(items, "6"), [items[i] for i in idx])
        self.assertEqual(len(royale.select_epochs(items, "All")), 10)
        self.assertEqual(royale.select_epochs(items, None), items)

    def test_journey_seeds(self):
        self.assertEqual(royale.journey_seeds(5, 9, 2), [5, 9])
        first = royale.journey_seeds(5, 9, 5)
        second = royale.journey_seeds(5, 9, 5)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        self.assertEqual(first[0], 5)
        self.assertEqual(first[-1], 9)

    def test_ffmpeg_command(self):
        self.assertEqual(
            royale.ffmpeg_command("ffmpeg", 513, 512, 22, "clip.mp4"),
            [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", "512x512", "-r", "22", "-i", "-", "-an", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
                "-movflags", "+faststart", "clip.mp4",
            ],
        )

    def test_newest_gen_wins(self):
        host = get_host()
        royale.load({"family": "klein", "lora": str(self.lora)})
        epochs = [{"label": 1, "path": str(self.lora)}]
        first = royale.render({
            "family": "klein", "steps": 6, "gen": 1, "prompt": "a cat",
            "epochs": epochs, "max_renders": "All",
        })
        second = royale.render({
            "family": "klein", "steps": 2, "gen": 1, "prompt": "a cat",
            "epochs": epochs, "max_renders": "All",
        })
        self.assertEqual(second["gen"], first["gen"] + 1)
        self.assertNotEqual(first["gen"], 1)
        self.assertEqual(second["status"], "running")
        seen = []
        want = second["gen"]
        self._wait(lambda: seen.extend(host.drain()) or any(
            item.get("event") == "done" and item.get("gen") == want for item in seen))
        dones = [item for item in seen if item.get("event") == "done"]
        frames = [item for item in seen if item.get("event") == "frame"]
        self.assertEqual([item["gen"] for item in dones], [want])
        self.assertTrue(frames)
        self.assertTrue(all(item["gen"] == want and item.get("side") == "epoch" for item in frames))

    def test_export_command_and_file(self):
        get_host().unload()
        image = self.output / "frame.png"
        image.write_bytes(png(4, 5, 6))
        started = royale.export({
            "images": [str(image)],
            "format": "MP4",
            "speed": "Normal",
            "pingpong": True,
            "brand": True,
            "show_epoch": True,
            "folder": str(self.output),
        })
        record_path = Path(os.environ["FIZGIG_WEB_JOBS"]) / started["id"] / "job.json"

        def record():
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            return data if data.get("command") else None

        saved = self._wait(record)
        dest = saved["values"]["dest"]
        width = saved["values"]["width"]
        height = saved["values"]["height"]
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(
            saved["command"],
            royale.ffmpeg_command(saved["command"][0], width, height, 22, dest),
        )
        self.assertTrue(str(dest).endswith("lora-royale.mp4"))

        def finished():
            body = self.client.get(f"/api/jobs/{started['id']}").json()
            if body.get("status") in {"done", "failed", "stopped"}:
                return body
            return None

        body = self._wait(finished)
        log_path = record_path.parent / "log.txt"
        detail = log_path.read_text(encoding="utf-8") if log_path.is_file() else body
        self.assertEqual(body["status"], "done", detail)
        self.assertTrue(Path(dest).is_file())
        self.assertEqual(Path(dest).read_bytes(), b"fake-mp4")
        again = royale.export({
            "images": [str(image)],
            "format": "MP4",
            "speed": "Normal",
            "folder": str(self.output),
        })
        second = json.loads((Path(os.environ["FIZGIG_WEB_JOBS"]) / again["id"] / "job.json").read_text(encoding="utf-8"))
        self.assertTrue(str(second["values"]["dest"]).endswith("lora-royale_2.mp4"))

        def second_done():
            body = self.client.get(f"/api/jobs/{again['id']}").json()
            return body if body.get("status") in {"done", "failed", "stopped"} else None

        self._wait(second_done)
        replaced = royale.export({
            "images": [str(image)],
            "format": "MP4",
            "speed": "Normal",
            "folder": str(self.output),
            "overwrite": True,
        })
        third = json.loads((Path(os.environ["FIZGIG_WEB_JOBS"]) / replaced["id"] / "job.json").read_text(encoding="utf-8"))
        self.assertTrue(str(third["values"]["dest"]).endswith("lora-royale.mp4"))

    def test_export_rejects_image_outside_roots(self):
        good = self.output / "frame.png"
        good.write_bytes(png(4, 5, 6))
        outside = self.root / "secret.png"
        outside.write_bytes(png(1, 2, 3))
        reply = self.client.post("/api/royale/export", json={"images": [str(good), str(outside)]})
        self.assertEqual(reply.status_code, 403, reply.text)
        self.assertEqual(jobs.list_jobs(), [])

    def test_export_rejects_folder_outside_roots(self):
        image = self.output / "frame.png"
        image.write_bytes(png(4, 5, 6))
        outside = self.root / "outside"
        outside.mkdir()
        reply = self.client.post("/api/royale/export", json={
            "images": [str(image)],
            "folder": str(outside),
        })
        self.assertEqual(reply.status_code, 403, reply.text)
        self.assertEqual(jobs.list_jobs(), [])

    def test_export_accepts_session_image(self):
        session = Path(os.environ["FIZGIG_WEB_JOBS"]) / "engine" / "session"
        session.mkdir(parents=True)
        image = session / "frame.png"
        image.write_bytes(png(4, 5, 6))
        reply = self.client.post("/api/royale/export", json={
            "images": [str(image)],
            "format": "MP4",
            "speed": "Normal",
        })
        self.assertEqual(reply.status_code, 200, reply.text)
        body = reply.json()
        self.assertTrue(body.get("id"))
        self.assertIn(body.get("status"), {"queued", "running", "done"})
        saved = jobs.list_jobs()
        self.assertEqual([item["id"] for item in saved], [body["id"]])
        record = json.loads((Path(os.environ["FIZGIG_WEB_JOBS"]) / body["id"] / "job.json").read_text(encoding="utf-8"))
        self.assertTrue(str(record["values"]["images"][0]).startswith(str(session.resolve())))

    def test_render_rejects_epoch_outside_roots(self):
        outside = self.root / "other.safetensors"
        outside.write_bytes(b"not a model")
        with self.assertRaises(jobs.JobError) as caught:
            royale.render({"epochs": [{"label": 1, "path": str(outside)}]})
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(get_host().latest, 0)
        self.assertEqual(jobs.list_jobs(), [])

    def test_render_rejects_reference_outside_roots(self):
        outside = self.root / "secret.png"
        outside.write_bytes(png(1, 2, 3))
        with self.assertRaises(jobs.JobError) as caught:
            royale.render({
                "epochs": [{"label": 1, "path": str(self.lora)}],
                "reference": str(outside),
            })
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(get_host().latest, 0)

    def test_render_accepts_reference_inside_roots(self):
        image = self.output / "ref.png"
        image.write_bytes(png(1, 2, 3))
        royale.load({"family": "klein", "lora": str(self.lora)})
        started = royale.render({
            "epochs": [{"label": 1, "path": str(self.lora)}],
            "reference": str(image),
            "steps": 1,
        })
        self.assertEqual(started["status"], "running")
        self.assertGreater(started["gen"], 0)

    def test_travel_rejects_reference_outside_roots(self):
        outside = self.root / "secret.png"
        outside.write_bytes(png(1, 2, 3))
        with self.assertRaises(jobs.JobError) as caught:
            royale.travel({"mode": "seed", "path": str(self.lora), "reference": str(outside)})
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(get_host().latest, 0)

    def test_load_rejects_folder_outside_roots(self):
        outside = self.root / "outside"
        outside.mkdir()
        with self.assertRaises(jobs.JobError) as caught:
            royale.load({"family": "klein", "folder": str(outside)})
        self.assertEqual(caught.exception.status, 403)
        self.assertFalse(get_host().loaded)

    def test_load_does_not_forward_a_file_as_folder(self):
        stray = self.output / "notes.txt"
        stray.write_text("x", encoding="utf-8")
        royale.load({"family": "klein", "folder": str(stray)})
        args = get_host().args
        self.assertNotIn("folder", args)
        self.assertNotIn(str(stray), list(args.values()))

    def test_scan_refuses_an_unc_folder_before_any_stat(self):
        touched = []
        real = Path.is_dir

        def spy(path):
            touched.append(os.fspath(path))
            return real(path)

        with patch.object(Path, "is_dir", spy):
            response = self.client.post("/api/royale/scan", json={"folder": r"\\example-nas\share\pics"})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual([item for item in touched if item.startswith("\\\\")], [])


if __name__ == "__main__":
    unittest.main()
