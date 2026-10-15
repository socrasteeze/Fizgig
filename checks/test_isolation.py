"""The tests' own guard: every web module's data paths are in the temp folder, not the real user_data/.

    python -m unittest discover -s checks -p "test_isolation.py" -v
"""
import importlib
import os
import pkgutil
import unittest

import isolate
from fizgig import user_data
from fizgig import web


class Isolation(unittest.TestCase):
    def test_user_data_moved(self):
        root = os.path.normcase(isolate.ROOT)
        for p in (user_data.USER_DATA, user_data.PREFS_FILE, user_data.LAST_USED_FILE, user_data.PRESETS_DIR,
                  user_data.MODELS_DIR):
            self.assertTrue(os.path.normcase(p).startswith(root), p)

    def test_migrate_off(self):
        self.assertIsNone(user_data.migrate())

    def test_no_web_module_holds_a_real_path(self):
        # every module, so a constant a later upstream sync adds is caught too (app_window opens a window: its
        # paths are read here without starting it)
        for m in pkgutil.iter_modules(web.__path__):
            if m.name != "__main__":
                importlib.import_module(f"fizgig.web.{m.name}")
        self.assertEqual(isolate.leaks(), [])


if __name__ == "__main__":
    unittest.main()
