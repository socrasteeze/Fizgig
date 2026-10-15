"""Who gets in: the page's token on every API call, the password when one is set (wrong guesses slow down), the Host
check on a localhost server, no network listening without a password, and Preferences never sending a secret back.

    python -m unittest discover -s checks -p "test_access.py" -v
"""
import os
import unittest
from unittest.mock import patch

import isolate
from fizgig.web import server
from webserve import Served

PASSWORD = "fake-password-not-real"
RUNPOD_KEY = "fake-runpod-key-not-real"


def _handler(**settings):
    return type("TestHandler", (server.Handler,), {"password": None, "local_only": True, **settings})


class NoPassword(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Served(_handler())

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def test_no_token(self):
        for method, path in (("GET", "/api/schema"), ("GET", "/api/run"), ("POST", "/api/start")):
            status, d = self.s.json(method, path, {} if method == "POST" else None, token=False)
            self.assertEqual(status, 403, path)

    def test_wrong_token(self):
        status, _d = self.s.json("GET", "/api/run", headers={"X-Fizgig-Token": "fake-token-not-real"}, token=False)
        self.assertEqual(status, 403)

    def test_token(self):
        status, _d = self.s.json("GET", "/api/run")
        self.assertEqual(status, 200)

    def test_foreign_host(self):
        for host in ("evil.example", "192.0.2.10:8081"):
            status, _d = self.s.json("GET", "/api/run", host=host)
            self.assertEqual(status, 403, host)
            status, _h, _b = self.s.request("GET", "/", host=host, token=False)
            self.assertEqual(status, 403, host)


class WithPassword(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Served(_handler(password=PASSWORD, local_only=False))

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def setUp(self):
        server._login_fails.clear()

    def test_no_cookie(self):
        status, d = self.s.json("GET", "/api/run")
        self.assertEqual(status, 401)
        self.assertTrue(d.get("login"))

    def test_any_host(self):
        # with a password the server is meant for other machines (a pod's proxy, a Tailscale name)
        status, _d = self.s.json("GET", "/api/run", host="fizgig.example.ts.net")
        self.assertEqual(status, 401)

    def test_login(self):
        status, headers, _b = self.s.request("POST", "/api/login", {"password": PASSWORD})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";")[0]
        status, _d = self.s.json("GET", "/api/run", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        status, _d = self.s.json("GET", "/api/run", headers={"Cookie": "fizgig_session=fake-session-not-real"})
        self.assertEqual(status, 401)

    def test_login_needs_token(self):
        status, _d = self.s.json("POST", "/api/login", {"password": PASSWORD}, token=False)
        self.assertEqual(status, 403)

    def test_wrong_passwords_slow_down(self):
        status, _d = self.s.json("POST", "/api/login", {"password": "fake-wrong-guess"})
        self.assertEqual(status, 401)
        status, _d = self.s.json("POST", "/api/login", {"password": "fake-wrong-guess"})
        self.assertEqual(status, 429)
        status, _d = self.s.json("POST", "/api/login", {"password": PASSWORD})     # locked, even the right one
        self.assertEqual(status, 429)


class Prefs(unittest.TestCase):
    def setUp(self):
        isolate.write_prefs(web_password=PASSWORD, runpod_api_key=RUNPOD_KEY)
        self.s = Served()

    def tearDown(self):
        self.s.close()
        isolate.write_prefs()

    def test_secrets_not_sent(self):
        status, _h, body = self.s.request("GET", "/api/prefs")
        self.assertEqual(status, 200)
        self.assertNotIn(PASSWORD.encode(), body)
        self.assertNotIn(RUNPOD_KEY.encode(), body)


class Listen(unittest.TestCase):
    def test_network_needs_password(self):
        isolate.write_prefs()
        env = {k: v for k, v in os.environ.items() if k not in ("FIZGIG_PASSWORD", "VNC_PASSWORD", "RUNPOD_POD_ID")}
        with patch.dict(os.environ, env, clear=True), patch.object(server, "run_server") as run:
            with self.assertRaises(SystemExit):
                server.main(["--host", "0.0.0.0"])
            run.assert_not_called()

    def test_short_password_refused(self):
        with patch.object(server, "run_server") as run:
            with self.assertRaises(SystemExit):
                server.main(["--password", "short"])
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
