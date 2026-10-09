"""Loopback web service scripts. No autostart, no public bind.

    python -m unittest checks.test_web_service -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fizgig.web.procs import creationflags

_SKIP_DIRS = {"__pycache__", "node_modules", "dist"}
_NEEDLES = (
    "schtasks",
    "Register-ScheduledTask",
    "systemctl enable",
    "CurrentVersion\\Run",
    "shell:startup",
    "Programs\\Startup",
)
_BANNED = ("funnel", "0.0.0.0", "EXPOSE")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_stub(directory: Path, name: str) -> None:
    path = directory / name
    path.write_text(
        "#!/bin/sh\n"
        'dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)\n'
        f'printf "%s\\n" "{name} $*" >> "$dir/commands.log"\n'
        "exit 0\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        path.chmod(path.stat().st_mode | 0o755)
    except OSError:
        pass


class WebServiceTests(unittest.TestCase):
    def test_run_webui_sh(self):
        text = _text(_REPO / "run_webui.sh")
        self.assertNotIn("\r", text)
        self.assertIn("127.0.0.1", text)
        self.assertNotIn("0.0.0.0", text)
        self.assertRegex(text, r"PYTHONPATH=.*src")
        self.assertIn("npm --prefix webui run build", text)
        self.assertIn("fizgig.web", text)

    def test_docker_webui_text(self):
        docker = _text(_REPO / "docker" / "webui" / "Dockerfile")
        entry = _text(_REPO / "docker" / "webui" / "entrypoint.sh")
        self.assertNotIn("\r", docker)
        self.assertNotIn("\r", entry)
        for label, text in (("Dockerfile", docker), ("entrypoint", entry)):
            for banned in _BANNED:
                self.assertNotIn(banned, text, label)
        self.assertIn("ARG BASE_IMAGE=fizgig:desktop", docker)
        self.assertIn("node:22-bookworm-slim", docker)
        self.assertIn("npx tsc --noEmit && npx vite build", docker)
        self.assertNotIn("COPY webui/ ./", docker)
        self.assertIn("tailscale serve --bg 8081", entry)
        self.assertIn("--tun=userspace-networking", entry)
        self.assertIn("127.0.0.1", entry)
        self.assertNotIn("funnel", entry)

    def test_no_autostart(self):
        self_path = Path(__file__).resolve()
        files = [_REPO / "run_webui.sh", _REPO / "run_webui.bat"]
        for rel in ("docker/webui", "src/fizgig/web", "webui/src"):
            root = _REPO.joinpath(*rel.split("/"))
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if any(part in _SKIP_DIRS for part in path.parts):
                    continue
                files.append(path)
        for path in (_REPO / "checks").glob("test_web_*.py"):
            if path.resolve() == self_path:
                continue
            files.append(path)
        hits = []
        for path in files:
            if path.resolve() == self_path:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for needle in _NEEDLES:
                if needle in text:
                    hits.append(f"{path.name}: {needle}")
        self.assertEqual(hits, [])

    def _require_bash(self) -> str:
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash is not on PATH")
        return bash

    def _run_entrypoint(self, authkey=None, state_text=None):
        bash = self._require_bash()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        bindir = root / "bin"
        state = root / "state"
        bindir.mkdir()
        state.mkdir()
        for name in ("tailscaled", "tailscale", "python3"):
            _write_stub(bindir, name)
        if state_text is not None:
            (state / "tailscaled.state").write_text(state_text, encoding="utf-8", newline="\n")
        env = os.environ.copy()
        env.pop("TS_AUTHKEY", None)
        if authkey is not None:
            env["TS_AUTHKEY"] = authkey
        env["TS_STATE_DIR"] = state.as_posix()
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        proc = subprocess.run(
            [bash, str(_REPO / "docker" / "webui" / "entrypoint.sh")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=20,
            creationflags=creationflags(),
        )
        self.assertIsNotNone(proc.returncode)
        log_path = bindir / "commands.log"
        log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
        return proc, log

    def test_refuses_without_key_or_saved_state(self):
        proc, log = self._run_entrypoint()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("TS_AUTHKEY", proc.stderr)
        self.assertIn("saved Tailscale state", proc.stderr)
        for name in ("tailscaled", "tailscale", "python3"):
            self.assertNotIn(name, log)

    def test_starts_with_auth_key(self):
        proc, log = self._run_entrypoint(authkey="fake-ts-authkey")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = log.splitlines()
        self.assertTrue(
            any("tailscaled" in line and "--tun=userspace-networking" in line and "--statedir" in line for line in lines),
            log,
        )
        self.assertTrue(
            any("up" in line and "--auth-key" in line and "fake-ts-authkey" in line for line in lines),
            log,
        )
        self.assertIn("serve --bg 8081", log)
        self.assertTrue(any("python3" in line and "-m" in line and "fizgig.web" in line for line in lines), log)
        self.assertNotIn("funnel", log)
        self.assertNotIn("funnel", _text(_REPO / "docker" / "webui" / "entrypoint.sh"))

    def test_starts_from_saved_state_without_key(self):
        proc, log = self._run_entrypoint(state_text="saved\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        up_lines = [line for line in log.splitlines() if "tailscale up" in line]
        self.assertTrue(up_lines, log)
        self.assertTrue(all("auth-key" not in line for line in up_lines), up_lines)
        self.assertIn("serve --bg 8081", log)


if __name__ == "__main__":
    unittest.main()
