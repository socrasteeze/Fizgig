"""One video or audio file for the page player.

``FileResponse`` answers HTTP Range. This returns the path and does not read the file.
"""
from __future__ import annotations

from pathlib import Path

from fizgig.web.fs import resolve_file
from fizgig.web.jobs import JobError

_SUFFIXES = {
    ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi",
    ".wav", ".mp3", ".flac", ".m4a", ".ogg",
}


def resolve_media(text: str) -> Path:
    """An existing media file inside the configured roots.

    Same refusal order as ``engine_file``: ``..`` is 403, any other suffix is
    404, then ``resolve_file`` (empty suffix, so the suffix check stays here)
    refuses links and paths outside the roots.
    """
    raw = (text or "").strip()
    if not raw or any(part == ".." for part in raw.replace("\\", "/").split("/")):
        raise JobError(403, {"detail": "path is outside the configured roots"})
    if Path(raw).suffix.lower() not in _SUFFIXES:
        raise JobError(404, {"detail": "no such file"})
    return resolve_file(raw, "")
