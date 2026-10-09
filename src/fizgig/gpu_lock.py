"""One OS file lock per CUDA device, shared by the desktop app and the web runner.

The lock file is ``cache/gpu/<index>.lock``. The holder keeps that file open.
When the holder exits, the operating system drops the lock, so a crash releases it.
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DIR = _REPO / "cache" / "gpu"


def device_index() -> int:
    """The card a run uses.

    The first ``CUDA_VISIBLE_DEVICES`` entry when it is a number, otherwise 0.
    Callers that already know the card pass that index to ``held`` and ``GpuLock``.
    The desktop resolves a UUID through its own GPU list and passes the index.
    """
    raw = (os.environ.get("CUDA_VISIBLE_DEVICES") or "").split(",")[0].strip()
    return int(raw) if raw.isdigit() else 0


def lock_path(index: int | None = None) -> Path:
    if index is None:
        index = device_index()
    return _DIR / f"{int(index)}.lock"


def _open(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() < 1:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    return handle


def _try_lock(handle) -> bool:
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def held(index: int | None = None) -> bool:
    """True when another process holds this card's lock.

    ``LoRATrainerGUI.start_training`` calls this and refuses the run when it is true.
    """
    handle = _open(lock_path(index))
    try:
        if _try_lock(handle):
            _unlock(handle)
            return False
        return True
    finally:
        handle.close()


class GpuLock:
    """A lock this process holds until ``release`` or until the process exits."""

    def __init__(self, index: int | None = None):
        self.path = lock_path(index)
        self._handle = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        handle = _open(self.path)
        if not _try_lock(handle):
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        _unlock(handle)
        handle.close()
