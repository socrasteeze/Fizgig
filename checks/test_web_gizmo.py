"""Gizmo cut, scene chop, voice caption, recording, and Whisper argv.

The desktop builders are loaded from gizmo.py without importing it (that
import starts Tk). ffmpeg is not started except one skipped-if-missing export.

    python -m unittest checks.test_web_gizmo -v
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.web import gizmo as web_gizmo
from fizgig.web import jobs
from fizgig.web.app import app


def desktop(*names):
    """Exec the named assigns and functions from gizmo.py. No Tk import."""
    wanted = set(names)
    tree = ast.parse((_REPO / "gizmo.py").read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            ids = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name in wanted for name in ids):
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"os": os, "re": re}
    exec(compile(module, "gizmo.py", "exec"), ns)
    return ns


class WebGizmoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "dataset"
        self.output.mkdir()
        (self.root / "prefs.json").write_text("{}", encoding="utf-8")
        self.source = self.output / "walk.mp4"
        self.source.write_bytes(b"not a video")
        keys = (
            "FIZGIG_WEB_JOBS", "FIZGIG_PREFS_FILE", "FIZGIG_NO_PERSIST",
            "FIZGIG_WEB_ROOTS", "FIZGIG_WEB_FAKE_FFMPEG", "FIZGIG_WEB_FAKE_WHISPER",
            "FIZGIG_WEB_FAKE_SCENES", "FIZGIG_WEB_UPLOAD_MAX",
        )
        self._env = {key: os.environ.get(key) for key in keys}
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.output)
        os.environ["FIZGIG_WEB_FAKE_FFMPEG"] = "1"
        os.environ["FIZGIG_WEB_FAKE_WHISPER"] = str(_REPO / "checks" / "fake_whisper.py")
        os.environ.pop("FIZGIG_WEB_FAKE_SCENES", None)
        os.environ.pop("FIZGIG_WEB_UPLOAD_MAX", None)
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

    def _wait(self, job_id):
        end = time.time() + 20
        last = None
        while time.time() < end:
            last = self.client.get(f"/api/jobs/{job_id}").json()
            if last["status"] in {"done", "failed", "stopped"}:
                return last
            time.sleep(0.05)
        self.fail(f"timed out; last={last!r}")

    def _post(self, path, payload):
        end = time.time() + 10
        last = None
        while time.time() < end:
            last = self.client.post(path, json=payload)
            if last.status_code != 409:
                return last
            time.sleep(0.05)
        return last

    def _stored(self, job_id):
        return json.loads((self.root / "jobs" / job_id / "job.json").read_text(encoding="utf-8"))

    def test_cut_argv_matches_desktop(self):
        ns = desktop(
            "FPS", "AUDIO_SAMPLE_RATE", "AUDIO_CHANNELS", "MUTE_SUFFIX",
            "find_ffmpeg", "build_export_command", "output_name",
        )
        source = str(self.source.resolve())
        dataset = str(self.output.resolve())
        self.assertEqual(web_gizmo.output_name(source, dataset, False), ns["output_name"](source, dataset, False))
        muted = ns["output_name"](source, dataset, True)
        self.assertEqual(web_gizmo.output_name(source, dataset, True), muted)
        self.assertTrue(muted.endswith("_01_mute.mp4"))
        claimed = {os.path.basename(ns["output_name"](source, dataset, False))}
        skipped = ns["output_name"](source, dataset, False, claimed)
        self.assertEqual(web_gizmo.output_name(source, dataset, False, claimed), skipped)
        self.assertTrue(os.path.basename(skipped).endswith("_02.mp4"))

        probed = self.client.get("/api/gizmo/probe", params={"path": source})
        self.assertEqual(probed.status_code, 200, probed.text)
        info = probed.json()
        self.assertEqual(info["fps"], 24)
        self.assertEqual(info["width"], 64)
        self.assertEqual(info["height"], 64)
        self.assertEqual(info["duration"], 10)
        self.assertFalse(info["has_audio"])
        self.assertEqual(info["sar"], 1)
        self.assertEqual(info["rotation"], 0)
        self.assertEqual(info["display_width"], 64)
        self.assertEqual(info["display_height"], 64)
        self.assertIsNone(info["sample_rate"])
        outside = self.client.get("/api/gizmo/probe", params={"path": str(self.root / "nope.mp4")})
        self.assertEqual(outside.status_code, 403, outside.text)

        ffmpeg = ns["find_ffmpeg"]()
        dst1 = ns["output_name"](source, dataset, False)
        dst2 = ns["output_name"](source, dataset, False, {os.path.basename(dst1)})
        spec = dict(start_s=1.5, frames=22, width=640, height=384,
                    keep_every=None, with_audio=info["has_audio"], crop=None, sar=1.0)
        expected = [
            ns["build_export_command"](ffmpeg, source, dst1, **spec),
            ns["build_export_command"](ffmpeg, source, dst2, **spec),
        ]
        started = self._post("/api/gizmo/clips", {
            "source": source,
            "dataset": dataset,
            "clips": [
                {"start": 1.5, "frames": 22, "width": 640, "height": 384,
                 "muted": False, "keep_every": None, "crop": None, "sar": 1.0},
                {"start": 1.5, "frames": 22, "width": 640, "height": 384,
                 "muted": False, "keep_every": None, "crop": None, "sar": 1.0},
            ],
        })
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        stored = self._stored(job_id)
        self.assertEqual(stored["command"], expected[0])
        self.assertEqual(stored["commands"], expected)
        self.assertEqual(stored["stage"], "Gizmo")
        done = self._wait(job_id)
        log = self.root / "jobs" / job_id / "log.txt"
        detail = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        self.assertEqual(done["status"], "done", detail)
        self.assertEqual(Path(dst1).read_bytes(), b"fake")
        self.assertEqual(Path(dst2).read_bytes(), b"fake")
        self.assertFalse(Path(dst1).with_suffix(".txt").is_file())

    def test_scene_chop_starts(self):
        ns = desktop("_SHOWINFO_TIME", "parse_scene_time", "plan_autochop")
        source = str(self.source.resolve())
        detector = "\n".join([
            "[Parsed_showinfo_1 @ 0] n: 0 pts_time:1.0",
            "[Parsed_showinfo_1 @ 0] n: 1 pts_time:3.0",
        ])
        times = []
        for line in detector.splitlines():
            found = ns["parse_scene_time"](line)
            if found is not None:
                times.append(found)
        expected = ns["plan_autochop"](times, 5, 1.0, True)
        os.environ["FIZGIG_WEB_FAKE_SCENES"] = "1"
        started = self._post("/api/gizmo/scan", {
            "source": source,
            "duration": 5,
            "span_s": 1.0,
            "fill": True,
            "detector": detector,
        })
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        done = self._wait(job_id)
        log = self.root / "jobs" / job_id / "log.txt"
        detail = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        self.assertEqual(done["status"], "done", detail)
        starts = json.loads((self.root / "jobs" / job_id / "scans.json").read_text(encoding="utf-8"))
        self.assertEqual(starts["starts"], expected)

    def test_voice_caption_and_name(self):
        ns = desktop("voice_output_name")
        source = str(self.source.resolve())
        dataset = str(self.output.resolve())
        expected = ns["voice_output_name"](source, dataset)
        self.assertEqual(web_gizmo.voice_output_name(source, dataset), expected)
        started = self._post("/api/gizmo/voices", {
            "source": source,
            "dataset": dataset,
            "segments": [{"start": 0.5, "frames": 22, "caption": "hello there"}],
        })
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        done = self._wait(job_id)
        log = self.root / "jobs" / job_id / "log.txt"
        detail = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        self.assertEqual(done["status"], "done", detail)
        wav = Path(expected)
        self.assertEqual(wav.name, os.path.basename(expected))
        self.assertEqual(wav.read_bytes(), b"fake")
        self.assertEqual(wav.with_suffix(".txt").read_text(encoding="utf-8"), "hello there")

    def test_recording_limit_and_command(self):
        dataset = str(self.output.resolve())
        os.environ["FIZGIG_WEB_UPLOAD_MAX"] = "32"
        too_big = self.client.post(
            "/api/gizmo/recordings",
            data={"dest": dataset},
            files={"file": ("take.webm", b"x" * 40, "video/webm")},
        )
        self.assertEqual(too_big.status_code, 413, too_big.text)
        os.environ["FIZGIG_WEB_UPLOAD_MAX"] = str(64 * 1024 * 1024)
        saved = self.client.post(
            "/api/gizmo/recordings",
            data={"dest": dataset},
            files={"file": ("take.webm", b"webm", "video/webm")},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        argv = body["command"]
        src = argv[argv.index("-i") + 1]
        ffmpeg = web_gizmo.find_ffmpeg()
        self.assertEqual(argv, web_gizmo.build_recording_command(ffmpeg, src, body["path"]))
        self.assertTrue(str(body["path"]).endswith(".wav"))
        self.assertTrue(Path(body["path"]).resolve().is_relative_to(self.output.resolve()))
        self.assertEqual(Path(body["path"]).read_bytes(), b"fake-wav")
        self.assertEqual(body["folder"], dataset)

    def test_real_ffmpeg_export_when_present(self):
        from fizgig.web import procs
        ffmpeg = web_gizmo.find_ffmpeg()
        if not ffmpeg:
            self.skipTest("ffmpeg is missing")
        previous = os.environ.get("FIZGIG_WEB_FAKE_FFMPEG")
        os.environ.pop("FIZGIG_WEB_FAKE_FFMPEG", None)
        src = self.output / "tiny.mp4"
        dst = self.output / "tiny_out.mp4"
        try:
            made = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=black:s=64x64:r=24:d=1",
                 "-frames:v", "24", "-pix_fmt", "yuv420p", str(src)],
                capture_output=True, timeout=60, creationflags=procs.creationflags(),
            )
            if made.returncode != 0:
                self.skipTest("ffmpeg could not make a clip")
            cmd = web_gizmo.build_export_command(
                ffmpeg, str(src), str(dst), 0.0, 5, 64, 64, with_audio=False,
            )
            proc = subprocess.run(
                cmd, capture_output=True, timeout=60, creationflags=procs.creationflags(),
            )
        finally:
            if previous is None:
                os.environ.pop("FIZGIG_WEB_FAKE_FFMPEG", None)
            else:
                os.environ["FIZGIG_WEB_FAKE_FFMPEG"] = previous
        self.assertEqual(proc.returncode, 0, (proc.stderr or b"").decode("utf-8", "replace")[-400:])
        self.assertGreater(dst.stat().st_size, 100)
        self.assertNotEqual(dst.read_bytes()[:4], b"fake")

    def test_transcribe_fake_script(self):
        source = str(self.source.resolve())
        output = self.output / "walk_whisper.txt"
        started = self._post("/api/gizmo/transcribe", {
            "source": source,
            "start": 1.25,
            "span": 2.5,
            "language": "Auto detect",
            "output": str(output),
        })
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        command = self._stored(job_id)["command"]
        fake = str(_REPO / "checks" / "fake_whisper.py")
        self.assertEqual(command[:2], [sys.executable, fake])
        self.assertEqual(command[command.index("--source") + 1], source)
        self.assertEqual(command[command.index("--start") + 1], "1.250")
        self.assertEqual(command[command.index("--span") + 1], "2.500")
        self.assertEqual(command[command.index("--language") + 1], "auto")
        self.assertEqual(command[command.index("--output") + 1], str(output.resolve()))
        done = self._wait(job_id)
        log = self.root / "jobs" / job_id / "log.txt"
        detail = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        self.assertEqual(done["status"], "done", detail)
        self.assertEqual(output.read_text(encoding="utf-8"), 'saying "fake words"')
        ffmpeg = web_gizmo.find_ffmpeg() or "ffmpeg"
        got = web_gizmo.build_whisper_extract_command(ffmpeg, "in.mp4", "out.wav", 1.25, 2.5)
        expected = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", "1.250", "-t", "2.500", "-i", "in.mp4",
                    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "out.wav"]
        self.assertEqual(got, expected)


if __name__ == "__main__":
    unittest.main()
