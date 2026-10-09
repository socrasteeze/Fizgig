"""Host, Origin, and engine-event broadcast.

Nothing here loads a model or touches CUDA.

    python -m unittest checks.test_web_http -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient

from fizgig.web.app import _allowed_origins, _host_name, _serialized_origin, app


class WebHttpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = {
            "FIZGIG_WEB_JOBS": os.environ.get("FIZGIG_WEB_JOBS"),
            "FIZGIG_PREFS_FILE": os.environ.get("FIZGIG_PREFS_FILE"),
            "FIZGIG_NO_PERSIST": os.environ.get("FIZGIG_NO_PERSIST"),
            "FIZGIG_WEB_ROOTS": os.environ.get("FIZGIG_WEB_ROOTS"),
            "FIZGIG_WEB_TAILNET_HOST": os.environ.get("FIZGIG_WEB_TAILNET_HOST"),
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.root)
        os.environ.pop("FIZGIG_WEB_TAILNET_HOST", None)
        self._client = TestClient(app, base_url="http://127.0.0.1:8081")
        self.client = self._client.__enter__()

    def tearDown(self):
        self._client.__exit__(None, None, None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_origin_must_match_scheme_host_and_port(self):
        ok = self.client.post("/api/ping", headers={"Origin": "http://127.0.0.1:8081"})
        self.assertEqual(ok.status_code, 200, ok.text)
        local = self.client.post("/api/ping", headers={"Origin": "http://localhost:8081"})
        self.assertEqual(local.status_code, 200, local.text)
        other_port = self.client.post("/api/ping", headers={"Origin": "http://127.0.0.1:8188"})
        self.assertEqual(other_port.status_code, 403, other_port.text)
        self.assertEqual(other_port.json()["detail"], "forbidden origin")
        missing = self.client.post("/api/ping")
        self.assertEqual(missing.status_code, 200, missing.text)

    def test_tailnet_host_ignores_a_trailing_dot(self):
        self.assertEqual(_host_name("allowed.example."), "allowed.example")
        self.assertEqual(_serialized_origin("https://allowed.example."), "https://allowed.example")
        os.environ["FIZGIG_WEB_TAILNET_HOST"] = "allowed.example."
        self.assertIn("https://allowed.example", _allowed_origins())
        self.assertNotIn("https://allowed.example:8443", _allowed_origins())
        with TestClient(app, base_url="http://allowed.example") as client:
            allowed = client.get("/api/jobs")
            self.assertEqual(allowed.status_code, 200, allowed.text)
            wrong_port = client.post("/api/ping", headers={"Origin": "https://allowed.example:8443"})
            self.assertEqual(wrong_port.status_code, 403, wrong_port.text)
            right = client.post("/api/ping", headers={"Origin": "https://allowed.example"})
            self.assertEqual(right.status_code, 200, right.text)

    def test_engine_events_reach_every_open_stream(self):
        from fizgig.web.app import _event_round
        from fizgig.web.engine_host import events_since, get_host

        host = get_host()
        _batch, cursor = events_since(0)
        host.publish({"event": "done", "gen": 1, "message": "broadcast-token"})
        for _stream in range(2):
            lines, _after = _event_round({}, {}, False, cursor)
            self.assertTrue(any("broadcast-token" in line for line in lines))
        again, after = host.events_since(0)
        self.assertTrue(any(item.get("message") == "broadcast-token" for item in again))
        self.assertGreater(after, cursor)

    def test_new_stream_starts_at_the_current_engine_cursor(self):
        from fizgig.web.engine_host import get_host

        host = get_host()
        host.publish({"event": "loading", "gen": 2, "message": "old-loading-token"})
        host.publish({"event": "error", "gen": 2, "message": "old-error-token"})
        first = self.client.get("/api/events", params={"once": 1})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertNotIn("old-loading-token", first.text)
        self.assertNotIn("old-error-token", first.text)
        self.assertNotIn("event: engine", first.text)

    def test_gizmo_upload_can_overwrite_a_source(self):
        dest = self.root / "clips"
        dest.mkdir()
        (dest / "clip.mp4").write_bytes(b"old")
        first = self.client.post(
            "/api/gizmo/upload",
            data={"dest": str(dest)},
            files={"file": ("clip.mp4", b"new", "video/mp4")},
        )
        self.assertEqual(first.status_code, 409, first.text)
        self.assertEqual(first.json().get("conflicts"), ["clip.mp4"])
        self.assertEqual((dest / "clip.mp4").read_bytes(), b"old")
        second = self.client.post(
            "/api/gizmo/upload",
            data={"dest": str(dest), "overwrite": "1"},
            files={"file": ("clip.mp4", b"new", "video/mp4")},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual((dest / "clip.mp4").read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
