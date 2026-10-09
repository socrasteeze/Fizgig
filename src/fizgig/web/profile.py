"""Profiler.

Weights runs ``profile_lora.py``, the weights path of ``_run_profiler_family``,
and writes the same report name under ``profiles_dir``. Quick and Thorough
render on the engine host (one seed, or two). ``lora_trainer_gui.py`` is not
imported.
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
        "defaults": {"mode": "quick", "size": "768", "prompt": "", "class_prompt": ""},
        "gaps": ["Likeness and bleed from subject photos"],
    }


def _settings(body: dict) -> dict:
    desc = _desc(str(body.get("family") or ""))
    mode = str(body.get("mode") or "weights")
    if mode not in _MODES:
        raise JobError(422, {"problems": ["unknown profiler mode"]})
    if mode != "weights":
        raise JobError(422, {"problems": ["Weights runs as a job. Quick and Thorough use the engine."]})
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


_ENGINE: dict = {}


def _engine_settings(body: dict) -> dict:
    """Quick and Thorough, the render half of ``_run_profiler_family``."""
    desc = _desc(str(body.get("family") or ""))
    mode = str(body.get("mode") or "quick")
    if mode not in ("quick", "thorough"):
        raise JobError(422, {"problems": ["Quick and Thorough run on the engine. Weights runs as a job."]})
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise JobError(422, {"problems": ["Enter a prompt (with the LoRA's trigger word, if it has one)."]})
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
        "prompt": prompt,
        "class_prompt": str(body.get("class_prompt") or "").strip(),
        "size": int(size),
        "output": str(output),
        "output_dir": str(folder),
    }


def _handoff_message(notes: list, class_prompt: str) -> str:
    """The status line ``LoRATrainerGUI._profiler_open_in_repair`` sets."""
    if notes:
        message = "From the profile: " + "; ".join(notes) + "."
    else:
        message = ("The profile found no group to turn down or switch off: the likeness and any bleed sit in the "
                   "same blocks, so sliders stay as trained.")
    if class_prompt:
        message += f' To see the bleed, set the prompt to "{class_prompt}".'
    return message


def _capture(host) -> dict | None:
    profile = host.profile if isinstance(host.profile, dict) else None
    if not profile:
        return None
    settings = _ENGINE.get("settings") or {}
    report = str(profile.get("report") or settings.get("output") or "")
    if report and not Path(report).is_file():
        notes = profile.get("notes") or []
        text = "<p>" + _handoff_message(list(notes), str(profile.get("class_prompt") or "")) + "</p>\n"
        Path(report).write_text(text, encoding="utf-8")
        profile = dict(profile)
        profile["report"] = report
    stored = {
        "status": "done",
        "gen": _ENGINE.get("gen"),
        "family": settings.get("family") or host.family,
        "lora": settings.get("lora") or (host.args or {}).get("primary") or "",
        "mode": profile.get("mode"),
        "seeds": profile.get("seeds") or [],
        "per_block": bool(profile.get("per_block")),
        "prompt": profile.get("prompt") or "",
        "class_prompt": profile.get("class_prompt") or "",
        "seed": profile.get("seed"),
        "size": profile.get("size"),
        "blocks": profile.get("blocks") or {},
        "notes": profile.get("notes") or [],
        "report": report,
        "message": _handoff_message(list(profile.get("notes") or []), str(profile.get("class_prompt") or "")),
    }
    _ENGINE["result"] = stored
    return stored


def start_engine(body: dict) -> dict:
    """Quick or Thorough on the engine host. Seeds match ``_run_profiler_family``: 1234, and 5678 when thorough."""
    from fizgig.web.engine_host import EngineError, get_host
    from fizgig.web.repair import _args, block_groups, gpu_free

    settings = _engine_settings(body)
    gpu_free()
    desc = _desc(settings["family"])
    groups = block_groups(desc)
    host = get_host()
    try:
        args = _args(desc, {"primary": settings["lora"], "dit": "fast"})
        host.load("profiler", desc.key, args)
        host.profile = None
        host.result = None
        gen = host.render({
            "profile": True,
            "mode": settings["mode"],
            "prompt": settings["prompt"],
            "class_prompt": settings["class_prompt"],
            "size": settings["size"],
            "output": settings["output"],
            "groups": groups,
            "steps": 1,
        })
    except EngineError as exc:
        text = exc.message
        if "GPU is in use" in text:
            from fizgig.web.repair import _GPU_BUSY
            raise JobError(409, {"detail": _GPU_BUSY}) from exc
        raise JobError(422, {"problems": [text]}) from exc
    _ENGINE["settings"] = settings
    _ENGINE["gen"] = gen
    _ENGINE["result"] = None
    return {"gen": gen, "status": "running", "mode": settings["mode"], "family": settings["family"]}


def engine_view() -> dict:
    from fizgig.web.engine_host import get_host
    host = get_host()
    gen = _ENGINE.get("gen")
    result = host.result or {}
    if gen and result.get("gen") == gen and host.profile:
        captured = _capture(host)
        if captured:
            return captured
    stored = _ENGINE.get("result")
    if stored and stored.get("gen") == gen:
        return stored
    if host.restarted:
        return {
            "status": "failed",
            "gen": gen,
            "message": "The engine worker stopped. It will start again on the next request.",
        }
    if host.busy:
        return {"status": "running", "gen": gen}
    if gen:
        return {"status": "failed", "gen": gen, "message": "The profile did not finish."}
    return {"status": "idle"}


def open_repair() -> dict:
    """``LoRATrainerGUI._profiler_open_in_repair``: the LoRA, prompt, seed, size and suggested sliders."""
    view = engine_view()
    if view.get("status") != "done":
        raise JobError(422, {"problems": ["Run Quick or Thorough before opening Repair Studio."]})
    return {
        "family": view.get("family") or "",
        "lora": view.get("lora") or "",
        "prompt": view.get("prompt") or "",
        "class_prompt": view.get("class_prompt") or "",
        "seed": view.get("seed"),
        "size": view.get("size"),
        "blocks": view.get("blocks") or {},
        "notes": view.get("notes") or [],
        "message": view.get("message") or "",
    }


def report_file(text: str) -> Path:
    folder = _profiles_dir()
    return resolve_file(text, ".html", [folder])
