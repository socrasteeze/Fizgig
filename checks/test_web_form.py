"""GET /api/form for every described family.

    python -m unittest checks.test_web_form -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from fizgig.families.registry import FAMILIES
from fizgig.web.app import app


class WebFormTests(unittest.TestCase):
    def setUp(self):
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        self._client.__exit__(None, None, None)

    def test_form_for_every_family(self):
        for key, desc in FAMILIES.items():
            with self.subTest(family=key):
                response = self.client.get("/api/form", params={"family": key})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["family"], key)
                self.assertGreaterEqual(len(body["fields"]), 50)
                sections = [field["section"] for field in body["fields"]]
                self.assertLess(sections.index("Output"), sections.index("Training Parameters"))
                self.assertLess(sections.index("Training Parameters"), sections.index("Run"))
                covered = {flag for field in body["fields"] for flag in (field["flag"],) if flag}
                advanced_flags = {flag for item in body["advanced"] for flag in item["flags"]}
                self.assertTrue(covered.isdisjoint(advanced_flags))
                self.assertNotIn("runpod_api_key", response.text)
                self.assertTrue(desc.display_name)

    def test_unknown_family_is_404(self):
        response = self.client.get("/api/form", params={"family": "no-such-family"})
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("runpod_api_key", response.text)


if __name__ == "__main__":
    unittest.main()
