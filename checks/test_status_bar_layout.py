"""Check status-bar geometry without importing the trainer or loading models.

    python -m unittest discover -s checks -p test_status_bar_layout.py
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest


def _status_bar_code():
    source = Path(__file__).resolve().parents[1] / "lora_trainer_gui.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {
        "COLORS", "FONT_FAMILY", "FONT_MONO", "ACTIVE_ENTRY_BG", "ACTIVE_ENTRY_FG",
        "APPEARANCE_DARK_CLAM", "APPEARANCE_COMPACT_CLAM", "APPEARANCE_SPACING",
        "SAMPLE_RESOLUTIONS",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id in names
                     for target in node.targets)]
    nodes.extend(node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"resolve_appearance", "appearance_spacing"})
    gui = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "LoRATrainerGUI")
    nodes.extend(node for node in gui.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"setup_styles", "_build_status_bar"})
    scope = {"tk": tk, "ttk": ttk}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
    return scope


class StatusBarLayoutTests(unittest.TestCase):
    def test_sample_controls_fit_at_supported_scales(self):
        code = _status_bar_code()
        for appearance in ("dark-clam", "compact-clam"):
            for dpi in (96, 120, 144):
                with self.subTest(appearance=appearance, dpi=dpi):
                    root = tk.Tk()
                    root.withdraw()
                    try:
                        root.tk.call("tk", "scaling", dpi / 72)
                        gui = SimpleNamespace(master=root, last_used={},
                                              active_appearance=appearance)
                        for name in ("_toggle_status_bar", "_open_queue_window",
                                     "_refresh_queue_button", "_on_sample_override_changed",
                                     "_status_reader_loop", "_poll_status_bar"):
                            setattr(gui, name, lambda *args: None)
                        code["setup_styles"](gui)
                        code["_build_status_bar"](gui, root)
                        root.update_idletasks()
                        bar = gui._status_bar_frame
                        # Each panel must fit with its external vertical margins.
                        for panel in bar.winfo_children():
                            info = panel.pack_info()
                            pad = root.tk.splitlist(str(info["pady"]))
                            margin = sum(map(int, pad)) if len(pad) == 2 else 2 * int(pad[0])
                            self.assertGreaterEqual(
                                bar.winfo_reqheight(), panel.winfo_reqheight() + margin,
                                "Status bar clips a panel at its requested size")
                    finally:
                        root.destroy()


if __name__ == "__main__":
    unittest.main()
