"""SHA-256 of the desktop functions the web form and the job supervisor mirror.

The hash is of the function source from ``ast.get_source_segment``, with line endings
normalised to ``\\n``. A mismatch means the desktop function changed: update the mirror
(``form_spec.py``, ``inputs.py``, ``jobs.py``, or ``system.py``), then replace the hash.
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
    "_confirm_disk_headroom",
    "_confirm_resume_has_epochs_left",
    "_pause_training",
    "_resume_training",
    "_on_training_subprocess_exited",
    "_detect_latest_state_dir",
    "_on_sample_override_changed",
    "stop_training",
    "_read_vram",
    "_status_reader_loop",
    "ft_checkpoint_continuation",
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
    "_confirm_disk_headroom": "d0819b4c4a4fa8e9f8b9e3311b06442c299a3f4c04533b12dcedde81896ad258",
    "_confirm_resume_has_epochs_left": "2e90805aac98ad9f1daf982a4fc9e01652aeb4cfc0035e9bb47ea7a5ac345620",
    "_pause_training": "d448de6f61d45a35c93fd2f9044d80973628d7445660d113c86d546310b36d75",
    "_resume_training": "34b3beb1116f6c08fc79fcd400bf6a4cff36ac06c38eb4825f863a3b330973e9",
    "_on_training_subprocess_exited": "55af21ce1e7865241fba7cb22f638fd2277f1ec3f6ddd3216cec4428b56c8c57",
    "_detect_latest_state_dir": "051e42b92fe0659808dd5e0059fe2805aa02c20101357855db010698b659ede6",
    "_on_sample_override_changed": "e57733885e924ba57e9d125ba299588d1b0b9ec4ba9ee50ae8bcc5ef544b4ced",
    "stop_training": "84f2a3c935e96c55fd766715d41b26f7ba6f8fafbae4427ddf8f6beec0560119",
    "_read_vram": "01871bcdb025528d88e819893b17986e4fb6b607375ca91f25c54a9324ba3632",
    "_status_reader_loop": "f898ebf91aec0982a1d305a8ecb49d25a8cd0eca135aaa8ae2fb9774006d22fa",
    "ft_checkpoint_continuation": "293e4e9aebbb31cf074591f2b1fd5d262690ea706521bd4d97557f40ed678369",
}
