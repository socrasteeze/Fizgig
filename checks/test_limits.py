"""Two caps on what a client can make the server do: a huge (or negative) Content-Length on a JSON request, even the
login anyone on the network can reach, is never read into memory; and the caption routes write only caption files,
never a .bat or .py, whatever Caption Extension they are sent.

    python -m unittest discover -s checks -p "test_limits.py" -v
"""
import http.client
import os
import unittest

import isolate
from fizgig.web import captions, server
from webserve import Served


class BodyCap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Served(type("TestHandler", (server.Handler,), {"password": "fake-password-not-real",
                                                                "local_only": False}))

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def setUp(self):
        server._login_fails.clear()

    def login_claiming(self, length):
        """A login whose header claims `length` bytes and sends none: the server must answer without waiting."""
        c = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=5)
        try:
            c.putrequest("POST", "/api/login", skip_accept_encoding=True)
            c.putheader("X-Fizgig-Token", server.TOKEN)
            c.putheader("Content-Length", str(length))
            c.endheaders()
            r = c.getresponse()
            return r.status
        finally:
            c.close()

    def test_huge_body_not_read(self):
        self.assertEqual(self.login_claiming(1 << 30), 401)       # treated as no password, not waited for

    def test_negative_length_not_read(self):
        self.assertEqual(self.login_claiming(-1), 401)

    def test_normal_login_still_works(self):
        status, _h, _b = self.s.request("POST", "/api/login", {"password": "fake-password-not-real"})
        self.assertEqual(status, 200)


class RawCap(unittest.TestCase):
    """A helper's raw-body routes (web/helpers.py pieces) are capped as JSON bodies are."""
    @classmethod
    def setUpClass(cls):
        cls.s = Served()

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def put_claiming(self, length):
        c = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=5)
        try:
            c.putrequest("POST", "/api/helper/put?name=fake_piece", skip_accept_encoding=True)
            c.putheader("X-Fizgig-Token", server.TOKEN)
            c.putheader("Content-Length", str(length))
            c.endheaders()
            return c.getresponse().status
        finally:
            c.close()

    def test_huge_and_negative_not_read(self):
        for length in (1 << 30, -1):
            self.assertEqual(self.put_claiming(length), 400, length)

    def test_a_piece_still_arrives(self):
        status, d = self.s.json("POST", "/api/helper/put?name=fake_piece&offset=0", b"fake piece")
        self.assertEqual((status, d.get("size")), (200, 10))


class CaptionExt(unittest.TestCase):
    def test_only_caption_kinds(self):
        for given, used in ((".caption", ".caption"), ("caption", ".caption"), (".TXT", ".TXT"), ("", ".txt"),
                            (".tags", ".tags"), (".bat", ".txt"), ("py", ".txt"), (".cmd", ".txt"), (".json", ".txt"),
                            (".safetensors", ".txt"), ("../x", ".txt")):
            self.assertEqual(captions.caption_ext(given), used, given)

    def test_save_route_writes_a_caption(self):
        folder = os.path.join(isolate.ROOT, "caption_ext")
        os.makedirs(folder, exist_ok=True)
        s = Served()
        try:
            status, _d = s.json("POST", "/api/captions/save", {"folder": folder, "name": "photo.png",
                                                               "text": "fake caption", "ext": ".bat"})
        finally:
            s.close()
        self.assertEqual(status, 200)
        self.assertEqual(os.listdir(folder), ["photo.txt"])


if __name__ == "__main__":
    unittest.main()
