"""Read and edit safetensors metadata inside the configured roots.

The fields and the save rules follow ``_load_metadata_file`` and
``_save_metadata_file``: standard modelspec keys, other keys kept, stale
hashes dropped, tensors not rewritten. The web save also leaves a ``.bak``
of the previous bytes beside the file. ``lora_trainer_gui.py`` is not imported.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from fizgig.web.fs import resolve_file
from fizgig.web.jobs import JobError

_FIELDS = (
    ("title", "modelspec.title"),
    ("author", "modelspec.author"),
    ("license", "modelspec.license"),
    ("tags", "modelspec.tags"),
    ("trigger", "modelspec.trigger_phrase"),
    ("usage_hint", "modelspec.usage_hint"),
    ("description", "modelspec.description"),
)
_THUMB = "modelspec.thumbnail"
_STALE = ("sshs_model_hash", "sshs_legacy_hash", "modelspec.hash_sha256")
_STANDARD = {key for _field, key in _FIELDS} | {_THUMB}
_CHUNK = 1024 * 1024


def _read_header(path: Path) -> tuple[dict, int]:
    """JSON header, and the offset where the tensor bytes start."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(0)
        prefix = handle.read(8)
        if len(prefix) < 8:
            raise JobError(422, {"problems": ["not a safetensors file"]})
        length = int.from_bytes(prefix, "little")
        if length < 2 or 8 + length > size:
            raise JobError(422, {"problems": ["not a safetensors file"]})
        raw = handle.read(length)
    if len(raw) != length:
        raise JobError(422, {"problems": ["not a safetensors file"]})
    try:
        header = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JobError(422, {"problems": ["not a safetensors file"]}) from exc
    if not isinstance(header, dict):
        raise JobError(422, {"problems": ["not a safetensors file"]})
    return header, 8 + length


def _header_bytes(header: dict) -> bytes:
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    raw += b" " * ((8 - (len(raw) % 8)) % 8)
    return len(raw).to_bytes(8, "little") + raw


def _region_equal(src: Path, src_at: int, dst: Path, dst_at: int) -> bool:
    if src.stat().st_size - src_at != dst.stat().st_size - dst_at:
        return False
    with src.open("rb") as left, dst.open("rb") as right:
        left.seek(src_at)
        right.seek(dst_at)
        while True:
            chunk = left.read(_CHUNK)
            if chunk != right.read(_CHUNK):
                return False
            if not chunk:
                return True


def _meta(header: dict) -> dict:
    raw = header.get("__metadata__") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _text(value) -> str:
    return "" if value is None else str(value)


def read(path_text: str) -> dict:
    path = resolve_file(path_text, ".safetensors")
    header, _offset = _read_header(path)
    meta = _meta(header)
    body = {field: _text(meta.get(key)) for field, key in _FIELDS}
    body["thumbnail"] = _text(meta.get(_THUMB))
    body["path"] = str(path)
    body["extra"] = {str(key): _text(value) for key, value in meta.items() if str(key) not in _STANDARD}
    return body


def _thumbnail(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("data:image"):
        return text
    from fizgig.web.fs import IMAGE_EXTENSIONS, all_roots

    path = resolve_file(text, "", all_roots())
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise JobError(422, {"problems": ["Could not read that image."]})
    from fizgig.training.metadata import thumbnail_data_uri

    uri = thumbnail_data_uri(str(path))
    if not uri:
        raise JobError(422, {"problems": ["Could not read that image."]})
    return uri


def save(body: dict) -> dict:
    """Rewrite metadata. Tensor bytes are the original payload, unchanged."""
    path = resolve_file(str((body or {}).get("path") or ""), ".safetensors")
    header, data_offset = _read_header(path)
    meta = _meta(header)
    if "extra" in body and isinstance(body.get("extra"), dict):
        kept = {str(key): _text(value) for key, value in body["extra"].items() if str(key) not in _STANDARD}
    else:
        kept = {str(key): _text(value) for key, value in meta.items() if str(key) not in _STANDARD}
    for stale in _STALE:
        kept.pop(stale, None)
    new_meta = dict(kept)
    for field, key in _FIELDS:
        if field not in body:
            existing = _text(meta.get(key)).strip()
            if existing:
                new_meta[key] = existing
            continue
        value = _text(body.get(field)).strip()
        if value:
            new_meta[key] = value
    if "thumbnail" not in body:
        existing = _text(meta.get(_THUMB)).strip()
        if existing:
            new_meta[_THUMB] = existing
    else:
        thumb = _thumbnail(_text(body.get("thumbnail")))
        if thumb:
            new_meta[_THUMB] = thumb
    out_header = {key: value for key, value in header.items() if key != "__metadata__"}
    if new_meta:
        out_header["__metadata__"] = {key: _text(value) for key, value in new_meta.items()}
    header_blob = _header_bytes(out_header)
    tmp = Path(str(path) + ".tmp")
    bak = Path(str(path) + ".bak")
    try:
        with path.open("rb") as src, tmp.open("wb") as dst:
            dst.write(header_blob)
            src.seek(data_offset)
            shutil.copyfileobj(src, dst, length=_CHUNK)
        if not _region_equal(path, data_offset, tmp, len(header_blob)):
            raise JobError(500, {"detail": "refusing to rewrite tensor bytes"})
        shutil.copy2(path, bak)
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        raise
    return read(str(path))
