"""Windows launch flags for web children.

A process with no console gives each of its children a new, visible console.
Short tools pass ``CREATE_NO_WINDOW`` via :func:`creationflags`. A long-lived
child instead gets its own hidden console via :func:`hidden_console`. Processes
it starts inherit that console and stay hidden. A detached launch also starts a
new process group, so a server restart or Ctrl+C does not kill the run.
Other platforms get the kwargs those launches already used.
"""
from __future__ import annotations

import os
import subprocess


def creationflags() -> int:
    """Flags for a short-lived tool that must not open a console."""
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW


def hidden_console(detached: bool = False) -> dict:
    """Kwargs for a long-lived child whose console is hidden.

    ``detached`` adds ``CREATE_NEW_PROCESS_GROUP`` on Windows and
    ``start_new_session`` elsewhere. Spread the dict into ``Popen``.
    """
    if os.name != "nt":
        kwargs = {"creationflags": 0}
        if detached:
            kwargs["start_new_session"] = True
        return kwargs
    flags = subprocess.CREATE_NEW_CONSOLE
    if detached:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": flags, "startupinfo": info}
