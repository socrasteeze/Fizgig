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


_TAILSCALE = """#!/bin/sh
dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
printf '%s\\n' "tailscale $*" >> "$dir/commands.log"
if [ "$1" = "status" ]; then
  if [ "${2:-}" = "--json" ]; then
    printf '%s\\n' '{"Self":{"DNSName":"gpu.example.ts.net."}}'
    exit 0
  fi
  if [ -f "$dir/up.flag" ]; then
    exit 0
  fi
  exit 1
fi
if [ "$1" = "up" ]; then
  : > "$dir/up.flag"
fi
exit 0
"""

_PYTHON3 = """#!/bin/sh
dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
printf '%s\\n' "python3 $* FIZGIG_WEB_TAILNET_HOST=${FIZGIG_WEB_TAILNET_HOST-}" >> "$dir/commands.log"
exit 0
"""


def _write_script(directory: Path, name: str, text: str) -> None:
    path = directory / name
    path.write_text(text, encoding="utf-8", newline="\n")
    try:
        path.chmod(path.stat().st_mode | 0o755)
    except OSError:
        pass


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

    def _run_entrypoint(self, authkey=None, state_text=None, extra_env=None):
        bash = self._require_bash()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        bindir = root / "bin"
        state = root / "state"
        bindir.mkdir()
        state.mkdir()
        _write_stub(bindir, "tailscaled")
        _write_script(bindir, "tailscale", _TAILSCALE)
        _write_script(bindir, "python3", _PYTHON3)
        if state_text is not None:
            (state / "tailscaled.state").write_text(state_text, encoding="utf-8", newline="\n")
        env = os.environ.copy()
        env.pop("TS_AUTHKEY", None)
        env.pop("FIZGIG_WEB_TAILNET_HOST", None)
        if authkey is not None:
            env["TS_AUTHKEY"] = authkey
        if extra_env:
            env.update(extra_env)
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
        status_at = next(i for i, line in enumerate(lines) if "status --json" in line)
        up_at = next(i for i, line in enumerate(lines) if line.startswith("tailscale up"))
        self.assertLess(status_at, up_at)
        self.assertNotRegex(log, r"(?m)^tailscale status$")
        self.assertIn("FIZGIG_WEB_TAILNET_HOST=gpu.example.ts.net\n", log)
        self.assertNotIn("FIZGIG_WEB_TAILNET_HOST=gpu.example.ts.net.\n", log)

    def test_starts_from_saved_state_without_key(self):
        proc, log = self._run_entrypoint(state_text="saved\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        up_lines = [line for line in log.splitlines() if "tailscale up" in line]
        self.assertTrue(up_lines, log)
        self.assertTrue(all("auth-key" not in line for line in up_lines), up_lines)
        self.assertIn("serve --bg 8081", log)

    def test_keeps_configured_tailnet_host(self):
        proc, log = self._run_entrypoint(
            authkey="fake-ts-authkey",
            extra_env={"FIZGIG_WEB_TAILNET_HOST": "mine.example.ts.net"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("FIZGIG_WEB_TAILNET_HOST=mine.example.ts.net\n", log)
        self.assertNotIn("FIZGIG_WEB_TAILNET_HOST=gpu.example.ts.net\n", log)

    def test_image_copies_serve_prefs_and_fs(self):
        import shutil
        import textwrap

        docker = _text(_REPO / "docker" / "webui" / "Dockerfile")
        entry = _text(_REPO / "docker" / "webui" / "entrypoint.sh")
        self.assertIn("COPY lora_trainer_gui.py /opt/fizgig/lora_trainer_gui.py", docker)
        self.assertIn("FIZGIG_PREFS_FILE", entry)
        self.assertIn("/workspace/prefs.json", entry)
        self.assertIn("FIZGIG_WEB_ROOTS", entry)
        self.assertIn("/workspace", entry)
        copies = _runtime_copies(docker)
        self.assertIn("lora_trainer_gui.py", [src for src, _dest in copies])
        staged = Path(tempfile.mkdtemp(prefix="fizgig-webimage-"))
        self.addCleanup(lambda: shutil.rmtree(staged, ignore_errors=True))
        for src, dest in copies:
            source = _REPO / src
            target = staged / dest if dest else staged / Path(src).name
            if source.is_dir():
                shutil.copytree(source, target, ignore=lambda _dir, names: [n for n in names if n == "__pycache__"])
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        workspace = staged / "workspace"
        workspace.mkdir()
        script = staged / "probe.py"
        script.write_text(textwrap.dedent("""
            import sys, traceback
            try:
                from fastapi.testclient import TestClient
                from fizgig.web.app import app
                with TestClient(app, base_url="http://127.0.0.1") as client:
                    prefs = client.get("/api/prefs")
                    listing = client.get("/api/fs")
                sys.stdout.write("PREFS %s\\n" % prefs.status_code)
                sys.stdout.write(prefs.text[:500] + "\\n")
                sys.stdout.write("FS %s\\n" % listing.status_code)
                sys.stdout.write(listing.text[:500] + "\\n")
                if prefs.status_code != 200 or listing.status_code != 200:
                    sys.exit(1)
                if "FileNotFoundError" in prefs.text or "FileNotFoundError" in listing.text:
                    sys.exit(1)
            except Exception:
                traceback.print_exc()
                sys.exit(1)
        """), encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(staged / "src")
        env["FIZGIG_PREFS_FILE"] = str(workspace / "prefs.json")
        env["FIZGIG_WEB_ROOTS"] = str(workspace)
        env["FIZGIG_NO_PERSIST"] = "1"
        env["FIZGIG_WEB_JOBS"] = str(staged / "jobs")
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(staged),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)

    def test_docs_and_api_scripts(self):
        docs = _text(_REPO / "docs" / "WEBUI.md")
        self.assertIn("set FIZGIG_WEB_TAILNET_HOST=", docs)
        self.assertIn("$env:FIZGIG_WEB_TAILNET_HOST=", docs)
        self.assertIn("export FIZGIG_WEB_TAILNET_HOST=", docs)
        self.assertIn("pip install -r requirements-web.txt", docs)
        self.assertIn("npm --prefix webui ci", docs)
        self.assertIn("from a thread inside the running server", docs)
        self.assertIn("Opening the page does not start a job", docs)
        self.assertIn("A failed run does not start the next one", docs)
        self.assertIn("not sent", docs)
        self.assertIn("save_repaired", docs)
        self.assertNotIn("baked with `save_repaired_lora`", docs)
        self.assertIn("Self.DNSName", docs)
        for name in ("check-api.mjs", "gen-api.mjs"):
            text = _text(_REPO / "webui" / "scripts" / name)
            self.assertIn("FIZGIG_PY", text)
            self.assertIn("venv/Scripts/python.exe", text)
            self.assertIn("venv/bin/python", text)
            self.assertIn("python3", text)
            self.assertNotIn('const py = resolve(repo, "venv/Scripts/python.exe")', text)


def _runtime_copies(text: str) -> list[tuple[str, str]]:
    stage = 0
    found = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("FROM "):
            stage += 1
            continue
        if stage < 2 or not line.startswith("COPY "):
            continue
        parts = line.split()
        if parts[1].startswith("--from="):
            dest = parts[-1]
            if dest.startswith("/opt/fizgig/"):
                found.append(("webui/dist", dest[len("/opt/fizgig/"):].rstrip("/")))
            continue
        dest = parts[-1]
        if not dest.startswith("/opt/fizgig"):
            continue
        rel = "" if dest == "/opt/fizgig" else dest[len("/opt/fizgig/"):].rstrip("/")
        for src in parts[1:-1]:
            found.append((src.rstrip("/"), rel))
    return found


if __name__ == "__main__":
    unittest.main()
