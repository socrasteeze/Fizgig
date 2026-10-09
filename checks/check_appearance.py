"""Preference appearance check.

Drives the shipped load/save and appearance resolution against a temporary
preference file. Does not construct the 13-tab window.

    python checks/check_appearance.py
    python checks/check_appearance.py --launch <scratch-dir>
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE_FILES = (
    REPO / "prefs.json",
    REPO / ".last_used.json",
    REPO / "last_used.json",
)
EXPECTED_TABS = (
    "1. Start",
    "2. Image Prep",
    "3. Captions",
    "4. Samples",
    "5. Training",
    "Profiler",
    "Repair Studio",
    "RefMod Studio",
    "LoRA the Explorer",
    "LoRA Royale",
    "Extract",
    "Metadata",
    "Preferences",
)


def _live_digest():
    rows = []
    for path in LIVE_FILES:
        if path.is_file():
            rows.append(hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            rows.append("absent")
    return tuple(rows)


def _pass(message: str) -> None:
    print(f"PASS {message}", flush=True)


def check_resolution() -> None:
    before = _live_digest()
    os.environ.pop("FIZGIG_NO_PERSIST", None)
    tmp = Path(tempfile.mkdtemp(prefix="fizgig-appearance-"))
    prefs_path = tmp / "isolated-prefs.json"
    last_path = tmp / "isolated-last-used.json"
    os.environ["FIZGIG_PREFS_FILE"] = str(prefs_path)
    os.environ["FIZGIG_LAST_USED_FILE"] = str(last_path)

    sys.path.insert(0, str(REPO))
    import lora_trainer_gui as gui

    assert gui.PREFS_FILE == str(prefs_path)
    assert gui.LAST_USED_FILE == str(last_path)
    assert gui.PREFS_FILE != str(REPO / "prefs.json")

    assert gui.resolve_appearance(None) == gui.APPEARANCE_DARK_CLAM
    assert gui.resolve_appearance("") == gui.APPEARANCE_DARK_CLAM
    assert gui.resolve_appearance("   ") == gui.APPEARANCE_DARK_CLAM
    _pass("missing value resolves to dark-clam")

    prefs_path.write_text("{}\n", encoding="utf-8")
    loaded = gui.load_prefs()
    on_disk = json.loads(prefs_path.read_text(encoding="utf-8"))
    assert "appearance" not in on_disk
    assert gui.resolve_appearance(on_disk.get("appearance")) == gui.APPEARANCE_DARK_CLAM
    assert gui.resolve_appearance(loaded.get("appearance")) == gui.APPEARANCE_DARK_CLAM
    _pass("loaded file with no appearance key resolves to dark-clam")

    prefs_path.write_text(json.dumps({"appearance": "sun-valley-dark"}) + "\n", encoding="utf-8")
    loaded = gui.load_prefs()
    assert loaded["appearance"] == "sun-valley-dark"
    assert gui.resolve_appearance(loaded["appearance"]) == gui.APPEARANCE_DARK_CLAM
    _pass("invalid value resolves to dark-clam")

    os.environ.pop("FIZGIG_NO_PERSIST", None)
    gui.save_prefs({"appearance": gui.APPEARANCE_COMPACT_CLAM})
    loaded = gui.load_prefs()
    saved = json.loads(prefs_path.read_text(encoding="utf-8"))
    assert saved["appearance"] == gui.APPEARANCE_COMPACT_CLAM
    assert loaded["appearance"] == gui.APPEARANCE_COMPACT_CLAM
    assert gui.resolve_appearance(loaded["appearance"]) == gui.APPEARANCE_COMPACT_CLAM
    assert gui.resolve_appearance(gui.APPEARANCE_DARK_CLAM) == gui.APPEARANCE_DARK_CLAM
    _pass("saved alternate resolves to compact-clam")

    dark = gui.appearance_spacing(None)
    compact = gui.appearance_spacing(gui.APPEARANCE_COMPACT_CLAM)
    assert dark["button"] == (16, 8)
    assert dark["tab"] == (12, 6)
    assert dark["tab_selected"] == (6, 4, 6, 2)
    assert dark["check"] == 2
    assert dark["entry"] == 1
    assert dark["labelframe"] is None
    assert dark["tabmargin"] is None
    assert dark["scrollbar"] == 12
    assert dark["rowheight"] == 24
    assert dark["check"] != compact["check"]
    assert dark["entry"] != compact["entry"]
    assert dark["button"] != compact["button"]
    assert dark["tab_selected"] != compact["tab_selected"]
    assert compact["tab_selected"] == compact["tab"]
    assert set(dark) == set(compact)
    _pass("dark-clam matches the pre-change clam spacing")
    _pass("compact-clam uses a different shared spacing scale, including the selected tab")

    after = _live_digest()
    assert before == after
    assert not last_path.exists()
    _pass("isolated preference file only")
    print("ALL ASSERTIONS PASSED", flush=True)


def _python():
    candidate = REPO / "venv" / "Scripts" / "python.exe"
    if candidate.is_file():
        return candidate
    return Path(sys.executable)


def _tk_failed(text: str) -> bool:
    lowered = text.lower()
    needles = (
        "can't find a usable tk.tcl",
        "can't find a usable init.tcl",
        "no display name and no $display environment variable",
        "couldn't connect to display",
    )
    return any(needle in lowered for needle in needles)


def launch_twice(scratch: Path) -> None:
    before = _live_digest()
    scratch.mkdir(parents=True, exist_ok=True)
    home = scratch / "launch-home"
    home.mkdir(parents=True, exist_ok=True)
    for name in ("cache", "profiles", "output"):
        (home / name).mkdir(exist_ok=True)
    prefs_path = home / "isolated-prefs.json"
    last_path = home / "isolated-last-used.json"
    chosen = "compact-clam"
    prefs_path.write_text(json.dumps({
        "appearance": chosen,
        "cache_dir": str((home / "cache").resolve()),
        "profiles_dir": str((home / "profiles").resolve()),
        "lora_output_dir": str((home / "output").resolve()),
    }, indent=2), encoding="utf-8")
    env = os.environ.copy()
    env["FIZGIG_PREFS_FILE"] = str(prefs_path)
    env["FIZGIG_LAST_USED_FILE"] = str(last_path)
    env["FIZGIG_NO_PERSIST"] = "1"
    env["FIZGIG_STRUCTURAL_DUMP"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    script = REPO / "lora_trainer_gui.py"
    for index in (1, 2):
        proc = subprocess.run(
            [str(_python()), str(script)],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
            errors="replace",
        )
        body = (proc.stdout or "").replace("\r\n", "\n").replace("\r", "\n")
        if proc.stderr:
            body += "\n" + proc.stderr.replace("\r\n", "\n").replace("\r", "\n")
        log = scratch / f"launch-{index}.log"
        log.write_text(body, encoding="utf-8")
        if proc.returncode != 0 or "APPEARANCE:" not in body:
            if _tk_failed(body):
                (scratch / "launch-fail.log").write_text(body, encoding="utf-8")
                print("Tk could not open a window; wrote launch-fail.log", flush=True)
                raise SystemExit(2)
            raise SystemExit(f"launch {index} failed with code {proc.returncode}")
        if f"APPEARANCE: {chosen}" not in body:
            raise SystemExit(f"launch {index} appearance mismatch")
        if "THEME: clam" not in body:
            raise SystemExit(f"launch {index} left clam")
        padding = next((line.split(":", 1)[1].strip() for line in body.splitlines()
                        if line.startswith("BUTTON_PADDING:")), "")
        if padding not in {"8 3", "(8, 3)", "8 3 8 3"}:
            raise SystemExit(f"launch {index} did not apply compact button spacing ({padding})")
        for label in EXPECTED_TABS:
            if f"TAB: {label}\n" not in body and not body.endswith(f"TAB: {label}"):
                raise SystemExit(f"launch {index} missing tab {label}")
        _pass(f"launch {index} shows {chosen} and 13 tabs")
    after = _live_digest()
    assert before == after
    _pass("launches left the checkout preference files unchanged")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--launch":
        if len(sys.argv) != 3:
            raise SystemExit("usage: check_appearance.py --launch <scratch-dir>")
        launch_twice(Path(sys.argv[2]))
        return
    check_resolution()


if __name__ == "__main__":
    main()
