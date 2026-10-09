"""LoRA extraction as a job.

The command is the CLI ``extract_lora.py`` builds for the same choices
``_run_extract`` makes: family, source, output in the LoRA output folder,
rank, and either a preset or the Custom block ids. ``lora_trainer_gui.py``
is not imported.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fizgig.web.fs import resolve_dir, resolve_file
from fizgig.web.jobs import JobError

_RANKS = ("1", "2", "4", "8", "16")
_GROUPS: dict[str, list] = {}


def _families():
    from fizgig.families.registry import FAMILIES

    return [desc for desc in FAMILIES.values() if desc.training_ready and "extract" in desc.workbench]


def _desc(family: str):
    from fizgig.families.registry import get as get_family

    desc = get_family(family)
    if desc is None:
        raise JobError(404, {"detail": "unknown family"})
    if not desc.training_ready or "extract" not in desc.workbench:
        raise JobError(422, {"problems": ["That family has no Extract tool."]})
    return desc


def block_groups(desc) -> list[dict]:
    """The driver's block map, cached. The first call imports that driver."""
    cached = _GROUPS.get(desc.key)
    if cached is not None:
        return cached
    groups = []
    for group in desc.load_driver().block_map():
        groups.append({
            "label": group.label,
            "blocks": [{"id": block.id, "label": block.label} for block in group.blocks],
        })
    _GROUPS[desc.key] = groups
    return groups


def _time_note(desc) -> str:
    if desc.video_workbench:
        return (f"{desc.display_name} is a big model - weight SVD runs over every trained module "
                "(hundreds of wide Linears). Expect several minutes on a free GPU.")
    return (f"{desc.display_name}: exact low-rank SVD of every kept module, straight from the file (no model "
            "loaded) — a few seconds. The result keeps the family's own key format.")


def suggested_name(source: str, preset: str, rank: str) -> str:
    """``_update_extract_output_name``: source stem, preset slug, rank."""
    base = os.path.splitext(os.path.basename(source))[0]
    slug = str(preset or "").lower().replace("+", "_").replace(" ", "_")
    return f"{base}_{slug}_r{rank}.safetensors"


def form(family: str = "") -> dict:
    rows = _families()
    if not rows:
        raise JobError(404, {"detail": "no extract family"})
    chosen = family if any(desc.key == family for desc in rows) else rows[0].key
    desc = _desc(chosen)
    names = [name for name, _blocks in desc.extract_presets]
    groups = block_groups(desc) if names else []
    if names:
        names = [*names, "Custom"]
    return {
        "family": desc.key,
        "display_name": desc.display_name,
        "families": [{"key": item.key, "name": item.display_name} for item in rows],
        "presets": names,
        "groups": groups,
        "ranks": list(_RANKS),
        "rank": "4",
        "time_note": _time_note(desc),
        "gaps": [],
    }


def _output_dir() -> Path:
    from fizgig.web.fs import output_roots
    from fizgig.web.prefs import roots_from_prefs

    raw = str(roots_from_prefs().get("lora_output_dir") or "").strip()
    if not raw:
        raise JobError(422, {"problems": ["Set the LoRA output folder in Preferences."]})
    return resolve_dir(raw, output_roots())


def _free(path: Path) -> Path:
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    number = 2
    while True:
        candidate = path.with_name(f"{stem}_{number}{ext}")
        if not candidate.exists():
            return candidate
        number += 1


def _leaf(name: str) -> str:
    text = (name or "").strip().replace("\\", "/")
    leaf = text.split("/")[-1]
    if text != leaf or leaf in {"", ".", ".."} or leaf.startswith("."):
        raise JobError(422, {"problems": ["Enter an output name."]})
    if any(ord(char) < 32 or char in '<>:"|?*' for char in leaf):
        raise JobError(422, {"problems": ["Enter an output name."]})
    if not leaf.lower().endswith(".safetensors"):
        leaf += ".safetensors"
    return leaf


def _blocks(desc, preset: str, raw) -> list[str] | None:
    names = [name for name, _blocks in desc.extract_presets]
    if not names:
        return None
    if preset == "Custom":
        if not isinstance(raw, list):
            raw = []
        allowed = {block["id"] for group in block_groups(desc) for block in group["blocks"]}
        chosen = []
        for item in raw:
            block_id = str(item).strip()
            if not block_id:
                continue
            if block_id not in allowed:
                raise JobError(422, {"problems": [f"unknown block: {block_id}"]})
            if block_id not in chosen:
                chosen.append(block_id)
        if not chosen:
            raise JobError(422, {"problems": ["Custom is selected but no blocks are ticked."]})
        return chosen
    if preset not in names:
        raise JobError(422, {"problems": [f"unknown extract preset: {preset or 'none'}"]})
    return None


def _settings(body: dict) -> dict:
    desc = _desc(str(body.get("family") or ""))
    source = resolve_file(str(body.get("source") or ""), ".safetensors")
    rank = str(body.get("rank") if body.get("rank") is not None else "4")
    if rank not in _RANKS:
        raise JobError(422, {"problems": ["Target rank must be 1, 2, 4, 8 or 16."]})
    preset = str(body.get("preset") or "")
    names = [name for name, _blocks in desc.extract_presets]
    if names and not preset:
        preset = names[0]
    blocks = _blocks(desc, preset, body.get("blocks"))
    name = str(body.get("output_name") or "").strip()
    leaf = _leaf(name) if name else suggested_name(str(source), preset, rank)
    folder = _output_dir()
    output = _free(folder / leaf)
    return {
        "family": desc.key,
        "source": str(source),
        "output_name": output.name,
        "output": str(output),
        "output_dir": str(folder),
        "preset": "" if blocks else preset,
        "blocks": blocks or [],
        "rank": rank,
    }


def flags(settings: dict) -> list[str]:
    args = ["--family", settings["family"], "--source", settings["source"],
            "--output", settings["output"], "--rank", str(settings["rank"])]
    blocks = settings.get("blocks") or []
    if blocks:
        args += ["--blocks", ",".join(blocks)]
    elif settings.get("preset"):
        args += ["--preset", settings["preset"]]
    return args


def cli(settings: dict) -> list[str]:
    return [sys.executable, "-m", "fizgig.scripts.extract_lora", *flags(settings)]


def command(job: dict) -> list[str]:
    settings = job.get("values") or {}
    fake = os.environ.get("FIZGIG_WEB_FAKE_EXTRACT", "").strip()
    if fake:
        return [sys.executable, fake, *flags(settings)]
    return cli(settings)


def launch(body: dict) -> dict:
    from fizgig.web import jobs

    settings = _settings(body)

    def stamp(folder, job):
        job["command"] = cli(settings)
        job["stage"] = "Extract"
        jobs.save(folder, job)

    return jobs.start_task("extract", settings["family"], settings, settings["output_dir"], stamp)
