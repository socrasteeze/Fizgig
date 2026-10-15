"""The web server answers: the page with its token, its script and styles, the schema; and importing it loads no
torch (the page must come up on a machine still installing).

    python -m unittest discover -s checks -p "test_serve.py" -v
"""
import subprocess
import sys
import unittest

import isolate
from fizgig.web import server
from webserve import Served


class Serve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Served()

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def test_page_carries_token(self):
        status, _h, body = self.s.request("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(server.TOKEN.encode(), body)
        self.assertNotIn(b"__FIZGIG_TOKEN__", body)

    def test_static_files(self):
        for path in ("/app.js", "/style.css", "/qrcode.js", "/icon.png", "/manifest.webmanifest"):
            status, _h, body = self.s.request("GET", path, token=False)
            self.assertEqual(status, 200, path)
            self.assertTrue(body, path)

    def test_schema_lists_families(self):
        status, d = self.s.json("GET", "/api/schema")
        self.assertEqual(status, 200)
        self.assertTrue(d.get("families"))

    def test_unknown_path(self):
        status, _h, _b = self.s.request("GET", "/nothing-here", token=False)
        self.assertEqual(status, 404)


class NoTorch(unittest.TestCase):
    def test_server_import_skips_torch(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import isolate; "
                "print('torch' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code, str(isolate.REPO / "checks")], capture_output=True,
                             text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "False")


if __name__ == "__main__":
    unittest.main()
