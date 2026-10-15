"""Files in and out: uploads keep to their folder (no '..', no hidden or odd names, only the kinds Fizgig trains on),
a zip can't write outside it, the file routes serve only their own kinds, and byte ranges answer 206 / 416.

    python -m unittest discover -s checks -p "test_files.py" -v
"""
import io
import os
import unittest
import zipfile
from urllib.parse import quote

import isolate
from fizgig.web import server
from webserve import Served


def _q(path):
    return quote(path, safe="")


class Uploads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        isolate.write_prefs()
        cls.s = Served()

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def upload(self, folder, name, data=b"fake-bytes", single=False):
        path = f"/api/upload?folder={_q(folder)}&name={_q(name)}" + ("&single=1" if single else "")
        return self.s.json("POST", path, data)

    def test_plain_upload_lands_in_its_folder(self):
        status, d = self.upload("fake_set", "photo 1 (b).png")
        self.assertEqual(status, 200, d)
        self.assertEqual(os.path.normcase(d["folder"]),
                         os.path.normcase(os.path.join(server.UPLOAD_DEFAULT, "fake_set")))
        self.assertTrue(os.path.isfile(os.path.join(d["folder"], "photo 1 (b).png")))

    def test_bad_names_refused(self):
        for folder, name in (("fake_set", "../escape.png"), ("fake_set", "..\\escape.png"), ("../fake_up", "a.png"),
                             ("fake_set", ".hidden.png"), ("fake_set", "CON.png"), ("fake_set", "a.png."),
                             ("fake_set", "a:b.png"), ("", "a.png"), ("fake_set", "")):
            status, _d = self.upload(folder, name)
            self.assertEqual(status, 400, (folder, name))
        self.assertFalse(os.path.exists(os.path.join(isolate.ROOT, "escape.png")))
        self.assertFalse(os.path.exists(os.path.join(isolate.ROOT, "fake_up")))

    def test_only_training_kinds(self):
        for name in ("run.bat", "tool.exe", "page.html", "model.safetensors"):
            status, _d = self.upload("fake_set", name)
            self.assertEqual(status, 400, name)
        for name in ("tool.exe", "data.zip"):
            status, _d = self.upload("", name, single=True)
            self.assertEqual(status, 400, name)
        status, d = self.upload("", "fake_context.safetensors", single=True)
        self.assertEqual(status, 200, d)
        self.assertEqual(os.path.normcase(os.path.dirname(d["path"])), os.path.normcase(server.UPLOAD_FILES))

    def test_zip_stays_in_its_folder(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name in ("../../zip_escape.png", "sub/../../zip_escape2.png", "/abs_escape.png",
                         "C:/drive_escape.png", "inner/ok.png", "ok.txt", "run.bat", ".hidden.png",
                         "__MACOSX/._ok.png"):
                z.writestr(name, b"fake")
        status, d = self.upload("fake_zip", "set.zip", buf.getvalue())
        self.assertEqual(status, 200, d)
        dest = os.path.join(server.UPLOAD_DEFAULT, "fake_zip")
        self.assertEqual(sorted(os.listdir(dest)), sorted(["zip_escape.png", "zip_escape2.png", "abs_escape.png",
                                                           "drive_escape.png", "ok.png", "ok.txt"]))
        self.assertIn("run.bat", d["skipped"])
        for root, _dirs, files in os.walk(isolate.ROOT):
            for f in files:
                if "escape" in f:
                    self.assertEqual(os.path.normcase(root), os.path.normcase(dest), f)

    def test_bad_zip(self):
        status, d = self.upload("fake_zip_bad", "broken.zip", b"not a zip")
        self.assertEqual(status, 400, d)


class Serving(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = os.path.join(isolate.ROOT, "serving")
        os.makedirs(cls.dir, exist_ok=True)
        cls.files = {}
        for name, data in (("song.wav", b"0123456789"), ("notes.txt", b"secret-fake"), ("tool.bat", b"fake"),
                           ("pic.png", b"fake-png"), ("lora.safetensors", b"fake-lora")):
            p = os.path.join(cls.dir, name)
            with open(p, "wb") as f:
                f.write(data)
            cls.files[name] = p
        cls.s = Served()

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def get(self, route, name, headers=None):
        return self.s.request("GET", f"{route}?path={_q(self.files.get(name, name))}", headers=headers)

    def test_media_kinds(self):
        self.assertEqual(self.get("/api/media", "song.wav")[0], 200)
        for name in ("notes.txt", "tool.bat", "lora.safetensors", os.path.join(self.dir, "nothing.wav")):
            self.assertEqual(self.get("/api/media", name)[0], 404, name)

    def test_thumb_kinds(self):
        for name in ("notes.txt", "song.wav", "lora.safetensors"):
            self.assertEqual(self.get("/api/thumb", name)[0], 404, name)

    def test_download_only_checkpoints(self):
        status, headers, body = self.get("/api/download", "lora.safetensors")
        self.assertEqual((status, body), (200, b"fake-lora"))
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        for name in ("notes.txt", "song.wav", "pic.png"):
            self.assertEqual(self.get("/api/download", name)[0], 404, name)

    def test_ranges(self):
        status, headers, body = self.get("/api/media", "song.wav", {"Range": "bytes=2-5"})
        self.assertEqual((status, body, headers.get("Content-Range")), (206, b"2345", "bytes 2-5/10"))
        status, _h, body = self.get("/api/media", "song.wav", {"Range": "bytes=7-"})
        self.assertEqual((status, body), (206, b"789"))
        status, _h, body = self.get("/api/media", "song.wav", {"Range": "bytes=-3"})
        self.assertEqual((status, body), (206, b"789"))
        status, headers, _b = self.get("/api/media", "song.wav", {"Range": "bytes=10-"})
        self.assertEqual((status, headers.get("Content-Range")), (416, "bytes */10"))
        status, _h, _b = self.get("/api/media", "song.wav", {"Range": "bytes=6-2"})
        self.assertEqual(status, 416)

    def test_needs_token(self):
        status, _h, _b = self.s.request("GET", f"/api/media?path={_q(self.files['song.wav'])}", token=False)
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
