import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_appearance


def _valid_output():
    lines = [
        "APPEARANCE: compact-clam",
        "THEME: clam",
        "BUTTON_PADDING: 8 3",
    ]
    lines.extend(f"TAB: {label}" for label in check_appearance.EXPECTED_TABS)
    return "\n".join(lines) + "\n"


class LaunchTwiceTests(unittest.TestCase):
    def _run_with(self, outputs):
        scratch = Path("appearance-launch-test")
        calls = iter(outputs)
        with patch.object(check_appearance, "_live_digest", return_value=("same",)), \
             patch.object(check_appearance, "_python", return_value=Path("python")), \
             patch.object(check_appearance.subprocess, "run", side_effect=lambda *a, **k: next(calls)), \
             patch.object(Path, "mkdir"), \
             patch.object(Path, "write_text"), \
             redirect_stdout(io.StringIO()) as stdout:
            try:
                check_appearance.launch_twice(scratch)
            except SystemExit as exc:
                output = stdout.getvalue()
                result = (exc.code, "wrote launch-fail.log" in output, output)
            else:
                result = (0, False, stdout.getvalue())
        return result

    def test_widget_tclerror_is_launch_failure(self):
        self.assertFalse(check_appearance._tk_failed("_tkinter.TclError: invalid command name .!button"))
        code, _, _ = self._run_with([
            SimpleNamespace(returncode=1, stdout="", stderr="_tkinter.TclError: invalid command name .!button"),
        ])
        self.assertEqual(code, "launch 1 failed with code 1")

    def test_missing_display_is_environment_failure_and_keeps_log(self):
        code, has_failure_log, _ = self._run_with([
            SimpleNamespace(returncode=1, stdout="", stderr="TclError: no display name and no $DISPLAY environment variable"),
        ])
        self.assertEqual(code, 2)
        self.assertTrue(has_failure_log)

    def test_missing_tk_runtime_is_environment_failure(self):
        code, has_failure_log, _ = self._run_with([
            SimpleNamespace(returncode=1, stdout="", stderr="ImportError: can't find a usable init.tcl"),
        ])
        self.assertEqual(code, 2)
        self.assertTrue(has_failure_log)

    def test_two_valid_launches_pass(self):
        valid = _valid_output()
        code, _, output = self._run_with([
            SimpleNamespace(returncode=0, stdout=valid, stderr=""),
            SimpleNamespace(returncode=0, stdout=valid, stderr=""),
        ])
        self.assertEqual(code, 0)
        self.assertIn("PASS launch 1", output)
        self.assertIn("PASS launch 2", output)


if __name__ == "__main__":
    unittest.main()
