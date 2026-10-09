"""Folder listing, upload, and LoRA download inside configured roots.

A path is refused when it contains ``..``, when a symlink or junction sits
strictly below the matching root, or when the resolved path is outside the
roots. The root itself may be a link, or sit under one.
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from fizgig.web.jobs import JobError, jobs_root

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
_DEFAULT_LIMIT = 64 * 1024 * 1024


def _limit() -> int:
    raw = os.environ.get("FIZGIG_WEB_UPLOAD_MAX", "").strip()
    if not raw:
        return _DEFAULT_LIMIT
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_LIMIT


def _linked(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def _any_link(path: Path) -> bool:
    cursor = path
    while True:
        if _linked(cursor):
            return True
        parent = cursor.parent
        if parent == cursor:
            return False
        cursor = parent


def _dotdot(text: str) -> bool:
    return any(part == ".." for part in text.replace("\\", "/").split("/"))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _add(found: list[Path], raw) -> None:
    text = str(raw or "").strip()
    if not text:
        return
    path = Path(text)
    if path.is_file():
        path = path.parent
    if not path.is_dir():
        return
    try:
        resolved = path.resolve()
    except OSError:
        return
    if resolved not in found:
        found.append(resolved)


def _start_folder() -> str:
    path = jobs_root() / "start.json"
    if not path.is_file():
        return ""
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str((data or {}).get("folder") or "").strip() if isinstance(data, dict) else ""


def _prefs() -> dict:
    from fizgig.web.prefs import roots_from_prefs

    return roots_from_prefs()


def all_roots() -> list[Path]:
    prefs = _prefs()
    found: list[Path] = []
    _add(found, prefs.get("input_dataset_dir"))
    _add(found, Path(__file__).resolve().parents[3] / "dataset")
    _add(found, prefs.get("lora_output_dir"))
    _add(found, prefs.get("profiles_dir"))
    _add(found, prefs.get("cache_dir"))
    from fizgig.families.registry import FAMILIES

    for desc in FAMILIES.values():
        for item in desc.model_files:
            _add(found, prefs.get(item.pref_key))
    for part in os.environ.get("FIZGIG_WEB_ROOTS", "").split(";"):
        _add(found, part.strip())
    _add(found, _start_folder())
    return found


def dataset_roots() -> list[Path]:
    prefs = _prefs()
    found: list[Path] = []
    _add(found, prefs.get("input_dataset_dir"))
    _add(found, Path(__file__).resolve().parents[3] / "dataset")
    for part in os.environ.get("FIZGIG_WEB_ROOTS", "").split(";"):
        _add(found, part.strip())
    _add(found, _start_folder())
    return found


def output_roots() -> list[Path]:
    prefs = _prefs()
    found: list[Path] = []
    _add(found, prefs.get("lora_output_dir"))
    _add(found, prefs.get("profiles_dir"))
    from fizgig.web.jobs import _each

    for job in _each():
        _add(found, job.get("output_dir"))
    return found


def _under(path: Path, roots: list[Path]) -> bool:
    return any(_inside(path, root) for root in roots)


def _matching_root(path: Path, roots: list[Path]) -> Path | None:
    found = None
    found_len = -1
    for root in roots:
        if not _inside(path, root):
            continue
        try:
            length = len(root.resolve().parts)
        except OSError:
            continue
        if length > found_len:
            found = root
            found_len = length
    return found


def _has_link(path: Path, roots: list[Path]) -> bool:
    """A symlink or junction strictly below the matching root.

    The root and anything above it may be a link, because the user configured
    that root. A path outside every root still fails when any component is a link.
    """
    root = _matching_root(path, roots)
    if root is None:
        return _any_link(path)
    try:
        root_place = os.path.normcase(str(root.resolve()))
    except OSError:
        return True
    cursor = path
    anchor = None
    while True:
        try:
            here = os.path.normcase(str(cursor.resolve()))
        except OSError:
            return True
        if here == root_place:
            anchor = cursor
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    if anchor is None:
        return _any_link(path)
    stop = os.path.normcase(os.path.abspath(os.fspath(anchor)))
    cursor = path
    while os.path.normcase(os.path.abspath(os.fspath(cursor))) != stop:
        if _linked(cursor):
            return True
        parent = cursor.parent
        if parent == cursor:
            return True
        cursor = parent
    return False


def resolve_dir(text: str, roots: list[Path] | None = None) -> Path:
    """An existing directory inside ``roots`` (all roots when omitted)."""
    roots = all_roots() if roots is None else roots
    raw = (text or "").strip()
    if not raw or _dotdot(raw):
        raise JobError(403, {"detail": "path is outside the configured roots"})
    path = Path(raw)
    if not path.is_dir() or _has_link(path, roots) or not _under(path, roots):
        raise JobError(403, {"detail": "path is outside the configured roots"})
    return path.resolve()


def listing(text: str) -> dict:
    roots = all_roots()
    if not (text or "").strip():
        return {
            "path": "",
            "parent": None,
            "entries": [{"name": path.name or str(path), "path": str(path), "kind": "dir"} for path in roots],
        }
    path = resolve_dir(text, roots)
    entries = []
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.lower())
    except OSError as exc:
        raise JobError(403, {"detail": "path is outside the configured roots"}) from exc
    for child in children:
        if _linked(child):
            continue
        if child.is_dir():
            kind = "dir"
        elif child.suffix.lower() in IMAGE_EXTENSIONS:
            kind = "image"
        elif child.is_file():
            kind = "file"
        else:
            continue
        entries.append({"name": child.name, "path": str(child), "kind": kind})
    parent = str(path.parent) if path.parent != path and _under(path.parent, roots) else ""
    return {"path": str(path), "parent": parent, "entries": entries}


def _safe_leaf(name: str) -> str:
    text = (name or "").replace("\\", "/")
    leaf = text.split("/")[-1]
    if text != leaf or leaf in {"", ".", ".."} or leaf.startswith("."):
        raise JobError(422, {"problems": [f"unsafe name: {name}"]})
    if any(ord(char) < 32 or char in '<>:"|?*' for char in leaf):
        raise JobError(422, {"problems": [f"unsafe name: {name}"]})
    return leaf


def _read_limited(upload, limit: int, used: int) -> bytes:
    data = upload.file.read(limit - used + 1)
    if used + len(data) > limit:
        raise JobError(413, {"detail": "upload is too large"})
    return data


def upload(dest: str, files, archive, overwrite: bool) -> dict:
    folder = resolve_dir(dest, dataset_roots())
    limit = _limit()
    planned: list[tuple[str, bytes]] = []
    used = 0
    for upload in files or []:
        leaf = _safe_leaf(upload.filename or "")
        if Path(leaf).suffix.lower() not in IMAGE_EXTENSIONS:
            raise JobError(422, {"problems": [f"not an image: {leaf}"]})
        data = _read_limited(upload, limit, used)
        used += len(data)
        planned.append((leaf, data))
    if archive is not None and (archive.filename or ""):
        blob = _read_limited(archive, limit, used)
        used += len(blob)
        try:
            zf = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile as exc:
            raise JobError(422, {"problems": ["not a zip file"]}) from exc
        with zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                raw_name = info.filename.replace("\\", "/")
                if raw_name.startswith("/") or _dotdot(raw_name) or ":" in raw_name.split("/")[0]:
                    raise JobError(422, {"problems": [f"unsafe zip entry: {info.filename}"]})
                leaf = _safe_leaf(Path(raw_name).name)
                if Path(leaf).suffix.lower() not in IMAGE_EXTENSIONS:
                    raise JobError(422, {"problems": [f"not an image: {leaf}"]})
                if info.file_size > limit or used + info.file_size > limit:
                    raise JobError(413, {"detail": "upload is too large"})
                data = zf.read(info)
                used += len(data)
                if used > limit:
                    raise JobError(413, {"detail": "upload is too large"})
                target = (folder / leaf).resolve()
                if not _inside(target, folder):
                    raise JobError(422, {"problems": [f"unsafe zip entry: {info.filename}"]})
                planned.append((leaf, data))
    if not planned:
        raise JobError(422, {"problems": ["nothing to upload"]})
    seen: set[str] = set()
    duplicates: list[str] = []
    for name, _data in planned:
        if name in seen:
            if name not in duplicates:
                duplicates.append(name)
        else:
            seen.add(name)
    if duplicates:
        raise JobError(422, {"problems": [f"duplicate name: {name}" for name in duplicates]})
    conflicts = [name for name, _data in planned if (folder / name).exists()]
    if conflicts and not overwrite:
        raise JobError(409, {"conflicts": conflicts})
    written = []
    for name, data in planned:
        target = folder / name
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        written.append(name)
    return {"written": written, "folder": str(folder)}


def resolve_file(text: str, suffix: str, roots: list[Path] | None = None) -> Path:
    """An existing file inside ``roots`` (all roots when omitted).

    ``suffix`` is required when it is not empty (``.safetensors``, ``.html``).
    """
    raw = (text or "").strip()
    if not raw or _dotdot(raw):
        raise JobError(403, {"detail": "path is outside the configured roots"})
    path = Path(raw)
    if suffix and path.suffix.lower() != suffix.lower():
        raise JobError(422, {"problems": [f"not a {suffix} file"]})
    roots = all_roots() if roots is None else roots
    if not path.is_file() or _has_link(path, roots) or not _under(path, roots):
        raise JobError(403, {"detail": "path is outside the configured roots"})
    return path.resolve()


def lora_file(text: str) -> Path:
    raw = (text or "").strip()
    if not raw or _dotdot(raw):
        raise JobError(403, {"detail": "path is outside the configured roots"})
    path = Path(raw)
    if path.suffix.lower() != ".safetensors":
        raise JobError(404, {"detail": "no such file"})
    roots = output_roots()
    if not path.is_file() or _has_link(path, roots) or not _under(path, roots):
        raise JobError(403, {"detail": "path is outside the configured roots"})
    return path.resolve()
