"""The page's script parses (a syntax error is a blank page), and every element it looks up by id exists in the page
or is made by the script itself.

    python -m unittest discover -s checks -p "test_page.py" -v
"""
import re
import shutil
import subprocess
import unittest

import isolate

STATIC = isolate.REPO / "src" / "fizgig" / "web" / "static"
GENERATED = ("f_", "note__")         # the Training form's rows and notes, one per setting key


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_script_parses(self):
        out = subprocess.run(["node", "--check", str(STATIC / "app.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_every_looked_up_element_exists(self):
        used = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', self.js))
        made = (set(re.findall(r'id="([A-Za-z0-9_-]+)"', self.html)) | set(re.findall(r'id="([A-Za-z0-9_-]+)"', self.js))
                | set(re.findall(r'id:\s*"([A-Za-z0-9_-]+)"', self.js)))
        missing = sorted(i for i in used - made if not i.startswith(GENERATED))
        self.assertTrue(used)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
