"""Weights profile as a job.

The desktop Profiler renders Quick and Thorough on the workbench engine. This
phase runs the weights CLI (``profile_lora.py``), which is the weights path of
``_run_profiler_family``: the same report name under ``profiles_dir``.
``lora_trainer_gui.py`` is not imported.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote

from fizgig.web.fs import _linked, resolve_dir, resolve_file
from fizgig.web.jobs import JobError

_MODES = ("weights", "quick", "thorough")
_SIZES = ("512", "768", "1024")


def _families():
    from fizgig.families.registry import FAMILIES

    return [desc for desc in FAMILIES.values() if desc.training_ready and "profiler" in desc.workbench]


def _desc(family: str):
    from fizgig.families.registry import get as get_family

    desc = get_family(family)
    if desc is None:
        raise JobError(404, {"detail": "unknown family"})
    if not desc.training_ready or "profiler" not in desc.workbench:
        raise JobError(422, {"problems": ["That family has no Profiler."]})
    return desc


def _profiles_dir() -> Path:
    from fizgig.web.prefs import roots_from_prefs

    raw = str(roots_from_prefs().get("profiles_dir") or "").strip()
    if not raw:
        raise JobError(422, {"problems": ["Set the profiles folder in Preferences."]})
    Path(raw).mkdir(parents=True, exist_ok=True)
    return resolve_dir(raw)


def form(family: str = "") -> dict:
    rows = _families()
    if not rows:
        raise JobError(404, {"detail": "no profiler family"})
    chosen = family if any(desc.key == family for desc in rows) else rows[0].key
    desc = _desc(chosen)
    return {
        "family": desc.key,
        "display_name": desc.display_name,
        "families": [{"key": item.key, "name": item.display_name} for item in rows],
        "modes": [
            {"id": "weights", "label": "Weights only (instant)"},
            {"id": "quick", "label": "Quick (1 seed)"},
            {"id": "thorough", "label": "Thorough (2 seeds, steadier)"},
        ],
        "sizes": list(_SIZES),
        "defaults": {"mode": "weights", "size": "768"},
        "gaps": ["Quick and Thorough renders", "Open in Repair Studio"],
    }


def _settings(body: dict) -> dict:
    desc = _desc(str(body.get("family") or ""))
    mode = str(body.get("mode") or "weights")
    if mode not in _MODES:
        raise JobError(422, {"problems": ["unknown profiler mode"]})
    if mode != "weights":
        raise JobError(422, {"problems": [
            "Quick and Thorough profiling needs the engine host. This phase runs Weights only.",
        ]})
    lora = resolve_file(str(body.get("lora") or ""), ".safetensors")
    folder = _profiles_dir()
    output = folder / f"{lora.stem}_{desc.lora_name_suffix}_profile.html"
    size = str(body.get("size") or "768")
    if size not in _SIZES:
        size = "768"
    return {
        "family": desc.key,
        "lora": str(lora),
        "mode": mode,
        "prompt": str(body.get("prompt") or "").strip(),
        "class_prompt": str(body.get("class_prompt") or "").strip(),
        "baselines": body.get("baselines") if isinstance(body.get("baselines"), list) else [],
        "size": size,
        "output": str(output),
        "output_dir": str(folder),
    }


def flags(settings: dict) -> list[str]:
    return ["--lora", settings["lora"], "--family", settings["family"], "--output", settings["output"]]


def cli(settings: dict) -> list[str]:
    return [sys.executable, "-m", "fizgig.scripts.profile_lora", *flags(settings)]


def command(job: dict) -> list[str]:
    settings = job.get("values") or {}
    fake = os.environ.get("FIZGIG_WEB_FAKE_PROFILE", "").strip()
    if fake:
        return [sys.executable, fake, *flags(settings)]
    return cli(settings)


def launch(body: dict) -> dict:
    from fizgig.web import jobs

    settings = _settings(body)

    def stamp(folder, job):
        job["command"] = cli(settings)
        job["stage"] = "Profile"
        jobs.save(folder, job)

    return jobs.start_task("profile", settings["family"], settings, settings["output_dir"], stamp)


def reports() -> dict:
    try:
        folder = _profiles_dir()
    except JobError:
        return {"dir": "", "reports": []}
    found = []
    try:
        names = sorted(folder.glob("*.html"), key=lambda item: item.name.lower())
    except OSError:
        names = []
    for path in names:
        if _linked(path) or not path.is_file():
            continue
        found.append({
            "name": path.name,
            "path": str(path),
            "url": "/api/profiles/file?path=" + quote(str(path.resolve())),
        })
    return {"dir": str(folder), "reports": found}


def report_file(text: str) -> Path:
    folder = _profiles_dir()
    return resolve_file(text, ".html", [folder])
