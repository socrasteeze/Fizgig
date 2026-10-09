"""Folder roots, upload limits, zip slip, and duplicate names.

    python -m unittest checks.test_web_fs -v
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.web.app import app

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _link(link: Path, target: Path) -> str:
    try:
        os.symlink(target, link, target_is_directory=True)
        return "symlink"
    except OSError:
        pass
    subprocess.check_call(["cmd", "/c", "mklink", "/J", str(link), str(target)], stdout=subprocess.DEVNULL)
    return "junction"


def _try_link(link: Path, target: Path) -> str | None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return "symlink"
    except OSError:
        pass
    if _junction(link, target):
        return "junction"
    return None


def _junction(link: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        subprocess.check_call(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return True
    except (OSError, AttributeError):
        return False


class WebFsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dataset = self.root / "dataset"
        self.dataset.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        (self.outside / "secret.png").write_bytes(_PNG)
        self.output = self.root / "output"
        self.output.mkdir()
        (self.output / "run.safetensors").write_bytes(b"lora")
        self._env = {
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_WEB_UPLOAD_MAX": os.environ.get("FIZGIG_WEB_UPLOAD_MAX"),
        }
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.dataset)
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_WEB_UPLOAD_MAX"] = "100000"
        (self.root / "prefs.json").write_text(
            '{"lora_output_dir": "%s", "runpod_api_key": "zz-secret-value-zz"}' % str(self.output).replace("\\", "\\\\"),
            encoding="utf-8",
        )
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        self._client.__exit__(None, None, None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_roots_reject_dotdot_symlink_and_junction(self):
        listed = self.client.get("/api/fs", params={"path": str(self.dataset)})
        self.assertEqual(listed.status_code, 200, listed.text)
        escaped = self.client.get("/api/fs", params={"path": str(self.dataset) + "/../outside"})
        self.assertEqual(escaped.status_code, 403, escaped.text)
        outside = self.client.get("/api/fs", params={"path": str(self.outside)})
        self.assertEqual(outside.status_code, 403, outside.text)

        link = self.dataset / "via-link"
        kind = _link(link, self.outside)
        response = self.client.get("/api/fs", params={"path": str(link)})
        self.assertEqual(response.status_code, 403, f"{kind}: {response.text}")
        other = self.dataset / "via-junction"
        if kind != "junction":
            subprocess.check_call(
                ["cmd", "/c", "mklink", "/J", str(other), str(self.outside)],
                stdout=subprocess.DEVNULL,
            )
            jumped = self.client.get("/api/fs", params={"path": str(other)})
            self.assertEqual(jumped.status_code, 403, jumped.text)

    def test_upload_limit_conflict_and_zip_slip(self):
        ok = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[("files", ("photo.png", _PNG, "image/png"))],
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertTrue((self.dataset / "photo.png").is_file())
        again = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[("files", ("photo.png", _PNG, "image/png"))],
        )
        self.assertEqual(again.status_code, 409, again.text)
        self.assertEqual(again.json()["conflicts"], ["photo.png"])

        os.environ["FIZGIG_WEB_UPLOAD_MAX"] = "8"
        huge = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset), "overwrite": "1"},
            files=[("files", ("photo.png", _PNG, "image/png"))],
        )
        self.assertEqual(huge.status_code, 413, huge.text)
        os.environ["FIZGIG_WEB_UPLOAD_MAX"] = "100000"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("../secret.png", _PNG)
            archive.writestr("ok.png", _PNG)
        slipped = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[("archive", ("pics.zip", buf.getvalue(), "application/zip"))],
        )
        self.assertEqual(slipped.status_code, 422, slipped.text)
        self.assertFalse((self.outside / "from-zip.png").exists())
        self.assertFalse((self.root / "secret.png").exists())
        self.assertFalse((self.dataset / "ok.png").exists())

        safe = io.BytesIO()
        with zipfile.ZipFile(safe, "w") as archive:
            archive.writestr("nested/kept.png", _PNG)
        written = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[("archive", ("pics.zip", safe.getvalue(), "application/zip"))],
        )
        self.assertEqual(written.status_code, 200, written.text)
        self.assertTrue((self.dataset / "kept.png").is_file())

        downloaded = self.client.get("/api/download", params={"path": str(self.output / "run.safetensors")})
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, b"lora")
        leaked = self.client.get("/api/download", params={"path": str(self.outside / "secret.png")})
        self.assertIn(leaked.status_code, {403, 404})

    def test_root_reached_through_a_link_is_allowed(self):
        real = self.root / "storage"
        dataset = real / "dataset"
        dataset.mkdir(parents=True)
        (dataset / "keep.png").write_bytes(_PNG)
        nested = dataset / "nested"
        nested.mkdir()
        gate = self.root / "gate"
        kind = _try_link(gate, real)
        if kind is None:
            self.skipTest("creating a symlink or junction is not permitted")

        linked = gate / "dataset"
        os.environ["FIZGIG_WEB_ROOTS"] = str(linked)
        listed = self.client.get("/api/fs", params={"path": str(linked)})
        self.assertEqual(listed.status_code, 200, f"{kind}: {listed.text}")
        self.assertIn("keep.png", [item["name"] for item in listed.json()["entries"]])
        child = self.client.get("/api/fs", params={"path": str(linked / "nested")})
        self.assertEqual(child.status_code, 200, child.text)

        alias = dataset / "alias"
        self.assertIsNotNone(_try_link(alias, nested))
        refused = self.client.get("/api/fs", params={"path": str(linked / "alias")})
        self.assertEqual(refused.status_code, 403, refused.text)
        escaped = self.client.get("/api/fs", params={"path": str(linked) + "/../outside"})
        self.assertEqual(escaped.status_code, 403, escaped.text)

        direct = self.root / "direct-root"
        direct_kind = _try_link(direct, dataset)
        self.assertIsNotNone(direct_kind)
        os.environ["FIZGIG_WEB_ROOTS"] = str(direct)
        via = self.client.get("/api/fs", params={"path": str(direct)})
        self.assertEqual(via.status_code, 200, f"{direct_kind}: {via.text}")
        names = [item["name"] for item in via.json()["entries"]]
        self.assertIn("keep.png", names)
        still = self.client.get("/api/fs", params={"path": str(direct / "alias")})
        self.assertEqual(still.status_code, 403, still.text)
        dotted = self.client.get("/api/fs", params={"path": str(direct) + "/../outside"})
        self.assertEqual(dotted.status_code, 403, dotted.text)

        if kind != "junction":
            jump = self.root / "jump"
            self.assertTrue(_junction(jump, real), "junction was not created")
            os.environ["FIZGIG_WEB_ROOTS"] = str(jump / "dataset")
            jumped = self.client.get("/api/fs", params={"path": str(jump / "dataset")})
            self.assertEqual(jumped.status_code, 200, jumped.text)
            inner = self.client.get("/api/fs", params={"path": str(jump / "dataset" / "alias")})
            self.assertEqual(inner.status_code, 403, inner.text)

        out_real = self.root / "out-real"
        out_real.mkdir()
        (out_real / "run.safetensors").write_bytes(b"lora-via-link")
        kept = out_real / "kept"
        kept.mkdir()
        (kept / "inside.safetensors").write_bytes(b"inside")
        out_link = self.root / "out-link"
        out_kind = _try_link(out_link, out_real)
        self.assertIsNotNone(out_kind)
        hook = out_real / "hook"
        self.assertIsNotNone(_try_link(hook, kept))
        (self.root / "prefs.json").write_text(
            '{"lora_output_dir": "%s"}' % str(out_link).replace("\\", "\\\\"),
            encoding="utf-8",
        )
        downloaded = self.client.get("/api/download", params={"path": str(out_link / "run.safetensors")})
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, b"lora-via-link")
        plain = self.client.get("/api/download", params={"path": str(out_link / "kept" / "inside.safetensors")})
        self.assertEqual(plain.status_code, 200, plain.text)
        leaked = self.client.get("/api/download", params={"path": str(out_link / "hook" / "inside.safetensors")})
        self.assertEqual(leaked.status_code, 403, leaked.text)

    def test_upload_rejects_duplicate_leaf_names(self):
        dup = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[
                ("files", ("same.png", _PNG, "image/png")),
                ("files", ("same.png", _PNG, "image/png")),
            ],
        )
        self.assertEqual(dup.status_code, 422, dup.text)
        self.assertEqual(dup.json()["problems"], ["duplicate name: same.png"])
        self.assertFalse((self.dataset / "same.png").exists())

        forced = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset), "overwrite": "1"},
            files=[
                ("files", ("forced.png", _PNG, "image/png")),
                ("files", ("forced.png", _PNG, "image/png")),
            ],
        )
        self.assertEqual(forced.status_code, 422, forced.text)
        self.assertFalse((self.dataset / "forced.png").exists())

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("a/one.png", _PNG)
            archive.writestr("b/two.png", _PNG)
            archive.writestr("c/one.png", _PNG)
            archive.writestr("d/two.png", _PNG)
        zipped = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[("archive", ("pics.zip", buf.getvalue(), "application/zip"))],
        )
        self.assertEqual(zipped.status_code, 422, zipped.text)
        self.assertEqual(zipped.json()["problems"], ["duplicate name: one.png", "duplicate name: two.png"])
        self.assertFalse((self.dataset / "one.png").exists())
        self.assertFalse((self.dataset / "two.png").exists())

        mixed_buf = io.BytesIO()
        with zipfile.ZipFile(mixed_buf, "w") as archive:
            archive.writestr("nested/twin.png", _PNG)
        mixed = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[
                ("files", ("twin.png", _PNG, "image/png")),
                ("archive", ("pics.zip", mixed_buf.getvalue(), "application/zip")),
            ],
        )
        self.assertEqual(mixed.status_code, 422, mixed.text)
        self.assertEqual(mixed.json()["problems"], ["duplicate name: twin.png"])
        self.assertFalse((self.dataset / "twin.png").exists())


if __name__ == "__main__":
    unittest.main()
