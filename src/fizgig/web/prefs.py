"""Preferences the page is allowed to see.

``DEFAULT_PREFS`` is read from source so the GUI module is not imported. Model rows
follow ``_generic_prefs_section``. Portable directories follow ``save_prefs``.
Secret values never leave this module.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

from fizgig.web.jobs import JobError

_REPO = Path(__file__).resolve().parents[3]
_GUI = _REPO / "lora_trainer_gui.py"
_PORTABLE = {"lora_output_dir", "profiles_dir", "cache_dir"}
_DIR_LABELS = {
    "lora_output_dir": "LoRA output folder",
    "profiles_dir": "Profiles folder",
    "cache_dir": "Cache folder",
    "input_lora_dir": "LoRA browse folder",
    "input_ref_dir": "Reference browse folder",
    "input_dataset_dir": "Dataset browse folder",
}


def secret_key(key: str) -> bool:
    return key == "runpod_api_key" or key.endswith(("_key", "_token", "_secret"))


def prefs_path() -> Path:
    raw = os.environ.get("FIZGIG_PREFS_FILE", "").strip().strip('"')
    return Path(raw) if raw else _REPO / "prefs.json"


def _persist_blocked() -> bool:
    return bool(os.environ.get("FIZGIG_NO_PERSIST")) and not os.environ.get("FIZGIG_PREFS_FILE", "").strip()


_DEFAULTS: dict | None = None


def _defaults() -> dict:
    """``DEFAULT_PREFS`` from the GUI source, plus empty family model keys.

    The source is parsed once. Callers get a copy because they update it.
    """
    global _DEFAULTS
    if _DEFAULTS is not None:
        return dict(_DEFAULTS)
    text = _GUI.read_text(encoding="utf-8")
    tree = ast.parse(text)
    found = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "DEFAULT_PREFS":
                found = ast.literal_eval(node.value)
    if not isinstance(found, dict):
        raise JobError(500, {"detail": "DEFAULT_PREFS is missing"})
    from fizgig.families.registry import FAMILIES

    for desc in FAMILIES.values():
        for key in desc.pref_keys:
            found.setdefault(key, "")
    _DEFAULTS = found
    return dict(found)


def _resolve(value: str) -> str:
    """Mirrors ``_resolve_pref_path``."""
    if not value:
        return value
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(str(_REPO), value))


def _serialize(value: str) -> str:
    """Mirrors ``_serialize_pref_path``."""
    if not value:
        return value
    try:
        absolute = os.path.abspath(value)
        relative = os.path.relpath(absolute, os.path.abspath(str(_REPO)))
    except ValueError:
        return os.path.abspath(value).replace(os.sep, "/")
    if relative.startswith("..") or os.path.isabs(relative):
        return os.path.abspath(value).replace(os.sep, "/")
    return relative.replace(os.sep, "/")


def _raw() -> dict:
    path = prefs_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stored() -> dict:
    """On-disk prefs. A file that cannot be parsed is refused, not replaced."""
    path = prefs_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JobError(409, {"detail": "prefs.json could not be read"}) from exc
    if not isinstance(data, dict):
        raise JobError(409, {"detail": "prefs.json could not be read"})
    return data


def _merged() -> dict:
    prefs = _defaults()
    prefs.update(_raw())
    for key in _PORTABLE:
        if isinstance(prefs.get(key), str):
            prefs[key] = _resolve(prefs[key])
    return prefs


def _sections(prefs: dict) -> list:
    from fizgig.families.registry import training_families

    sections = []
    for desc in training_families():
        files = []
        for item in desc.model_files:
            hint = item.hint or (("" if item.required else "OPTIONAL — ") + (item.note or ""))
            download = ""
            if item.repo and item.path:
                download = f"https://huggingface.co/{item.repo}/blob/main/{item.path}"
            files.append({
                "key": item.pref_key,
                "label": item.label,
                "value": str(prefs.get(item.pref_key) or ""),
                "required": bool(item.required),
                "hint": hint,
                "download": download,
            })
        sections.append({"key": desc.key, "name": desc.display_name, "files": files})
    return sections


def _model_keys(prefs: dict) -> set[str]:
    keys = set()
    for section in _sections(prefs):
        for item in section["files"]:
            keys.add(item["key"])
    return keys


def view() -> dict:
    prefs = _merged()
    defaults = _defaults()
    directories = []
    for key in defaults:
        if not key.endswith("_dir"):
            continue
        directories.append({
            "key": key,
            "label": _DIR_LABELS.get(key, key.replace("_", " ")),
            "value": str(prefs.get(key) or ""),
        })
    raw = _raw()
    seen = set()
    secrets = []
    for key in list(defaults) + [key for key in raw if key not in defaults]:
        if key in seen or not secret_key(key):
            continue
        seen.add(key)
        present = str(raw.get(key) or "").strip()
        secrets.append({"key": key, "set": bool(present)})
    return {
        "directories": directories,
        "families": _sections(prefs),
        "secrets": secrets,
        "web_caption_trigger": str(prefs.get("web_caption_trigger") or ""),
    }


def roots_from_prefs() -> dict:
    """Resolved directory and model paths for the folder browser. Values stay on the server."""
    return _merged()


def save(values: dict) -> dict:
    if _persist_blocked():
        return view()
    raw = _stored()
    defaults = _defaults()
    allowed = {key for key in defaults if key.endswith("_dir")} | _model_keys(_merged())
    allowed.add("web_caption_trigger")
    for key, value in (values or {}).items():
        if secret_key(key) or key not in allowed:
            continue
        text = "" if value is None else str(value)
        raw[key] = _serialize(text) if key in _PORTABLE else text
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return view()
