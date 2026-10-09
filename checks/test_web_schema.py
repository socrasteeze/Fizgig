"""Schema endpoint, Host/Origin checks, and the loopback-only bind.

    python -m unittest discover -s checks -p "test_web_schema.py" -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from fizgig.families.registry import FAMILIES
from fizgig.web.app import app, serve


def _assert_no_secret(test, response):
    test.assertNotIn("runpod_api_key", response.text)


class WebSchemaTests(unittest.TestCase):
    def setUp(self):
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        self._client.__exit__(None, None, None)

    def test_schema_for_every_family(self):
        for key in FAMILIES:
            with self.subTest(family=key):
                response = self.client.get("/api/schema", params={"family": key})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["key"], key)
                self.assertIsInstance(body["model_files"], list)
                self.assertIsInstance(body["presets"], list)
                self.assertIsInstance(body["options"], list)
                self.assertIn("lr_hint", body)
                dests = [item["dest"] for item in body["advanced"]]
                self.assertIn("learning_rate", dests)
                _assert_no_secret(self, response)

    def test_unknown_family_is_404(self):
        response = self.client.get("/api/schema", params={"family": "no-such-family"})
        self.assertEqual(response.status_code, 404)
        _assert_no_secret(self, response)

    def test_foreign_host_is_rejected(self):
        with TestClient(app, base_url="http://evil.example") as client:
            response = client.get("/api/schema", params={"family": "klein"})
        self.assertEqual(response.status_code, 403)
        _assert_no_secret(self, response)

    def test_foreign_origin_on_post_is_rejected(self):
        response = self.client.post("/api/ping", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        _assert_no_secret(self, response)

    def test_public_bind_is_refused(self):
        with self.assertRaises(SystemExit):
            serve("0.0.0.0")

    def test_ping_has_no_secret(self):
        response = self.client.post("/api/ping")
        self.assertEqual(response.status_code, 200)
        _assert_no_secret(self, response)


if __name__ == "__main__":
    unittest.main()
