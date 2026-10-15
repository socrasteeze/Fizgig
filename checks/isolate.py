"""Test isolation: Fizgig's own files go to a temp folder, never to the real user_data/.

Import this before anything from fizgig.web. Upstream's data paths are import-time constants, built from
fizgig.user_data when each module loads, so the order matters:

1. user_data's paths move into a temp folder and migrate() is switched off (it would move the real Fizgig 7 files).
2. server, queue, history, captions and studio are imported: their files (web_state.json, web_queue.json,
   runs.json, caption_jobs/, studio/) are built from the moved folder.
3. server's defaults that hang off the Fizgig folder (output_loras, training_data, uploads) move too.

``test_isolation`` checks that no loaded web module still holds a data path inside the Fizgig folder.
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

if "fizgig.web.server" in sys.modules and not getattr(sys.modules["fizgig.web.server"], "_ISOLATED", False):
    raise RuntimeError("import isolate before fizgig.web: the server already holds the real user_data paths")

ROOT = tempfile.mkdtemp(prefix="fizgig-checks-")
atexit.register(shutil.rmtree, ROOT, True)

from fizgig import user_data  # noqa: E402

user_data.USER_DATA = os.path.join(ROOT, "user_data")
user_data.PREFS_FILE = os.path.join(user_data.USER_DATA, "prefs.json")
user_data.LAST_USED_FILE = os.path.join(user_data.USER_DATA, "last_used.json")
user_data.PRESETS_DIR = os.path.join(user_data.USER_DATA, "presets")
user_data.MODELS_DIR = os.path.join(user_data.USER_DATA, "models")
user_data.migrate = lambda *a, **k: None
user_data._done.append(True)

from fizgig.web import server  # noqa: E402  (imports captions, history, queue and studio)

server.OUTPUT_DEFAULT = os.path.join(ROOT, "output_loras")
server.UPLOAD_DEFAULT = os.path.join(ROOT, "training_data")
server.UPLOAD_FILES = os.path.join(ROOT, "uploads")
server._ISOLATED = True


def write_prefs(**values):
    """A fresh prefs.json in the temp folder: its folders inside it, plus `values`."""
    prefs = {"lora_output_dir": server.OUTPUT_DEFAULT, "cache_dir": os.path.join(ROOT, "cache"),
             "profiles_dir": os.path.join(ROOT, "profiles"), **values}
    os.makedirs(os.path.dirname(user_data.PREFS_FILE), exist_ok=True)
    with open(user_data.PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)
    return prefs


def leaks():
    """Module globals of the loaded fizgig.web modules that still point at a data path in the Fizgig folder.
    The code folders (src/, the folder itself) are fine; anything else there is a real user's file."""
    repo, src = os.path.normcase(str(REPO)), os.path.normcase(str(REPO / "src"))
    found = []
    for name, mod in sorted(sys.modules.items()):
        if not name.startswith("fizgig.web") or mod is None:
            continue
        for attr, v in vars(mod).items():
            if not isinstance(v, str) or not os.path.isabs(v):
                continue
            p = os.path.normcase(os.path.normpath(v))
            if p == repo or p.startswith(src + os.sep) or p == src:
                continue
            if p.startswith(repo + os.sep):
                found.append(f"{name}.{attr} = {v}")
    return found


write_prefs()
