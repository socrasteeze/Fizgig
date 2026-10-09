"""Widget-free training queue.

Items live in ``<jobs root>/queue.json``. Import maps a desktop
``presets/training_queue.json`` entry the way ``_apply_queue_item`` loads one
(architecture first, then preset, model options, folder, concept folders, samples).
``lora_trainer_gui.py`` is not imported. Hashes live in ``mirrors.py``.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from fizgig.families.registry import by_gui_label
from fizgig.web.jobs import JobError, _device_index, _now, jobs_root

_LOCK = threading.Lock()
_SEEN: dict[str, str] = {}
_ACTIVE_SEEN: set[str] = set()
_READY: set[str] = set()
_HOLD: set[int] = set()
_DEVICE: dict[str, int] = {}

# LoRATrainerGUI._canon_arch / _ARCH_ALIASES. Old Base Model labels.
_ARCH_ALIASES = {
    "MiniMax H3 (experimental)": "MiniMax H3",
    "Krea 2 (experimental)": "Krea 2",
    "MiniMax H3 (driver)": "MiniMax H3",
    "Klein (driver)": "Flux 2 Klein Base 9B",
}

# Samples-tab widget keys stored on a desktop item, and the launch.plan names.
_SAMPLES = {
    "SAMPLE_ENABLED": "enabled",
    "SAMPLE_WIDTH": "width",
    "SAMPLE_HEIGHT": "height",
    "SAMPLE_STEPS": "steps",
    "SAMPLE_SEED": "seed",
    "SAMPLE_EVERY_N_EPOCHS": "every",
    "SAMPLE_EVERY_N_STEPS": "every_steps",
    "SAMPLE_AT_FIRST": "at_first",
    "SAMPLE_FLOW_SHIFT": "flow_shift",
    "SAMPLE_NEGATIVE": "negative",
    "SAMPLE_CFG_SCALE": "cfg",
    "SAMPLE_FRAMES": "frames",
}
_SAMPLE_BOOLS = {"enabled", "at_first"}
_VALUE_SAMPLES = {"FAMILY_TURBO_STEPS", "FAMILY_TURBO_PACE"}


def _path() -> Path:
    return jobs_root() / "queue.json"


def _read() -> list[dict]:
    path = _path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("id")]


def _write(items: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(items, indent=2)
    # Windows denies the replace while a reader still has queue.json open.
    for _ in range(25):
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.02)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _label(item: dict) -> str:
    values = item.get("values") or {}
    name = str(values.get("LORA_NAME") or "").strip()
    if name:
        return name
    folder = str(values.get("image_folder") or (item.get("context") or {}).get("image_folder") or "")
    base = Path(folder).name
    return base or str(item.get("family") or "")


def _public(item: dict) -> dict:
    return {
        "id": item.get("id") or "",
        "family": item.get("family") or "",
        "values": item.get("values") or {},
        "context": item.get("context") or {},
        "added": item.get("added") or "",
        "label": _label(item),
        "device": _device_index(item.get("device")),
    }


def list_items() -> dict:
    return {"items": [_public(item) for item in _read()]}


def _folder_of(values: dict, context: dict) -> str:
    return str(values.get("image_folder") or context.get("image_folder") or "").strip()


def add(family: str, values: dict, context: dict, device: int = 0) -> dict:
    from fizgig.families.registry import get as get_family

    if get_family(family) is None:
        raise JobError(404, {"detail": "unknown family"})
    values = dict(values or {})
    context = dict(context or {})
    folder = _folder_of(values, context)
    if not folder:
        raise JobError(422, {"problems": ["Pick a training image folder on the Start tab first."]})
    values["image_folder"] = folder
    context["image_folder"] = folder
    item = {
        "id": "q" + uuid.uuid4().hex[:10],
        "family": family,
        "values": values,
        "context": context,
        "added": _now(),
        "device": _device_index(device),
    }
    with _LOCK:
        items = _read()
        items.append(item)
        _write(items)
        _HOLD.clear()
    return _public(item)


def reorder(ids: list[str]) -> dict:
    with _LOCK:
        items = _read()
        by_id = {item["id"]: item for item in items}
        if sorted(ids) != sorted(by_id) or len(ids) != len(by_id):
            raise JobError(422, {"problems": ["the order must list every queued item once"]})
        _write([by_id[item_id] for item_id in ids])
        _HOLD.clear()
    return list_items()


def remove(item_id: str) -> dict:
    with _LOCK:
        items = _read()
        kept = [item for item in items if item.get("id") != item_id]
        if len(kept) == len(items):
            raise JobError(404, {"detail": "no such queue item"})
        _write(kept)
        _HOLD.clear()
    return list_items()


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no"}
    return bool(value)


def _samples_from(raw) -> dict:
    samples = {}
    if not isinstance(raw, dict):
        return samples
    for source, dest in _SAMPLES.items():
        if source not in raw:
            continue
        samples[dest] = _flag(raw[source]) if dest in _SAMPLE_BOOLS else raw[source]
    return samples


def from_desktop(item: dict) -> dict | None:
    """One desktop queue entry as a web item, or None when it cannot be launched."""
    if not isinstance(item, dict) or not isinstance(item.get("preset"), dict):
        return None
    if not isinstance(item.get("image_folder", ""), str):
        return None
    if not isinstance(item.get("architecture", ""), str):
        return None
    if not isinstance(item.get("samples", {}), dict):
        return None
    label = _ARCH_ALIASES.get(item.get("architecture") or "", item.get("architecture") or "")
    desc = by_gui_label(label)
    if desc is None:
        return None
    values = dict(item.get("preset") or {})
    options = item.get("model_options")
    if isinstance(options, dict):
        for key, value in options.items():
            if value:
                values[key] = value
    raw_samples = item.get("samples") if isinstance(item.get("samples"), dict) else {}
    for key in _VALUE_SAMPLES:
        if raw_samples.get(key) not in (None, ""):
            values[key] = raw_samples[key]
    folder = str(item.get("image_folder") or "").strip()
    if folder:
        values["image_folder"] = folder
    concepts = item.get("concept_folders") or []
    if not isinstance(concepts, list):
        concepts = []
    concepts = [str(entry).strip() for entry in concepts if str(entry).strip()]
    if concepts:
        values["MINIMAX_CONCEPT_DIRS"] = concepts
    context = {"image_folder": folder, "samples": _samples_from(raw_samples), "concept_folders": concepts}
    return {
        "id": "q" + uuid.uuid4().hex[:10],
        "family": desc.key,
        "values": values,
        "context": context,
        "added": _now(),
        "device": 0,
    }


def desktop_path() -> Path:
    override = os.environ.get("FIZGIG_WEB_DESKTOP_QUEUE", "").strip().strip('"')
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "presets" / "training_queue.json"


def import_desktop() -> dict:
    path = desktop_path()
    if not path.is_file():
        raise JobError(404, {"detail": "no desktop queue file"})
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobError(422, {"problems": [f"desktop queue could not be read: {exc}"]}) from exc
    if not isinstance(raw, list):
        raise JobError(422, {"problems": ["desktop queue is not a list"]})
    imported = []
    skipped = 0
    for entry in raw:
        mapped = from_desktop(entry)
        if mapped is None:
            skipped += 1
        else:
            imported.append(mapped)
    with _LOCK:
        items = _read()
        items.extend(imported)
        _write(items)
        _HOLD.clear()
    body = list_items()
    body["imported"] = len(imported)
    body["skipped"] = skipped
    return body


def arm(job_id: str) -> None:
    """Remember a training job this process started, so a later ``done`` can advance."""
    with _LOCK:
        _SEEN[job_id] = "queued"
        _ACTIVE_SEEN.add(job_id)


def _drop_ready(ids: list[str]) -> None:
    for job_id in ids:
        _READY.discard(job_id)


def observe(rows: list[dict]) -> None:
    """Start the next queued run when a training job in this call's rows finishes cleanly.

    The first time this process sees a job (no previous status) does not arm, so a
    run that is already done does not start the queue. A transition to failed does
    not arm. The ready mark is dropped once this call launches, finds nothing, or
    the device is held. It stays only when the launch was skipped because the
    device is busy. A job id that is not in ``rows`` cannot launch anything.
    """
    launches: list[tuple[dict, list[str]]] = []
    with _LOCK:
        busy: set[int] = set()
        failed: set[int] = set()
        present: set[str] = set()
        for job in rows:
            if (job.get("kind") or "train") != "train":
                continue
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            present.add(job_id)
            status = job.get("status") or ""
            device = _device_index(job.get("device"))
            prev = _SEEN.get(job_id)
            _SEEN[job_id] = status
            _DEVICE[job_id] = device
            if status in {"queued", "running"}:
                busy.add(device)
                _ACTIVE_SEEN.add(job_id)
            elif status == "done" and prev in {"queued", "running"}:
                _READY.add(job_id)
            elif status == "failed" and prev in {"queued", "running"}:
                failed.add(device)
        for job_id in list(_READY):
            if job_id not in present:
                _READY.discard(job_id)
        by_device: dict[int, list[str]] = {}
        for job_id in list(_READY):
            device = _DEVICE.get(job_id)
            if device is None:
                _READY.discard(job_id)
                continue
            by_device.setdefault(device, []).append(job_id)
        for device in failed:
            _drop_ready(by_device.pop(device, []))
        if not by_device:
            return
        picked: set[int] = set()
        for item in _read():
            device = _device_index(item.get("device"))
            if device not in by_device or device in picked or device in busy or device in _HOLD:
                continue
            picked.add(device)
            ids = list(by_device[device])
            _drop_ready(ids)
            launches.append((item, ids))
        for device, ids in by_device.items():
            if device in picked:
                continue
            if device in busy and device not in _HOLD:
                continue
            _drop_ready(ids)
    for head, ids in launches:
        try:
            outcome = _launch(head)
        except Exception:
            # An unexpected failure (a locked dataset.toml, a failed job.json write) keeps the mark, so the
            # next poll retries. The other devices in this batch still launch.
            outcome = None
        if outcome is None:
            with _LOCK:
                _READY.update(ids)


def advance(confirm: list[str] | None = None, device: int | None = None) -> dict:
    """Start one item now. ``device`` None is the head. A refusal leaves the item queued."""
    with _LOCK:
        items = _read()
        if device is None:
            head = items[0] if items else None
        else:
            want = _device_index(device)
            head = next((item for item in items if _device_index(item.get("device")) == want), None)
        if head is None:
            raise JobError(404, {"detail": "the queue is empty"})
        _HOLD.discard(_device_index(head.get("device")))
    return _launch(head, confirm or [], manual=True)


def _launch(head: dict, confirm: list[str] | None = None, manual: bool = False) -> dict:
    from fizgig.web import jobs

    device = _device_index(head.get("device"))
    try:
        created = jobs.start(
            head.get("family") or "",
            dict(head.get("values") or {}),
            dict(head.get("context") or {}),
            list(confirm or []),
            device=device,
        )
    except JobError as exc:
        detail = (exc.body or {}).get("detail")
        retry = exc.status == 409 and detail in {"a run is already active", "the GPU is in use"}
        if retry and not manual:
            return None
        if not retry:
            with _LOCK:
                _HOLD.add(device)
        if manual:
            raise
        return {}
    with _LOCK:
        items = [item for item in _read() if item.get("id") != head.get("id")]
        _write(items)
        _HOLD.discard(device)
    return created
