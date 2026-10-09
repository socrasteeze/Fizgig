"""Image prep output matches the desktop helpers, including a stubbed face crop.

The desktop class is constructed without its GUI. No face model is loaded.

    python -m unittest checks.test_web_prep -v
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
os.environ.setdefault("FIZGIG_NO_PERSIST", "1")

from PIL import Image
from fastapi.testclient import TestClient

from fizgig.web import image_prep
from fizgig.web.app import app
import runner_guard


def _tree(folder: Path) -> dict:
    found = {}
    for path in folder.rglob("*"):
        if path.is_file():
            found[path.relative_to(folder).as_posix()] = path.read_bytes()
    return found


def _fill(folder: Path) -> None:
    folder.mkdir(parents=True)
    Image.new("RGB", (64, 48), (20, 40, 60)).save(folder / "wide.jpg", "JPEG")
    Image.new("RGB", (64, 64), (200, 10, 10)).save(folder / "face.png")


class Host:
    """Enough of the desktop object for the prep helpers. No window, no detector model."""

    def __init__(self, detector):
        import lora_trainer_gui as gui

        self._gui = gui.LoRATrainerGUI
        self.IMAGE_EXTENSIONS = gui.LoRATrainerGUI.IMAGE_EXTENSIONS
        self._originals_dir_cache = {}
        self._detector = detector
        self.logs = []

    def _log(self, text):
        self.logs.append(text)

    @property
    def face_detector(self):
        return self._detector

    def __getattr__(self, name):
        raw = self._gui.__dict__[name]
        if isinstance(raw, staticmethod):
            return raw.__func__
        if isinstance(raw, classmethod):
            return raw.__get__(self._gui, self._gui)
        return raw.__get__(self, Host)


class WebPrepTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = {
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_WEB_FAKE_FACE": os.environ.get("FIZGIG_WEB_FAKE_FACE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
        }
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.root)
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_WEB_FAKE_FACE"] = "1"
        os.environ["FIZGIG_NO_PERSIST"] = "1"
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

    def _pair(self, name):
        left = self.root / name / "desktop"
        right = self.root / name / "web"
        _fill(left)
        _fill(right)
        return left, right

    def _host(self):
        import lora_trainer_gui as gui

        if not hasattr(gui, "crop_to_face"):
            root = str(_REPO)
            if root not in sys.path:
                sys.path.insert(0, root)
            from face_utils import crop_to_face
            gui.crop_to_face = crop_to_face
        return Host(image_prep.StubDetector())

    def test_matches_desktop_including_face_crop(self):
        host = self._host()
        self.assertEqual(image_prep.target_area(1.0), host._prep_target_area(1.0))
        self.assertEqual(image_prep.face_mode_of("Largest Female Face"), "largest_female")
        area = 256

        left, right = self._pair("resize")
        host._resize_only_images(str(left), str(left), area, False)
        image_prep.resize_only(str(right), str(right), area, False)
        self.assertEqual(_tree(left), _tree(right))

        left, right = self._pair("crop")
        host._face_crop_only_images(str(left), str(left), area, "largest_face", 20.0, False)
        image_prep.face_crop_only(str(right), str(right), area, "largest_face", 20.0, False, image_prep.StubDetector())
        self.assertEqual(_tree(left), _tree(right))

        left, right = self._pair("auto")
        host._auto_prep_images(str(left), str(left), area, "largest_face", 20.0, False)
        image_prep.auto_prep(str(right), str(right), area, "largest_face", 20.0, False, image_prep.StubDetector())
        self.assertEqual(_tree(left), _tree(right))

    def test_resize_job(self):
        folder = self.root / "dataset"
        _fill(folder)
        saved = self.client.put("/api/start", json={"folder": str(folder)})
        self.assertEqual(saved.status_code, 200, saved.text)
        started = self.client.post("/api/prep/jobs", json={"mode": "Resize Only", "megapixels": "0.25"})
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        end = time.time() + 15
        status = ""
        while time.time() < end:
            status = self.client.get(f"/api/jobs/{job_id}").json()["status"]
            if status in {"done", "failed", "stopped"}:
                break
            time.sleep(0.05)
        log = ""
        log_path = self.root / "jobs" / job_id / "log.txt"
        if log_path.is_file():
            log = log_path.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(status, "done", log)
        self.assertTrue((folder / "wide.png").is_file())
        self.assertTrue((folder / "originals" / "wide.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
