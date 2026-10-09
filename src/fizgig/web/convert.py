"""Checkpoint to LoRA as a job.

``_start`` checks the two checkpoints, the ranks, and the name. ``_work``
passes that base, tuned file, output directory, ranks, and name through.
``diff_to_lora_gui.py`` is not imported.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fizgig.web.fs import resolve_dir, resolve_file
from fizgig.web.jobs import JobError

# diff_to_lora_gui.RANKS and sorted(DEFAULT_ON).
RANKS = [8, 16, 32, 64, 128, 256]
DEFAULT_RANKS = [32, 64]
_RANK_PROBLEM = "Rank must be 8, 16, 32, 64, 128 or 256."


def _configured_output() -> str:
    from fizgig.web.prefs import roots_from_prefs

    return str(roots_from_prefs().get("lora_output_dir") or "").strip()


def _output_dir() -> Path:
    """The LoRA output directory ``_start`` writes into."""
    from fizgig.web.fs import output_roots

    raw = _configured_output()
    if not raw:
        raise JobError(422, {"problems": ["Set the LoRA output folder in Preferences."]})
    return resolve_dir(raw, output_roots())


def form() -> dict:
    output_dir = ""
    if _configured_output():
        output_dir = str(_output_dir())
    return {
        "ranks": list(RANKS),
        "default_ranks": list(DEFAULT_RANKS),
        "name": "extracted",
        "output_dir": output_dir,
    }


def _name(raw) -> str:
    text = "" if raw is None else str(raw).strip()
    if not text:
        return "extracted"
    if "/" in text or "\\" in text or ".." in text:
        raise JobError(422, {"problems": ["Enter a name without a path."]})
    return text


def _rank_value(item) -> int:
    if isinstance(item, bool):
        raise JobError(422, {"problems": [_RANK_PROBLEM]})
    if isinstance(item, int):
        return item
    text = str(item).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    raise JobError(422, {"problems": [_RANK_PROBLEM]})


def _ranks(raw) -> list[int]:
    """Ranks ``_start`` collects, kept in ``RANKS`` order."""
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [item for item in raw if not (isinstance(item, str) and not str(item).strip())]
    else:
        items = []
    if not items:
        raise JobError(422, {"problems": ["Tick at least one rank."]})
    chosen: list[int] = []
    for item in items:
        rank = _rank_value(item)
        if rank not in RANKS:
            raise JobError(422, {"problems": [_RANK_PROBLEM]})
        if rank not in chosen:
            chosen.append(rank)
    return [rank for rank in RANKS if rank in chosen]


def _settings(body: dict) -> dict:
    """``_start``: both checkpoints exist, they differ, and a rank is ticked."""
    base = resolve_file(str(body.get("base") or ""), ".safetensors")
    tuned = resolve_file(str(body.get("tuned") or ""), ".safetensors")
    if base == tuned:
        raise JobError(422, {"problems": ["Base and trained checkpoint are the same file."]})
    ranks = _ranks(body.get("ranks"))
    name = _name(body.get("name"))
    folder = _output_dir()
    return {
        "base": str(base),
        "tuned": str(tuned),
        "output": str(folder),
        "output_dir": str(folder),
        "name": name,
        "ranks": ranks,
    }


def flags(settings: dict) -> list[str]:
    """Arguments ``_work`` passes to ``extract_diff_loras``."""
    ranks = settings["ranks"]
    if not isinstance(ranks, str):
        ranks = ",".join(str(rank) for rank in ranks)
    return [
        "--base", str(settings["base"]),
        "--tuned", str(settings["tuned"]),
        "--output", str(settings["output"]),
        "--name", str(settings["name"]),
        "--ranks", ranks,
    ]


def cli(settings: dict) -> list[str]:
    return [sys.executable, "-m", "fizgig.web.convert_run", *flags(settings)]


def command(source: dict) -> list[str]:
    """The argv the runner executes. A job dict or the settings dict both work."""
    settings = source["values"] if isinstance(source.get("values"), dict) else source
    fake = os.environ.get("FIZGIG_WEB_FAKE_CONVERT", "").strip()
    if fake:
        return [sys.executable, fake, *flags(settings)]
    return cli(settings)


def launch(body: dict) -> dict:
    from fizgig.web import jobs

    settings = _settings(body)
    output_dir = settings["output_dir"]

    def stamp(folder, job):
        job["command"] = command(settings)
        job["stage"] = "Convert"
        jobs.save(folder, job)

    return jobs.start_task("convert", "convert", settings, output_dir, stamp)
