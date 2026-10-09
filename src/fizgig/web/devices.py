"""CUDA device indices the page can offer.

Torch is not imported. ``pynvml`` wins, then ``nvidia-smi``, then ``[0]``.
``CUDA_VISIBLE_DEVICES`` filters a successful probe. ``nvmlShutdown`` is not
called; the status reader uses ``pynvml`` too.
"""
from __future__ import annotations

import os
import subprocess

from fizgig.web.procs import creationflags


def _pynvml_indices() -> list[int] | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        count = int(pynvml.nvmlDeviceGetCount())
    except Exception:
        return None
    if count < 0:
        return None
    return list(range(count))


def _smi_indices() -> list[int] | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=creationflags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = []
    for line in (out.stdout or "").splitlines():
        text = line.strip()
        if text.isdigit():
            found.append(int(text))
    if not found:
        return None
    return found


def _env_indices() -> list[int] | None:
    """Integers in ``CUDA_VISIBLE_DEVICES``, or None when the variable is unset."""
    if "CUDA_VISIBLE_DEVICES" not in os.environ:
        return None
    found = []
    for part in (os.environ.get("CUDA_VISIBLE_DEVICES") or "").split(","):
        text = part.strip()
        if text.isdigit():
            found.append(int(text))
    return found


def visible_devices() -> list[int]:
    detected = _pynvml_indices()
    if detected is None:
        detected = _smi_indices()
    failed = detected is None
    if not detected:
        detected = []
    chosen = _env_indices()
    if chosen is None:
        return detected or [0]
    if not chosen:
        return [0]
    if failed:
        return chosen
    have = set(detected)
    kept = [index for index in chosen if index in have]
    return kept or [0]
