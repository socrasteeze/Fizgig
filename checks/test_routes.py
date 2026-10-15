"""Every /api/... address the page's script calls is one the server answers (a renamed route on either side is a
button that silently does nothing). /api/studio/, /api/refmod/ and /api/pods/ hand the rest of the address to one
function each (_studio_post, _refmod_post, _pods_post): their part is looked up in that function.

    python -m unittest discover -s checks -p "test_routes.py" -v
"""
import re
import unittest

import isolate

WEB = isolate.REPO / "src" / "fizgig" / "web"
PREFIXED = {"/api/studio/": "_studio_post", "/api/refmod/": "_refmod_post", "/api/pods/": "_pods_post"}


def _function(source, name):
    start = source.index(f"\ndef {name}(")
    end = source.find("\ndef ", start + 1)
    return source[start:end if end > 0 else len(source)]


def unserved(js, py):
    """The /api/... addresses in `js` that `py` doesn't answer."""
    missing = []
    for path in sorted(set(re.findall(r'["`](/api/[A-Za-z0-9_/.-]*)', js))):
        if f'"{path}"' in py:
            continue
        prefix = next((p for p in PREFIXED if path.startswith(p)), None)
        if prefix and f'"{path[len(prefix):]}"' in _function(py, PREFIXED[prefix]):
            continue
        missing.append(path)
    return missing


class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (WEB / "static" / "app.js").read_text(encoding="utf-8")
        cls.py = (WEB / "server.py").read_text(encoding="utf-8")

    def test_page_calls_are_served(self):
        self.assertGreater(len(set(re.findall(r'["`](/api/[A-Za-z0-9_/.-]*)', self.js))), 100)
        self.assertEqual(unserved(self.js, self.py), [])

    def test_a_missing_route_is_caught(self):
        js = 'api("/api/fake-route-not-real"); api("/api/studio/fake_action", {}); api(`/api/run`);'
        self.assertEqual(unserved(js, self.py), ["/api/fake-route-not-real", "/api/studio/fake_action"])


if __name__ == "__main__":
    unittest.main()
