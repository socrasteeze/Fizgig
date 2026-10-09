"""Repair Studio on the engine host.

Mirrors the desktop tab: ``create_repair_studio_tab`` (family, DiT choice, primary
and donor, prompt, seed, resolution, reference, sliders), ``_schedule_preview``
(the page waits 400 ms, or 100 ms when forced), ``_repair_preview_worker``
(baseline then the repaired render), ``_repair_show_early``, ``_reset_repair_sliders``,
``_repair_preset_dir``, ``_save_repair_preset``, ``_load_repair_preset``,
``_repair_builtin_state``, ``_repair_category_for_block``, ``_save_repaired_lora_action``,
``_workbench_preview_model`` and ``_repair_engine_plan_family``.

``lora_trainer_gui.py`` is not imported. Presets are the desktop ``SliderState``
JSON: blocks, plus the family name. Prompt, seed and the reference stay on the session.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fizgig.web.fs import resolve_dir, resolve_file
from fizgig.web.jobs import JobError

_REPO = Path(__file__).resolve().parents[3]
_GROUPS: dict[str, list] = {}
_RESOLUTIONS = ("512", "768", "1024")
_GPU_BUSY = "A training or caption job is using the GPU. Wait for it to finish before loading an engine."


def _families():
    from fizgig.families.registry import FAMILIES
    return [desc for desc in FAMILIES.values() if desc.training_ready and "repair" in desc.workbench]


def _desc(family: str):
    from fizgig.families.registry import get as get_family
    desc = get_family(family)
    if desc is None:
        raise JobError(404, {"detail": "unknown family"})
    if not desc.training_ready or "repair" not in desc.workbench:
        raise JobError(422, {"problems": ["That family has no Repair Studio."]})
    return desc


def legacy_name(desc) -> str:
    """``LoRATrainerGUI._wb_legacy_name``: shares_prefs_with, else the key."""
    return desc.shares_prefs_with or desc.key


def preset_root() -> Path:
    override = os.environ.get("FIZGIG_WEB_PRESET_ROOT", "").strip()
    return Path(override) if override else _REPO / "presets" / "repair_studio"


def preset_dir(desc) -> Path:
    """``LoRATrainerGUI._repair_preset_dir``."""
    folder = preset_root() / legacy_name(desc)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def block_groups(desc) -> list[dict]:
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


def category_for_block(block_id: str) -> str:
    """``LoRATrainerGUI._repair_category_for_block``."""
    kind, _, idx_s = block_id.rpartition("_")
    if kind not in ("double", "single") or not idx_s.isdigit():
        return "identity"
    idx = int(idx_s)
    if kind == "double":
        return "style_composition"
    if idx == 0:
        return "style_composition"
    if idx == 1:
        return "style_ident_overlap"
    if 2 <= idx <= 11:
        return "identity"
    if 12 <= idx <= 16:
        return "ident_details_overlap"
    return "details"


def _block_ids(desc) -> list[str]:
    return [block["id"] for group in block_groups(desc) for block in group["blocks"]]


def default_blocks(desc) -> dict:
    return {bid: {"primary_enabled": True, "primary_strength": 1.0, "donor_enabled": True, "donor_strength": 1.0}
            for bid in _block_ids(desc)}


def _builtin_map(desc) -> dict:
    """``LoRATrainerGUI._repair_builtin_presets``."""
    if desc.category_masters:
        return {
            "✨Reset All": "reset",
            "✨Identity Only": "identity",
            "✨Style+Composition Only": "style",
            "✨Details Only": "details",
        }
    return {"✨Reset All": "reset", **{name: f"blocks:{name}" for name, _rows in desc.repair_presets}}


def builtin_blocks(desc, kind: str) -> dict:
    """``LoRATrainerGUI._repair_builtin_state``."""
    blocks = default_blocks(desc)
    if kind.startswith("blocks:"):
        want = dict(dict(desc.repair_presets).get(kind.split(":", 1)[1], ()))
        for bid, strength in want.items():
            if bid in blocks:
                blocks[bid]["primary_enabled"] = True
                blocks[bid]["primary_strength"] = float(strength)
        return blocks
    if kind == "reset" or not desc.category_masters:
        return blocks
    keep = {
        "identity": {"identity", "style_ident_overlap", "ident_details_overlap"},
        "style": {"style_composition", "style_ident_overlap"},
        "details": {"details", "ident_details_overlap"},
    }.get(kind, set())
    if not keep:
        return blocks
    for bid, row in blocks.items():
        row["primary_enabled"] = category_for_block(bid) in keep
    return blocks


def _lookup(prefs: dict):
    def get(key):
        return str(prefs.get(key) or "").strip()
    return get


def _sampling_dict(sampling) -> dict | None:
    if sampling is None:
        return None
    return {
        "name": sampling.name,
        "steps": sampling.steps,
        "cfg": sampling.cfg,
        "sigmas": None if sampling.sigmas is None else list(sampling.sigmas),
        "options": [list(pair) for pair in sampling.options],
    }


def preview_model(desc, lookup, fast: bool = True) -> tuple:
    """``LoRATrainerGUI._workbench_preview_model``. (dit path, speed LoRA path, sampling dict)."""
    def ready(path: str) -> str:
        return path if path and os.path.isfile(path) else ""

    dit = desc.model_path("dit", lookup)
    if fast:
        found = desc.preview_checkpoint()
        if found is not None and ready(lookup(found[0].pref_key)):
            return ready(lookup(found[0].pref_key)), "", _sampling_dict(found[1])
        speed = desc.preview_speed()
        if speed is not None and ready(lookup(speed.pref_key)):
            return dit, ready(lookup(speed.pref_key)), None
    return dit, "", None


def _prefs() -> dict:
    from fizgig.web.prefs import roots_from_prefs
    return roots_from_prefs()


def _require_file(path: str, label: str) -> str:
    if not path or not os.path.isfile(path):
        raise JobError(422, {"problems": [f"{label} path not set or not found. Set it in Preferences."]})
    return path


def load_plan(desc, dit_choice: str, prefs: dict | None = None) -> dict:
    """``LoRATrainerGUI._repair_engine_plan_family`` (and the video engine's extra paths)."""
    prefs = _prefs() if prefs is None else prefs
    lookup = _lookup(prefs)
    labels = {item.role: item.label for item in desc.model_files}
    fast = dit_choice != "base"
    dit, speed, sampling = preview_model(desc, lookup, fast=fast and not desc.video_workbench)
    if desc.video_workbench:
        dit = desc.model_path("dit", lookup)
        speed_obj = desc.preview_speed()
        speed = desc.model_path("speed_lora", lookup) or (lookup(speed_obj.pref_key) if speed_obj else "")
        sampling = None
    dit = _require_file(dit, labels.get("dit", "DiT"))
    vae = _require_file(desc.model_path("vae", lookup), labels.get("vae", "VAE"))
    text = _require_file(desc.model_path("text_encoder", lookup), labels.get("text_encoder", "text encoder"))
    raw_int8 = str(prefs.get("inference_int8") or "").strip()
    precision = "int8" if raw_int8 in {"1", "True", "true"} else "auto"
    cache = str(prefs.get("cache_dir") or "").strip()
    spec = getattr(desc, "clip_spec", None)
    return {
        "dit_path": dit,
        "vae_path": vae,
        "text_encoder_path": text,
        "speed_lora_path": speed if speed and os.path.isfile(speed) else "",
        "turbo_lora_path": speed if speed and os.path.isfile(speed) else "",
        "audio_vae_path": desc.model_path("audio_vae", lookup),
        "te_cache_dir": str(Path(cache) / "te_prompts") if cache else "",
        "precision": precision,
        "blocks_to_swap": str(prefs.get("inference_blocks_to_swap") or ""),
        "preview_sampling": sampling,
        "base_mode": "auto",
        "follows_samples": bool(desc.workbench_follows_samples),
        "video": bool(desc.video_workbench),
        "fps": int(spec.fps) if spec is not None else 24,
    }


def _fake() -> bool:
    return os.environ.get("FIZGIG_WEB_FAKE_ENGINE") == "1"


def gpu_free() -> None:
    from fizgig.gpu_lock import held
    from fizgig.web.engine_host import engine_device, engine_loaded
    from fizgig.web.jobs import _busy
    if engine_loaded():
        return
    device = engine_device()
    if _busy(device) or held(device):
        raise JobError(409, {"detail": _GPU_BUSY})


_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)


def _reserved_leaf(name: str) -> bool:
    leaf = str(name or "").strip().replace("\\", "/").split("/")[-1]
    stem = leaf.split(".", 1)[0].rstrip(" ")
    return bool(stem and _RESERVED.match(stem))


def _sanitize(name: str) -> str:
    if _reserved_leaf(name):
        raise JobError(422, {"problems": ["Invalid preset name."]})
    name = "".join(char for char in name if char.isalnum() or char in (" ", "_", "-")).strip()
    if not name or name.startswith("✨") or _reserved_leaf(name):
        raise JobError(422, {"problems": ["Invalid preset name."]})
    return name


def form(family: str = "") -> dict:
    rows = _families()
    if not rows:
        raise JobError(404, {"detail": "no repair family"})
    chosen = family if any(desc.key == family for desc in rows) else rows[0].key
    desc = _desc(chosen)
    groups = block_groups(desc)
    builtins = list(_builtin_map(desc))
    saved = []
    try:
        saved = [path.stem for path in sorted(preset_dir(desc).glob("*.json"))]
    except OSError:
        saved = []
    return {
        "family": desc.key,
        "display_name": desc.display_name,
        "families": [{"key": item.key, "name": item.display_name, "video": bool(item.video_workbench)} for item in rows],
        "groups": groups,
        "resolutions": list(_RESOLUTIONS),
        "video": bool(desc.video_workbench),
        "follows_samples": bool(desc.workbench_follows_samples),
        "dit_choices": [] if desc.video_workbench else [
            {"id": "fast", "label": "Preview"},
            {"id": "base", "label": "Base model"},
        ],
        "presets": builtins + [name for name in saved if name not in builtins],
        "builtins": builtins,
        "defaults": {
            "seed": 42,
            "resolution": "768" if desc.video_workbench or desc.key != "klein" else "512",
            "primary_scale": 1.0,
            "donor_scale": 1.0,
            "ref_megapixels": 1.0,
            "ref_strength": 1.0,
            "dit": "fast",
            "blocks": default_blocks(desc),
        },
        "debounce_ms": 400,
        "debounce_force_ms": 100,
    }


def _primary(body: dict) -> Path:
    return resolve_file(str(body.get("primary") or body.get("lora") or ""), ".safetensors")


def _donor(body: dict) -> str:
    text = str(body.get("donor") or "").strip()
    if not text:
        return ""
    return str(resolve_file(text, ".safetensors"))


def _args(desc, body: dict) -> dict:
    primary = str(_primary(body))
    donor = _donor(body)
    if _fake():
        return {"primary": primary, "donor": donor, "crash": bool(body.get("crash"))}
    plan = load_plan(desc, str(body.get("dit") or "fast"))
    plan["primary"] = primary
    plan["donor"] = donor
    settings = body.get("preview_settings")
    if desc.workbench_follows_samples and isinstance(settings, dict):
        plan["preview_settings"] = {
            "steps": settings.get("steps") or "",
            "cfg": settings.get("cfg") or "",
            "negative": str(settings.get("negative") or ""),
            "turbo": settings.get("turbo") or "0",
        }
    return plan


def load(body: dict) -> dict:
    from fizgig.web.engine_host import EngineError, get_host
    desc = _desc(str(body.get("family") or ""))
    gpu_free()
    try:
        args = _args(desc, body)
    except JobError:
        raise
    host = get_host()
    try:
        host.load("repair", desc.key, args)
    except EngineError as exc:
        text = exc.message
        if "GPU is in use" in text:
            raise JobError(409, {"detail": _GPU_BUSY}) from exc
        raise JobError(422, {"problems": [text]}) from exc
    return host.status()


def _checked_state(raw) -> dict:
    """``ref_image_path`` must sit inside the same roots Explorer opens, or be empty."""
    state = dict(raw) if isinstance(raw, dict) else {}
    if "ref_image_path" not in state:
        return state
    text = str(state.get("ref_image_path") or "").strip()
    if not text:
        state["ref_image_path"] = ""
        return state
    from fizgig.web.explorer import _client_image
    state["ref_image_path"] = _client_image(text)
    return state


def render(body: dict) -> dict:
    """Accept a render. The host assigns the gen; a client counter is not authoritative."""
    from fizgig.web.engine_host import EngineError, get_host
    desc = _desc(str(body.get("family") or ""))
    host = get_host()
    if not host.loaded or host.engine_name not in {"repair", "profiler"}:
        raise JobError(422, {"problems": ["Load a LoRA before rendering."]})
    state = _checked_state(body.get("state") if isinstance(body.get("state"), dict) else {})
    params = {
        "state": state,
        "steps": int(body.get("steps") or 3),
        "video": bool(body.get("video") if "video" in body else desc.video_workbench),
        "early_step": int(body.get("early_step") or 0),
        "frames": body.get("frames") or None,
        "fps": int(body.get("fps") or 24),
        "preview_settings": body.get("preview_settings") if isinstance(body.get("preview_settings"), dict) else None,
    }
    try:
        gen = host.render(params)
    except EngineError as exc:
        raise JobError(422, {"problems": [exc.message]}) from exc
    return {"gen": gen, "status": "running"}


def unload() -> dict:
    from fizgig.web.engine_host import get_host
    get_host().unload()
    return {"loaded": False}


def status() -> dict:
    from fizgig.web.engine_host import get_host
    host = get_host()
    if host.proc is None and not host.restarted:
        return {"loaded": False, "engine": "", "family": "", "busy": False, "gen": 0, "restarted": False}
    return host.status()


def presets(family: str) -> dict:
    desc = _desc(family)
    names = []
    folder = preset_dir(desc)
    try:
        names = [path.stem for path in sorted(folder.glob("*.json"), key=lambda item: item.name.lower())]
    except OSError:
        names = []
    return {"family": desc.key, "dir": str(folder), "builtins": list(_builtin_map(desc)), "presets": names}


def save_preset(body: dict) -> dict:
    """``LoRATrainerGUI._save_repair_preset``: blocks only, plus the family name."""
    desc = _desc(str(body.get("family") or ""))
    name = _sanitize(str(body.get("name") or ""))
    raw = body.get("state") if isinstance(body.get("state"), dict) else {}
    from fizgig.repair_studio.state import SliderState
    state = SliderState.from_json(raw)
    payload = {"blocks": state.to_json()["blocks"], "family": legacy_name(desc)}
    path = preset_dir(desc) / f"{name}.json"
    if path.exists() and not body.get("overwrite"):
        raise JobError(409, {"detail": f"Preset '{name}' already exists."})
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"name": name, "path": str(path), "family": legacy_name(desc)}


def read_preset(family: str, name: str) -> dict:
    """``LoRATrainerGUI._load_repair_preset``: blocks only. A prompt in an old file is ignored."""
    desc = _desc(family)
    builtins = _builtin_map(desc)
    if name in builtins:
        return {"name": name, "builtin": True, "blocks": builtin_blocks(desc, builtins[name])}
    name = _sanitize(name)
    folder = preset_dir(desc).resolve()
    path = (folder / f"{name}.json").resolve()
    try:
        path.relative_to(folder)
    except ValueError:
        raise JobError(422, {"problems": ["Invalid preset name."]}) from None
    if path.parent != folder:
        raise JobError(422, {"problems": ["Invalid preset name."]})
    if not path.is_file():
        raise JobError(404, {"detail": "no such preset"})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobError(422, {"problems": ["Load failed."]}) from exc
    from fizgig.repair_studio.state import SliderState
    state = SliderState.from_json(data if isinstance(data, dict) else {})
    blocks = {}
    known = set(_block_ids(desc))
    for bid, row in state.to_json()["blocks"].items():
        if bid in known:
            blocks[bid] = row
    return {"name": name, "builtin": False, "blocks": blocks}


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


_BAKER_BLOCK = re.compile(r"(?:lora_unet_)?(double_blocks|single_blocks)_(\d+)_")
_BAKER_TXT = re.compile(r"txtfusion_(layerwise|refiner)_blocks_(\d+)_")
_BAKER_REFINER = re.compile(r"token_refiner_blocks_(\d+)_")
_BAKER_MAIN = re.compile(r"lora_unet_blocks_(\d+)_")


def _baker_maps_key(key: str) -> bool:
    return bool(
        _BAKER_BLOCK.search(key) or _BAKER_TXT.search(key)
        or _BAKER_REFINER.search(key) or _BAKER_MAIN.search(key)
    )


def _refuse_unmapped(family: str) -> None:
    """The file baker only understands double/single, txtfusion, token_refiner, and lora_unet_blocks_N."""
    from fizgig.families.registry import get as get_family
    desc = get_family(family) if family else None
    lora = getattr(desc, "lora", None) if desc is not None else None
    sample = ""
    if lora is not None:
        module = lora.block_modules[0] if lora.block_modules else "block"
        try:
            sample = lora.key_template.format(block=0, module=module, ab=lora.down)
        except Exception:
            sample = ""
    if sample and _baker_maps_key(sample):
        return
    raise JobError(422, {"problems": [
        "This family's LoRA keys cannot be baked from the file. Load the engine and save from there.",
    ]})


def _inside_dir(dest: Path, folder: Path) -> None:
    try:
        dest.resolve().relative_to(folder.resolve())
    except (OSError, ValueError):
        raise JobError(422, {"problems": ["Enter an output name."]}) from None


def engine_bake(engine_name: str, state, dest: str, include_donor: bool):
    """``save_repaired`` on the loaded engine. None means the file baker should run."""
    from fizgig.web.engine_host import EngineError, get_host
    host = get_host()
    if host.proc is None or not host.loaded or host.engine_name != engine_name:
        return None
    payload = state.to_json() if hasattr(state, "to_json") else state
    try:
        reply = host.request({
            "op": "bake",
            "state": payload,
            "dest": str(dest),
            "include_donor": bool(include_donor),
        }, timeout=3600)
    except EngineError as exc:
        raise JobError(422, {"problems": [exc.message]}) from exc
    if reply.get("ok"):
        return reply.get("summary") or {}
    if reply.get("fallback"):
        return None
    raise JobError(422, {"problems": [str(reply.get("error") or "bake failed")]})


def bake(body: dict) -> dict:
    """``LoRATrainerGUI._save_repaired_lora_action``.

    A loaded engine with ``save_repaired`` bakes through that method. The file
    baker runs only when the loaded engine has no such method. Families whose
    keys it cannot map are refused instead of written through unchanged.
    """
    from fizgig.repair_studio.state import SliderState
    from fizgig.web.extract import _leaf as _output_leaf
    primary = _primary(body)
    raw = _checked_state(body.get("state") if isinstance(body.get("state"), dict) else {})
    state = SliderState.from_json(raw)
    donor_on = [bid for bid, row in state.blocks.items() if row.donor_enabled]
    donor_path = _donor(body) if donor_on else ""
    stem = primary.stem
    if donor_on and donor_path:
        default = f"{stem}_with_{Path(donor_path).stem}.safetensors"
    else:
        default = f"{stem}_repaired.safetensors"
    leaf = _output_leaf(str(body.get("output_name") or default))
    folder = _output_dir()
    dest = _free(folder / leaf)
    _inside_dir(dest, folder)
    from fizgig.web.engine_host import get_host
    host = get_host()
    baked_by = host.engine_name if host.loaded and host.engine_name in {"repair", "profiler"} else ""
    summary = engine_bake(baked_by, state, str(dest), bool(donor_on)) if baked_by else None
    if summary is None:
        _refuse_unmapped(str(body.get("family") or ""))
        from fizgig.repair_studio.bake import save_repaired_lora
        summary = save_repaired_lora(str(primary), state, str(dest), donor_path=donor_path or None)
    return {"path": str(dest), "summary": summary}


def metrics(body: dict) -> dict:
    """``repair_studio.metrics.compare`` on the two preview images."""
    import numpy as np
    from PIL import Image
    from fizgig.repair_studio.metrics import PATCH_PITCH, compare
    family = str(body.get("family") or "")
    baseline = resolve_file(str(body.get("baseline") or ""), ".png")
    tweaked = resolve_file(str(body.get("tweaked") or ""), ".png")
    pitch = int(PATCH_PITCH.get(family, 16))
    with Image.open(baseline) as left, Image.open(tweaked) as right:
        base = np.asarray(left.convert("RGB"))
        tweak = np.asarray(right.convert("RGB"))
    return compare(base, tweak, pitch)
