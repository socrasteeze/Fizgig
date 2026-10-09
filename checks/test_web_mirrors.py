"""The desktop functions the web form mirrors still match the pinned source.

    python -m unittest checks.test_web_mirrors -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fizgig.web.mirrors import (
    CONVERT_FUNCTIONS,
    CONVERT_PINNED,
    FUNCTIONS,
    GIZMO_FUNCTIONS,
    GIZMO_PINNED,
    PINNED,
    _CONVERT,
    _GIZMO,
    source_hash,
)


class WebMirrorTests(unittest.TestCase):
    def test_pinned_functions_are_unchanged(self):
        for name in FUNCTIONS:
            with self.subTest(function=name):
                current = source_hash(name)
                self.assertEqual(
                    current,
                    PINNED[name],
                    f"{name} changed. Update the web mirror, then the hash in src/fizgig/web/mirrors.py.",
                )

    def test_gizmo_and_converter_pins(self):
        pairs = (
            (GIZMO_FUNCTIONS, GIZMO_PINNED, _GIZMO),
            (CONVERT_FUNCTIONS, CONVERT_PINNED, _CONVERT),
        )
        for names, pinned, path in pairs:
            for name in names:
                with self.subTest(function=name):
                    current = source_hash(name, file=path)
                    self.assertEqual(
                        current,
                        pinned[name],
                        f"{name} changed. Update the web mirror, then the hash in src/fizgig/web/mirrors.py.",
                    )


if __name__ == "__main__":
    unittest.main()
