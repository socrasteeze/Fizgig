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
    "_apply_queue_item",
    "_canon_arch",
    "_generic_prefs_section",
    "save_prefs",
    "_resolve_pref_path",
    "_serialize_pref_path",
    "create_start_tab",
    "_analyze_dataset",
    "create_caption_generator",
    "generate_captions",
    "convert_images",
    "_resize_image",
    "_prep_target_area",
    "_get_face_selection_mode",
    "_resize_only_images",
    "_face_crop_only_images",
    "_auto_prep_images",
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
    "_apply_queue_item": "645a00ccaaa76f0fdfa61e56b53d049364aa496f1e19764fcba82cb24080f5d0",
    "_canon_arch": "1981e42ccde8e61df60c15ac39a7416281e2cf75e7c1f645c20a13f89cbe8ac6",
    "_generic_prefs_section": "05ba0d4559f0f766bb7cfe92fb4af0eb4029c8f52b0b66658ccf75cad551d260",
    "save_prefs": "0e8800376968a78e730f14204a97580ec47e6904ea8094b71771a0efea7ba5d2",
    "_resolve_pref_path": "167a0772a2a908ac6e0ea3dd43acd4216fdfa38d477474b6a41682f405d56dc5",
    "_serialize_pref_path": "ad9d584d9fe085ece71c4610c68ce2c4a5dd418086fe81dec6b845f0300d83f1",
    "create_start_tab": "e1ae99aacaec0abbf216633cf5f5ddbdc67bf9ecaa16b53c7338e93b6eeb219e",
    "_analyze_dataset": "54b38be6fb163e5d8aaf03e5b1d7d9ecdd45be82a5a7ae50f304ea01e96033de",
    "create_caption_generator": "181b8eb6fe7d45e8335d8808233f699012ebd7e50d5ec2efd03c108778c8ac4e",
    "generate_captions": "0afb5df95206abb4d51bfefe15a3627f35b9248a0235c9e2d7eb8bdf7c7e5601",
    "convert_images": "918d7d04f9e71baf30dace4bcbefa18d08ef02f1974868a74e01adf6336f2efd",
    "_resize_image": "4ac262fdfbc2408f2faa77071382754d4cd8bc4719633d57647dbe8995b0a850",
    "_prep_target_area": "20858d3ea7fadccdc683b88f89f583ff6f591d6f78144738edf6d971cc7b7965",
    "_get_face_selection_mode": "bb175aae5e68b6c45539dd150281873534a18ee362b65f911273bb863bc3d07f",
    "_resize_only_images": "da03817deb60fd07ead1d0a2277de1dda5792ae117366770bb05ba556ae22a6b",
    "_face_crop_only_images": "2a9b302452cbc5dd9f68aa99b32339d88b0bfe7862d622b153ec02fde42ef15b",
    "_auto_prep_images": "6c997d194c1a134501ddf63f058530680a652f0f04eeefd83bc67028a2b05b16",
}
