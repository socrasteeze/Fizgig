"""Every subprocess launch under src/fizgig/web passes creationflags or hidden_console.

The Windows test starts a job and an engine worker, and checks that a grandchild
launched with no flags inherits a console that is not visible.

    python -m unittest checks.test_web_no_window -v
"""
import ast
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
_WEB = _REPO / "src" / "fizgig" / "web"
_CALLS = {"Popen", "run", "call", "check_call", "check_output"}

sys.path.insert(0, str(_REPO / "src"))

# The stand-in starts a grandchild with no window flags on purpose.
_STAGE = """\
import os
import subprocess
import sys

proc = subprocess.Popen(
    [sys.executable, os.environ["FIZGIG_CONSOLE_CHILD"], os.environ["FIZGIG_CONSOLE_RESULT"]],
)
code = proc.wait()
if code != 0:
    raise RuntimeError("grandchild exited %s" % code)
"""

_GRANDCHILD = """\
import ctypes
import sys
from pathlib import Path

out = Path(sys.argv[1])
try:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel.GetConsoleWindow.restype = ctypes.c_void_p
    user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
    user32.IsWindowVisible.restype = ctypes.c_int
    hwnd = kernel.GetConsoleWindow() or 0
    visible = int(user32.IsWindowVisible(hwnd)) if hwnd else 0
    out.write_text("console=%s visible=%s\\n" % (int(bool(hwnd)), visible), encoding="utf-8")
except Exception as exc:
    out.write_text("error=%s\\n" % exc, encoding="utf-8")
    raise
"""

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
_ENV_KEYS = (
    "FIZGIG_WEB_JOBS",
    "FIZGIG_WEB_FAKE_TRAINER",
    "FIZGIG_WEB_FAKE_ENGINE",
    "FIZGIG_CONSOLE_CHILD",
    "FIZGIG_CONSOLE_RESULT",
    "FIZGIG_NO_PERSIST",
    "FIZGIG_PREFS_FILE",
    "FIZGIG_WEB_ROOTS",
)


def _missing():
    if not _WEB.is_dir():
        return [f"missing {_WEB}"]
    found = []
    for path in sorted(_WEB.rglob("*.py")):
        rel = path.relative_to(_REPO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in _CALLS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                continue
            if any(kw.arg == "creationflags" for kw in node.keywords):
                continue
            if _spreads_hidden_console(node):
                continue
            found.append(f"{rel}:{node.lineno}")
    return found


def _spreads_hidden_console(node):
    for kw in node.keywords:
        if kw.arg is not None or not isinstance(kw.value, ast.Call):
            continue
        func = kw.value.func
        if isinstance(func, ast.Name) and func.id == "hidden_console":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "hidden_console":
            return True
    return False


class NoWindowTests(unittest.TestCase):
    def test_subprocess_calls_pass_creationflags(self):
        missing = _missing()
        self.assertFalse(
            missing,
            "missing creationflags or hidden_console:\n" + "\n".join(missing),
        )

    def test_helper_flags(self):
        from fizgig.web import procs

        with patch.object(procs.os, "name", "posix"):
            self.assertEqual(procs.creationflags(), 0)
            self.assertEqual(procs.hidden_console(), {"creationflags": 0})
            self.assertEqual(
                procs.hidden_console(detached=True),
                {"creationflags": 0, "start_new_session": True},
            )
        if os.name != "nt":
            return
        self.assertEqual(procs.creationflags(), subprocess.CREATE_NO_WINDOW)
        own = procs.hidden_console()
        detached = procs.hidden_console(detached=True)
        self.assertEqual(own["creationflags"], subprocess.CREATE_NEW_CONSOLE)
        self.assertEqual(
            detached["creationflags"],
            subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        for kwargs in (own, detached):
            flags = kwargs["creationflags"]
            self.assertFalse(flags & subprocess.DETACHED_PROCESS)
            self.assertFalse(flags & subprocess.CREATE_NO_WINDOW)
            info = kwargs["startupinfo"]
            self.assertEqual(
                info.dwFlags & subprocess.STARTF_USESHOWWINDOW,
                subprocess.STARTF_USESHOWWINDOW,
            )
            self.assertEqual(info.wShowWindow, subprocess.SW_HIDE)
        self.assertFalse(own["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP)

    @unittest.skipUnless(os.name == "nt", "hidden console inheritance is Windows-only")
    def test_grandchild_inherits_hidden_console(self):
        from fizgig.gpu_lock import held
        from fizgig.web import jobs
        from fizgig.web.engine_host import EngineHost
        from fizgig.web.procs import creationflags

        self.assertNotIn("creationflags", _STAGE)
        self.assertFalse(held(), "a lock is already held; the desktop or another run has this GPU")
        saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        host = None
        job_id = None
        try:
            child = root / "grandchild.py"
            stage = root / "stage.py"
            child.write_text(_GRANDCHILD, encoding="utf-8")
            stage.write_text(_STAGE, encoding="utf-8")
            output = root / "output"
            images = root / "images"
            output.mkdir()
            images.mkdir()
            (images / "a.png").write_bytes(_PNG)
            (images / "a.txt").write_text("a photo\n", encoding="utf-8")
            checkpoint = root / "checkpoint.safetensors"
            checkpoint.write_bytes(b"not a model")
            os.environ["FIZGIG_WEB_JOBS"] = str(root / "jobs")
            os.environ["FIZGIG_NO_PERSIST"] = "1"
            os.environ["FIZGIG_PREFS_FILE"] = str(root / "prefs.json")
            os.environ["FIZGIG_WEB_ROOTS"] = str(root)
            os.environ["FIZGIG_WEB_FAKE_TRAINER"] = str(stage)
            os.environ["FIZGIG_CONSOLE_CHILD"] = str(child)
            os.environ["FIZGIG_WEB_FAKE_ENGINE"] = "1"
            job_result = root / "job.txt"
            os.environ["FIZGIG_CONSOLE_RESULT"] = str(job_result)
            started = jobs.start("sdxl", {
                "LORA_OUTPUT_DIR": str(output),
                "LORA_NAME": "WebRun",
                "LEARNING_RATE": 1e-4,
                "NETWORK_DIM": 4,
                "NETWORK_ALPHA": 4,
                "MAX_TRAIN_EPOCHS": 1,
                "SAVE_EVERY_N_EPOCHS": 1,
                "SEED": 1,
            }, {
                "models": {"sdxl_checkpoint": str(checkpoint)},
                "image_folder": str(images),
                "DATASET_CONFIG": str(output / "dataset.toml"),
            }, ["low_disk"])
            job_id = started["id"]
            report = self._wait_text(job_result)
            body = self._wait_terminal(jobs, job_id)
            log = self._log(root, job_id)
            self.assertEqual(report, "console=1 visible=0", log)
            self.assertEqual(body.get("status"), "done", log)
            self._wait_free(held)

            engine_result = root / "engine.txt"
            os.environ["FIZGIG_CONSOLE_RESULT"] = str(engine_result)
            host = EngineHost()
            try:
                host.load("repair", "klein", {"console_probe": str(stage)})
            except Exception as exc:
                worker_log = ""
                if host.session is not None:
                    path = host.session / "worker.log"
                    if path.is_file():
                        worker_log = path.read_text(encoding="utf-8", errors="replace")
                self.fail(f"{exc}\n{worker_log}")
            self.assertEqual(self._wait_text(engine_result), "console=1 visible=0")
        finally:
            self._stop(jobs if job_id else None, job_id, host, creationflags)
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            tmp.cleanup()

    def _wait_text(self, path, timeout=45):
        end = time.time() + timeout
        while time.time() < end:
            if path.is_file() and path.stat().st_size:
                return path.read_text(encoding="utf-8").strip()
            time.sleep(0.05)
        self.fail(f"no probe result at {path.name}")

    def _wait_terminal(self, jobs, job_id, timeout=45):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = jobs.get_job(job_id)
            if last.get("status") in {"done", "failed", "stopped"}:
                return last
            time.sleep(0.05)
        return last or {}

    def _log(self, root, job_id):
        path = root / "jobs" / job_id / "log.txt"
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _wait_free(self, held, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if not held():
                return
            time.sleep(0.05)
        self.fail("the GPU lock is still held")

    def _stop(self, jobs, job_id, host, creationflags):
        if jobs is not None and job_id:
            try:
                current = jobs.get_job(job_id)
            except Exception:
                current = None
            if current and current.get("status") in {"queued", "running"}:
                try:
                    jobs.stop(job_id)
                except Exception:
                    pass
            pid = int((current or {}).get("pid") or 0)
            self._kill_tree(pid, creationflags)
        if host is not None:
            proc = host.proc
            pid = proc.pid if proc is not None else 0
            self._kill_tree(pid, creationflags)
            try:
                host.close()
            except Exception:
                pass
            self._kill_tree(pid, creationflags)

    def _kill_tree(self, pid, creationflags):
        if not pid:
            return
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            creationflags=creationflags(),
        )


if __name__ == "__main__":
    unittest.main()
