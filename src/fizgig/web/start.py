"""The shared training folder.

Mirrors the Start tab's folder (``create_start_tab``) and the counts from
``_analyze_dataset``. Missing captions are images with no sibling ``.txt``.
"""
from __future__ import annotations

import json
import os

from fizgig.web.fs import IMAGE_EXTENSIONS, resolve_dir, within_roots
from fizgig.web.jobs import JobError, jobs_root

_FILE = "start.json"


def _path():
    return jobs_root() / _FILE


def _in_roots(text: str) -> bool:
    try:
        within_roots(text)
    except JobError:
        return False
    return True


def folder() -> str:
    path = _path()
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("folder") or "").strip()


def summarize(path: str) -> dict:
    """Image count, caption count, and images that have no caption file."""
    text = (path or "").strip()
    if not text or not _in_roots(text) or not os.path.isdir(text):
        return {"folder": text, "images": 0, "captions": 0, "missing": 0, "ready": False}
    images = []
    captions = 0
    try:
        names = os.listdir(text)
    except OSError:
        return {"folder": text, "images": 0, "captions": 0, "missing": 0, "ready": False}
    for name in names:
        full = os.path.join(text, name)
        if not os.path.isfile(full):
            continue
        if name.endswith(".txt"):
            captions += 1
        if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
            images.append(name)
    missing = 0
    for name in images:
        stem = os.path.splitext(name)[0]
        if not os.path.isfile(os.path.join(text, stem + ".txt")):
            missing += 1
    return {
        "folder": text,
        "images": len(images),
        "captions": captions,
        "missing": missing,
        "ready": True,
    }


def current() -> dict:
    return summarize(folder())


def set_folder(path: str) -> dict:
    text = (path or "").strip()
    if text:
        text = str(resolve_dir(text))
    dest = _path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"folder": text}, indent=2), encoding="utf-8")
    os.replace(tmp, dest)
    return summarize(text)


def require_folder(path: str | None = None) -> str:
    text = (path or "").strip() or folder()
    if not text:
        raise JobError(422, {"problems": ["Pick a training image folder on the Start tab first."]})
    within_roots(text)
    if not os.path.isdir(text):
        raise JobError(422, {"problems": ["The training image folder does not exist."]})
    return str(resolve_dir(text))
