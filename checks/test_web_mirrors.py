"""The desktop functions the web form mirrors still match the pinned source.

    python -m unittest checks.test_web_mirrors -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fizgig.web.mirrors import FUNCTIONS, PINNED, source_hash


class WebMirrorTests(unittest.TestCase):
    def test_pinned_functions_are_unchanged(self):
        for name in FUNCTIONS:
            with self.subTest(function=name):
                current = source_hash(name)
                self.assertEqual(
                    current,
                    PINNED[name],
                    f"{name} changed. Update form_spec.py, then the hash in src/fizgig/web/mirrors.py.",
                )


if __name__ == "__main__":
    unittest.main()
