"""Folder roots, upload limits, zip slip, and duplicate names.

    python -m unittest checks.test_web_fs -v
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.web.app import app
from fizgig.web.procs import creationflags

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
    subprocess.check_call(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        stdout=subprocess.DEVNULL,
        creationflags=creationflags(),
    )
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
            creationflags=creationflags(),
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


class _VirtualShare:
    """A local folder that answers to a UNC name, so a root whose resolved form is UNC can be tested offline.

    ``resolve()`` of the local folder gives the UNC name, as it does for a mapped drive. Stat calls on the
    UNC name are answered from the local folder. Every stat call is recorded in ``touched``.
    """

    def __init__(self, unc: str, local: str):
        self.unc = unc
        self.local = local
        self.touched: list[str] = []
        self._patchers: list = []
        self._real = {
            name: getattr(Path, name)
            for name in ("is_dir", "is_file", "exists", "is_symlink", "is_junction", "resolve")
            if hasattr(Path, name)
        }

    @staticmethod
    def _within(text: str, base: str) -> bool:
        low, cut = text.lower(), base.lower()
        return low == cut or low.startswith(cut + os.sep)

    def _map(self, path):
        text = os.fspath(path)
        if self._within(text, self.unc):
            return Path(self.local + text[len(self.unc):])
        return path

    def _stat(self, name):
        real = self._real[name]

        def call(path):
            self.touched.append(os.fspath(path))
            return real(self._map(path))

        return call

    def _resolve(self, path, strict=False):
        text = os.fspath(path)
        if self._within(text, self.local):
            return Path(self.unc + text[len(self.local):])
        if self._within(text, self.unc):
            return Path(text)
        return self._real["resolve"](path, strict)

    def __enter__(self):
        replacements = [(name, self._stat(name)) for name in self._real if name != "resolve"]
        replacements.append(("resolve", lambda path, strict=False: self._resolve(path, strict)))
        for name, fn in replacements:
            patcher = patch.object(Path, name, fn)
            patcher.start()
            self._patchers.append(patcher)
        return self

    def __exit__(self, *exc):
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._patchers.clear()
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
                creationflags=creationflags(),
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

    def test_unc_device_names_case_and_zip_junk(self):
        from fizgig.web import fs
        from fizgig.web.jobs import JobError

        for raw in ("//server/share/pics", r"\\server\share\pics", r"\\?\C:\Windows", r"\\.\PhysicalDrive0"):
            with self.assertRaises(JobError) as caught:
                fs.resolve_dir(raw)
            self.assertEqual(caught.exception.status, 403)
            with self.assertRaises(JobError) as caught:
                fs.resolve_file(raw + "/a.safetensors" if not raw.endswith("0") else raw, "")
            self.assertEqual(caught.exception.status, 403)

        device = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[("files", ("CON.png", _PNG, "image/png"))],
        )
        self.assertEqual(device.status_code, 422, device.text)
        self.assertIn("unsafe", device.text.lower())
        self.assertNotIn("CON.png", [item.name for item in self.dataset.iterdir()])

        response = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[
                ("files", ("IMG.JPG", _PNG, "image/jpeg")),
                ("files", ("img.jpg", _PNG, "image/jpeg")),
            ],
        )
        if os.name == "nt":
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn("duplicate", response.text.lower())
            self.assertFalse((self.dataset / "IMG.JPG").exists())
        else:
            self.assertIn(response.status_code, {200, 422})

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("__MACOSX/._kept.png", _PNG)
            archive.writestr(".DS_Store", b"store")
            archive.writestr("nested/._thumb.png", _PNG)
            archive.writestr("kept.png", _PNG)
        written = self.client.post(
            "/api/upload",
            data={"dest": str(self.dataset)},
            files=[("archive", ("pics.zip", buf.getvalue(), "application/zip"))],
        )
        self.assertEqual(written.status_code, 200, written.text)
        self.assertEqual(written.json()["written"], ["kept.png"])
        self.assertTrue((self.dataset / "kept.png").is_file())
        self.assertFalse((self.dataset / ".DS_Store").exists())
        self.assertFalse((self.dataset / "._kept.png").exists())

        folder = self.root / "jobs" / "evil-out"
        folder.mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({
            "id": "evil-out",
            "status": "done",
            "output_dir": "\\\\no-such-host\\share\\out",
            "created": "2020-01-01T00:00:00Z",
        }), encoding="utf-8")
        started = time.time()
        roots = fs.output_roots()
        self.assertLess(time.time() - started, 2)
        self.assertTrue(any(path == self.dataset.resolve() or path == self.output.resolve() for path in roots))
        self.assertFalse(any("no-such-host" in str(path) for path in roots))

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

    def test_mapped_root_resolves_to_unc_and_its_children_still_work(self):
        from fizgig.web import fs

        unc = r"\\example-nas\share\datasets"
        (self.dataset / "set1").mkdir()
        (self.dataset / "set1" / "a.png").write_bytes(_PNG)
        with _VirtualShare(unc, str(self.dataset)), patch.object(fs, "_win_aliases", lambda path: set()):
            roots = fs.all_roots()
            self.assertTrue(any(str(path).lower() == unc.lower() for path in roots), roots)
            typed = fs.resolve_dir(str(self.dataset / "set1"))
            self.assertEqual(str(typed).lower(), (unc + r"\set1").lower())
            self.assertEqual(fs.resolve_dir(str(typed)), typed)
            picked = fs.resolve_file(str(typed / "a.png"), ".png")
            self.assertEqual(str(picked).lower(), (unc + r"\set1\a.png").lower())

    def test_unc_outside_the_roots_is_refused_without_a_stat(self):
        from fizgig.web import fs
        from fizgig.web.jobs import JobError

        share = _VirtualShare(r"\\example-nas\share\datasets", str(self.dataset))
        with share:
            for raw in (r"\\example-other\share\pics", "//example-other/share/pics"):
                with self.assertRaises(JobError) as caught:
                    fs.resolve_dir(raw)
                self.assertEqual(caught.exception.status, 403)
                with self.assertRaises(JobError) as caught:
                    fs.resolve_file(raw + "/a.safetensors", "")
                self.assertEqual(caught.exception.status, 403)
            self.assertEqual([item for item in share.touched if "example-other" in item.lower()], [])

    def test_job_output_inside_a_dataset_root_downloads(self):
        browse = self.root / "browse"
        run = browse / "mychar" / "out"
        run.mkdir(parents=True)
        (run / "mychar.safetensors").write_bytes(b"lora")
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
            "input_dataset_dir": str(browse),
        }), encoding="utf-8")
        folder = self.root / "jobs" / "finished-run"
        folder.mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({
            "id": "finished-run",
            "kind": "train",
            "family": "sdxl",
            "status": "done",
            "output_dir": str(run),
            "created": "2020-01-01T00:00:00Z",
        }), encoding="utf-8")
        got = self.client.get("/api/download", params={"path": str(run / "mychar.safetensors")})
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.content, b"lora")

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
