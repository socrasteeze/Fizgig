"""VRAM and RAM the way the desktop status bar reads them.

Mirrors ``LoRATrainerGUI._read_vram`` and the ``psutil`` read in
``_status_reader_loop``. This does not import torch and does not create a CUDA context.
"""
from __future__ import annotations

import subprocess

from fizgig.gpu_lock import device_index

_nvml_ready = False
_nvml_failed = False


def read_vram():
    """``(used_bytes, total_bytes)`` for the training GPU, or None."""
    global _nvml_ready, _nvml_failed
    index = device_index()
    if not _nvml_failed:
        try:
            import pynvml
            if not _nvml_ready:
                pynvml.nvmlInit()
                _nvml_ready = True
            info = pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(index))
            return int(info.used), int(info.total)
        except Exception:
            _nvml_failed = True
    try:
        out = subprocess.run(
            ["nvidia-smi", "-i", str(index),
             "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        used, total = out.stdout.strip().splitlines()[0].split(",")
        return int(used) * 1024 * 1024, int(total) * 1024 * 1024
    except Exception:
        pass
    try:
        from fizgig.utils.vram_monitor import read_amd_gpu_vram
        return read_amd_gpu_vram()
    except Exception:
        return None


def read_ram():
    """``(used_bytes, total_bytes)`` or None. Used is total minus available."""
    try:
        import psutil
        memory = psutil.virtual_memory()
        return memory.total - memory.available, memory.total
    except Exception:
        return None


def _pair(value):
    if not value:
        return None
    return {"used": int(value[0]), "total": int(value[1])}


def stats() -> dict:
    return {"vram": _pair(read_vram()), "ram": _pair(read_ram())}
