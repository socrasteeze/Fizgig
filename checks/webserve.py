"""A real Fizgig web server on a free localhost port, for tests (import isolate first)."""
import http.client
import json
import threading

from fizgig.web import server


class Served:
    """The server in a thread. `handler` defaults to server.Handler with no password; pass a subclass to change
    its class settings (password, local_only) without touching the real one."""

    def __init__(self, handler=None):
        self.handler = handler or type("TestHandler", (server.Handler,), {"password": None, "local_only": True})
        self.srv = server._Server(("127.0.0.1", 0), self.handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(5)

    def request(self, method, path, body=None, token=True, host=None, headers=None):
        """(status, headers, body bytes). JSON bodies are sent as JSON; the page's token goes along unless
        token=False."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        if token:
            h["X-Fizgig-Token"] = server.TOKEN
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        try:
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def json(self, method, path, body=None, **kw):
        status, headers, raw = self.request(method, path, body, **kw)
        return status, json.loads(raw or b"{}")
