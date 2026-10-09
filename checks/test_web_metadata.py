"""Metadata read and save. Tensor bytes stay put. A path outside the roots is refused.

    python -m unittest checks.test_web_metadata -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.web.app import app

_BODY = b"\x00\x00\x80?"
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _pack(header: dict, body: bytes) -> bytes:
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    raw += b" " * ((8 - (len(raw) % 8)) % 8)
    return len(raw).to_bytes(8, "little") + raw + body


def _tail(data: bytes) -> bytes:
    length = int.from_bytes(data[:8], "little")
    return data[8 + length:]


def _header(data: bytes) -> dict:
    length = int.from_bytes(data[:8], "little")
    return json.loads(data[8:8 + length])


class WebMetadataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.folder = self.root / "loras"
        self.outside = self.root / "outside"
        self.folder.mkdir()
        self.outside.mkdir()
        self._env = {
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
        }
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.folder)
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        (self.root / "prefs.json").write_text("{}", encoding="utf-8")
        self.path = self.folder / "demo.safetensors"
        self.original = _pack({
            "w": {"dtype": "F32", "shape": [1], "data_offsets": [0, len(_BODY)]},
            "__metadata__": {
                "modelspec.title": "Old",
                "modelspec.author": "Ada",
                "author_note": "keep me",
                "sshs_model_hash": "fade",
            },
        }, _BODY)
        self.path.write_bytes(self.original)
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

    def test_edit_keeps_tensors_and_refuses_outside(self):
        loaded = self.client.get("/api/metadata", params={"path": str(self.path)})
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertEqual(loaded.json()["title"], "Old")
        self.assertEqual(loaded.json()["extra"]["author_note"], "keep me")

        saved = self.client.put("/api/metadata", json={
            "path": str(self.path),
            "title": "New title",
            "author": "Ada",
            "license": "MIT",
            "tags": "style",
            "trigger": "ohwx",
            "usage_hint": "Say ohwx.",
            "description": "A small edit.",
            "thumbnail": "",
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        data = self.path.read_bytes()
        self.assertEqual(_tail(data), _BODY)
        self.assertEqual(_tail(data), _tail(self.original))
        header = _header(data)
        self.assertEqual(header["w"]["data_offsets"], [0, len(_BODY)])
        meta = header["__metadata__"]
        self.assertEqual(meta["modelspec.title"], "New title")
        self.assertEqual(meta["modelspec.trigger_phrase"], "ohwx")
        self.assertEqual(meta["author_note"], "keep me")
        self.assertNotIn("sshs_model_hash", meta)
        bak = Path(str(self.path) + ".bak")
        self.assertTrue(bak.is_file())
        self.assertEqual(bak.read_bytes(), self.original)

        image = self.folder / "thumb.png"
        image.write_bytes(_PNG)
        with_thumb = self.client.put("/api/metadata", json={
            "path": str(self.path),
            "title": "New title",
            "thumbnail": str(image),
        })
        self.assertEqual(with_thumb.status_code, 200, with_thumb.text)
        self.assertTrue(with_thumb.json()["thumbnail"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(_tail(self.path.read_bytes()), _BODY)

        other = self.outside / "other.safetensors"
        other.write_bytes(self.original)
        refused = self.client.get("/api/metadata", params={"path": str(other)})
        self.assertEqual(refused.status_code, 403, refused.text)
        refused_put = self.client.put("/api/metadata", json={"path": str(other), "title": "nope"})
        self.assertEqual(refused_put.status_code, 403, refused_put.text)
        dotted = self.client.get("/api/metadata", params={"path": str(self.folder / ".." / "outside" / "other.safetensors")})
        self.assertEqual(dotted.status_code, 403, dotted.text)
        self.assertEqual(other.read_bytes(), self.original)

    def test_large_file_is_not_loaded_into_memory(self):
        body = b"\xab" * (4 * 1024 * 1024)
        big = self.folder / "big.safetensors"
        original = _pack({
            "w": {"dtype": "U8", "shape": [len(body)], "data_offsets": [0, len(body)]},
            "__metadata__": {"modelspec.title": "Old", "author_note": "keep me"},
        }, body)
        big.write_bytes(original)
        limit = 64 * 1024
        real = Path.read_bytes

        def guarded(self):
            try:
                size = self.stat().st_size
            except OSError:
                return real(self)
            if size > limit:
                raise AssertionError("read_bytes loaded %s bytes" % size)
            return real(self)

        with patch.object(Path, "read_bytes", guarded):
            loaded = self.client.get("/api/metadata", params={"path": str(big)})
            self.assertEqual(loaded.status_code, 200, loaded.text)
            self.assertEqual(loaded.json()["title"], "Old")
            saved = self.client.put("/api/metadata", json={
                "path": str(big),
                "title": "New title",
            })
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["title"], "New title")
        data = big.read_bytes()
        length = int.from_bytes(data[:8], "little")
        self.assertEqual(length % 8, 0)
        self.assertEqual(data[8 + length:], body)
        self.assertEqual(_header(data)["w"]["data_offsets"], [0, len(body)])
        bak = Path(str(big) + ".bak")
        self.assertTrue(bak.is_file())
        self.assertEqual(bak.read_bytes(), original)
        self.assertFalse(Path(str(big) + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
