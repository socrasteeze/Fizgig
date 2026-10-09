"""SHA-256 of the desktop functions the web form mirrors.

The hash is of the function source from ``ast.get_source_segment``, with line endings
normalised to ``\\n``. A mismatch means the desktop function changed: update
``form_spec.py`` (and ``inputs.py`` when the launch inputs changed), then replace the hash.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

_GUI = Path(__file__).resolve().parents[3] / "lora_trainer_gui.py"

FUNCTIONS = (
    "create_training_settings",
    "_apply_training_arch_visibility",
    "_generic_training_visibility",
    "_family_edit_rows",
    "_family_launch_inputs",
)


def source_hash(name: str, text: str | None = None) -> str:
    if text is None:
        text = _GUI.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            if not segment:
                break
            normalised = segment.replace("\r\n", "\n").replace("\r", "\n")
            return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    raise KeyError(name)


# Recomputed from lora_trainer_gui.py. Replace a value only after updating the mirror.
PINNED = {
    "create_training_settings": "6806d8969587b1119f620228615777c4b0933cfe32da001615d77ed3dac794fd",
    "_apply_training_arch_visibility": "c8601b8cc1997969bcfb13f494a15e02645dd9e3b2bd3a134e4e16a27a5b1b7d",
    "_generic_training_visibility": "4c064f281ef64d3495f41a4d0957fbebd90755d64015174b95de6239a75ff7fd",
    "_family_edit_rows": "c3b4a260fc8836acb2bfb8e0990ae66ef513474e1b2e4349ea751e20a1c8f952",
    "_family_launch_inputs": "cec1321b35d5a172dddc49bfa4894f3728278b88aa1d006b23eb844884784119",
}
