"""A prefs.json that isn't JSON (a hand edit's typo) is never saved over: the server's saves refuse and say why, the
app window's size and last page aren't written, a model download doesn't start, and logins still work.

    python -m unittest discover -s checks -p "test_prefs_guard.py" -v
"""
import json
import unittest
from unittest.mock import patch

import isolate
from fizgig import user_data
from fizgig.web import app_window, server
from webserve import Served

BROKEN = '{"klein_model_path": "C:/models/fake.safetensors", "web_password": "fake-password-not-real",\n'


class PrefsGuard(unittest.TestCase):
    def setUp(self):
        with open(user_data.PREFS_FILE, "w", encoding="utf-8") as f:
            f.write(BROKEN)
        self.addCleanup(isolate.write_prefs)

    def assertUntouched(self):
        with open(user_data.PREFS_FILE, encoding="utf-8") as f:
            self.assertEqual(f.read(), BROKEN)

    def test_update_prefs_refuses(self):
        with self.assertRaises(OSError) as cm:
            server.update_prefs({"web_port": "8090"})
        self.assertIn("prefs.json", str(cm.exception))
        self.assertUntouched()

    def test_preferences_save_says_why(self):
        s = Served()
        try:
            status, d = s.json("POST", "/api/prefs", {"changes": {"lora_output_dir": "fake_out"}})
        finally:
            s.close()
        self.assertNotEqual(status, 200)
        self.assertIn("prefs.json", d.get("error", ""))
        self.assertUntouched()

    def test_login_key_not_saved(self):
        old = server._SESSION_KEY[0]
        server._SESSION_KEY[0] = ""
        try:
            self.assertGreaterEqual(len(server._session_key()), 24)
        finally:
            server._SESSION_KEY[0] = old
        self.assertUntouched()

    def test_app_window_leaves_it(self):
        app_window._remember({"width": 800, "height": 600, "x": 0, "y": 0})
        app_window._remember_last("http://127.0.0.1:8081/")
        self.assertUntouched()

    def test_model_download_refused(self):
        with patch.object(server.subprocess, "Popen", side_effect=AssertionError("no download in a test")), \
                self.assertRaises(ValueError) as cm:
            server._start_fetch("klein", token="fake-token-not-real")
        self.assertIn("prefs.json", str(cm.exception))
        self.assertUntouched()


class PrefsReadable(unittest.TestCase):
    def tearDown(self):
        isolate.write_prefs()

    def test_saves_still_work(self):
        isolate.write_prefs(klein_model_path="fake.safetensors")
        server.update_prefs({"web_port": "8090"})
        app_window._remember({"width": 800})
        with open(user_data.PREFS_FILE, encoding="utf-8") as f:
            p = json.load(f)
        self.assertEqual((p["web_port"], p["klein_model_path"], p["app_window"]),
                         ("8090", "fake.safetensors", {"width": 800}))

    def test_no_file_yet(self):
        import os
        os.remove(user_data.PREFS_FILE)
        server.update_prefs({"web_port": "8090"})
        self.assertEqual(server.load_prefs()["web_port"], "8090")


if __name__ == "__main__":
    unittest.main()
