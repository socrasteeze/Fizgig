"""Turn a submitted training form into the dict ``launch.plan`` expects.

Mirrors ``LoRATrainerGUI._family_launch_inputs``. Number fields are coerced the way
``_start_training_launch`` copies widgets into ``self.settings`` before that call:
learning rate and network alpha become floats, rank, epochs and seed become ints.
Switches are real booleans. Samples, model paths and the captioner are not Training-tab
fields; the caller passes them in ``context``.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from fizgig.web.form_spec import KIND_CHOICES

_REPO = Path(__file__).resolve().parents[3]
_KIND_BY_LABEL = {label: key for key, label in KIND_CHOICES}
_SLIDER_SOURCE = {"Photo pairs": "pairs", "Prompts": "prompts", "pairs": "pairs", "prompts": "prompts"}


def _python():
    candidate = _REPO / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(candidate if candidate.is_file() else Path(sys.executable))


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _text(value):
    return "" if value is None else str(value).strip()


def _float(value, default):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return float(default)


def _int(value, default):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return int(default)


def _kind(desc, values):
    raw = values.get("kind", "standard")
    kind = _KIND_BY_LABEL.get(raw, raw)
    if kind not in {"standard", "edit", "slider", "finetune"}:
        if _bool(values.get("FAMILY_FT")):
            kind = "finetune"
        elif _bool(values.get("FAMILY_SLIDER")):
            kind = "slider"
        elif _bool(values.get("FAMILY_EDIT")):
            kind = "edit"
        else:
            kind = "standard"
    return (
        kind == "edit" and bool(desc.edit_training),
        kind == "slider" and bool(desc.slider_training),
        kind == "finetune" and bool(desc.finetune),
    )


def _models(desc, available):
    """The pref keys ``_family_launch_inputs`` puts in ``models``."""
    keys = {item.pref_key for item in desc.model_files}
    speed = desc.preview_speed()
    if speed and speed.pref_key:
        keys.add(speed.pref_key)
    if desc.training_adapter:
        keys.add(desc.training_adapter)
    for opt in desc.options:
        blobs = [tok for _label, text in opt.choices for tok in text.split()] + opt.tokens.split()
        for blob in blobs:
            keys.update(re.findall(r"pref:([A-Za-z0-9_]+)", blob))
            keys.update(re.findall(r"->([A-Za-z0-9_]+)", blob))
    return {key: _text(available.get(key, "")) for key in keys}


def _check(opt, raw):
    if opt.kind == "check":
        return "1" if _bool(raw) or str(raw) in {"1", "True", "true"} else ""
    if opt.kind == "choice":
        return opt.pick(raw)
    return _text(raw)


def _family_options(desc, values, overrides):
    """``{key: value}`` of the family's options, fixed options excluded, as the launch reads them."""
    out = {}
    overrides = overrides or {}
    for opt in desc.options:
        if opt.kind == "fixed":
            continue
        if opt.key in overrides:
            raw = overrides[opt.key]
        elif opt.key in values:
            raw = values[opt.key]
        elif opt.setting and opt.setting in values:
            raw = values[opt.setting]
        else:
            raw = opt.default
        out[opt.key] = _check(opt, raw)
    return out


def _extra_folders(desc, values):
    if not (desc.multi_concept and _bool(values.get("FAMILY_MULTICONCEPT"))):
        return []
    raw = values.get("MINIMAX_CONCEPT_DIRS", values.get("extra_folders", ""))
    if isinstance(raw, (list, tuple)):
        return [_text(item) for item in raw if _text(item)]
    text = _text(raw)
    return [text] if text else []


def _samples(context):
    samples = dict(context.get("samples") or {})
    samples.setdefault("enabled", True)
    prompts = samples.get("prompts")
    if isinstance(prompts, str):
        samples["prompts"] = prompts.splitlines()
    elif prompts is None:
        samples["prompts"] = ["A high quality photo"]
    return samples


def build(desc, values, context=None):
    """The inputs dict for ``launch.plan(desc, inputs)``."""
    context = context or {}
    values = dict(values)
    edit, slider, finetune = _kind(desc, values)
    samples = _samples(context)
    if desc.train_preview_checkpoint and samples.get("checkpoint") and "int8" not in samples:
        from fizgig.web.prefs import roots_from_prefs

        raw = roots_from_prefs().get("inference_int8")
        samples["int8"] = str(raw or "").strip() in {"1", "True", "true"}
    source = _SLIDER_SOURCE.get(_text(values.get("FAMILY_SLIDER_SOURCE", "pairs")), "pairs")
    compile_blocks = _text(values.get("COMPILE_BLOCKS", "Auto")) or "Auto"
    if compile_blocks.lower() in {"auto", "on", "off"}:
        compile_blocks = compile_blocks.capitalize()
    areas = bool(desc.train_areas)
    blocks = values.get("FAMILY_TRAIN_BLOCKS") or values.get("TRAINING_BLOCKS") or []
    if isinstance(blocks, str):
        blocks = [part.strip() for part in blocks.split(",") if part.strip()]
    output_dir = _text(values.get("LORA_OUTPUT_DIR", context.get("LORA_OUTPUT_DIR", "")))
    samples_dir = _text(context.get("samples_dir")) or (os.path.join(output_dir, "sample") if output_dir else "")
    inputs = {
        "python": _python(),
        "repo_dir": str(_REPO),
        "models": _models(desc, context.get("models") or {}),
        "image_folder": _text(values.get("image_folder", context.get("image_folder", ""))),
        "caption_ext": _text(values.get("caption_ext", ".txt")) or ".txt",
        "batch_size": values.get("batch_size", "1"),
        "megapixels": values.get("megapixels", "0.25"),
        "enable_bucket": _bool(values.get("enable_bucket", True)),
        "no_upscale": _bool(values.get("no_upscale", True)),
        "cache_root": _text(context.get("cache_root", "")),
        "blocks_swap": _text(values.get("blocks_swap", "Auto (detect from GPU)")),
        "enable_cache": _bool(values.get("enable_cache", True)),
        "resuming": bool(_text(values.get("RESUME_TRAINING")) or context.get("ft_resume")),
        "loss_watch": {
            "detect": _bool(values.get("KREA2_LOSS_WATCH")),
            "per_image_lr": _bool(values.get("KREA2_PER_IMAGE_LR")),
            "warmup": _bool(values.get("KREA2_WARMUP_LOOK")),
            "recaption": _bool(values.get("KREA2_AUTO_RECAPTION")),
        },
        "captioner": _text(context.get("captioner", "")),
        "caption_trigger": _text(context.get("caption_trigger", "")),
        "caption_overrides": context.get("caption_overrides") or {},
        "samples": samples,
        "samples_dir": samples_dir,
        "edit_caption": _text(values.get("FAMILY_EDIT_CAPTION", "")),
        "FAMILY_OPTIONS": _family_options(desc, values, context.get("option_values")),
        "clip_megapixels": _float(values.get("clip_megapixels", 0.25), 0.25),
        "extra_folders": _extra_folders(desc, values),
        "DATASET_CONFIG": _text(context.get("DATASET_CONFIG", values.get("DATASET_CONFIG", ""))),
        "LORA_OUTPUT_DIR": output_dir,
        "LORA_NAME": _text(values.get("LORA_NAME", "")),
        "LEARNING_RATE": _float(values.get("LEARNING_RATE", 4e-4), 4e-4),
        "LORA_LR_RATIO": _int(values.get("LORA_LR_RATIO", 1), 1),
        "NETWORK_DIM": _int(values.get("NETWORK_DIM", 4), 4),
        "NETWORK_ALPHA": _float(values.get("NETWORK_ALPHA", 4), 4),
        "NETWORK_TYPE": _text(values.get("NETWORK_TYPE", "LoRA (standard)")),
        "LOKR_FACTOR": _int(values.get("LOKR_FACTOR", 8), 8),
        "MAX_TRAIN_EPOCHS": _int(values.get("MAX_TRAIN_EPOCHS", 12), 12),
        "SAVE_EVERY_N_EPOCHS": _int(values.get("SAVE_EVERY_N_EPOCHS", 1), 1),
        "SEED": _int(values.get("SEED", 42), 42),
        "OPTIMIZER_TYPE": _text(values.get("OPTIMIZER_TYPE", "")),
        "OPTIMIZER_ARGS": _text(values.get("OPTIMIZER_ARGS", "")),
        "GRADIENT_ACCUMULATION": values.get("GRADIENT_ACCUMULATION", 1),
        "MAX_GRAD_NORM": values.get("MAX_GRAD_NORM", 1.0),
        "LR_SCHEDULER": _text(values.get("LR_SCHEDULER", "constant")) or "constant",
        "LR_WARMUP_STEPS": _text(values.get("LR_WARMUP_STEPS", "")),
        "ADAPTIVE_LR": bool(desc.adaptive_lr and _bool(values.get("ADAPTIVE_LR"))),
        "ADAPTIVE_LR_MIN": _text(values.get("ADAPTIVE_LR_MIN", "1e-5")),
        "ADAPTIVE_LR_MAX": _text(values.get("ADAPTIVE_LR_MAX", "4e-4")),
        "CONTEXT_LORA_PATH": _text(values.get("CONTEXT_LORA_PATH", "")),
        "CONTEXT_LORA_STRENGTH": _text(values.get("CONTEXT_LORA_STRENGTH", "1.0")) or "1.0",
        "MIN_TIMESTEP": _text(values.get("MIN_TIMESTEP", "")),
        "MAX_TIMESTEP": _text(values.get("MAX_TIMESTEP", "")),
        "COMPILE_BLOCKS": compile_blocks,
        "SAVE_STATE": _bool(values.get("SAVE_STATE", True)),
        "SAVE_STATE_ON_TRAIN_END": _bool(values.get("SAVE_STATE_ON_TRAIN_END", True)),
        "KEEP_LAST_N_STATES": values.get("KEEP_LAST_N_STATES", 2),
        "RESUME_TRAINING": _text(values.get("RESUME_TRAINING", "")),
        "FAMILY_EDIT": edit,
        "FAMILY_SLIDER": slider,
        "FAMILY_FT": finetune,
        "FAMILY_FT_FUSED": _bool(values.get("FAMILY_FT_FUSED", True)),
        "FAMILY_SLIDER_ULTRA": _bool(values.get("FAMILY_SLIDER_ULTRA")),
        "FAMILY_FAST_ID": _bool(values.get("FAMILY_FAST_ID")),
        "FAMILY_SLIDER_SOURCE": source,
        "FAMILY_EDIT_DIR": _text(values.get("FAMILY_EDIT_DIR", "")),
        "FAMILY_EDIT_REF": _text(values.get("FAMILY_EDIT_REF", "")),
        "FAMILY_SLIDER_DIR": _text(values.get("FAMILY_SLIDER_DIR", "")),
        "FAMILY_SLIDER_CAPTION": _text(values.get("FAMILY_SLIDER_CAPTION", "")),
        "FAMILY_SLIDER_BASE": _text(values.get("FAMILY_SLIDER_BASE", "")),
        "FAMILY_SLIDER_POS": _text(values.get("FAMILY_SLIDER_POS", "")),
        "FAMILY_SLIDER_NEG": _text(values.get("FAMILY_SLIDER_NEG", "")),
        "FAMILY_SLIDER_GUIDANCE": _text(values.get("FAMILY_SLIDER_GUIDANCE", "")),
        "FAMILY_FT_ROTATIONS": _text(values.get("FAMILY_FT_ROTATIONS", "10")) or "10",
        "FAMILY_FT_SAVE_EVERY": _text(values.get("FAMILY_FT_SAVE_EVERY", "1")) or "1",
        "FAMILY_FT_ROTATE_EVERY": _text(values.get("FAMILY_FT_ROTATE_EVERY", "1")) or "1",
        "FAMILY_FT_REG_DIR": _text(values.get("FAMILY_FT_REG_DIR", "")),
        "FAMILY_FT_REG_MULT": _text(values.get("FAMILY_FT_REG_MULT", "0.2")) or "0.2",
        "FAMILY_FT_MAX_PARTS": _text(values.get("FAMILY_FT_MAX_PARTS", "")),
        "FAMILY_TRAINING_ADAPTER": _bool(values.get("FAMILY_TRAINING_ADAPTER", True)),
        "FAMILY_EMA": _text(values.get("FAMILY_EMA", "")),
        "FAMILY_PRECISION": _text(values.get("FAMILY_PRECISION", "")),
        "FAMILY_TURBO_STRENGTH": _text(context.get("FAMILY_TURBO_STRENGTH", values.get("FAMILY_TURBO_STRENGTH", ""))),
    }
    if areas:
        inputs["FAMILY_TRAIN_AREA"] = _text(values.get("FAMILY_TRAIN_AREA", ""))
        inputs["FAMILY_TRAIN_BLOCKS"] = list(blocks)
    if desc.samples_turbo_pace:
        inputs["FAMILY_TURBO_STEPS"] = _text(context.get("FAMILY_TURBO_STEPS", ""))
        inputs["FAMILY_TURBO_PACE"] = _text(context.get("FAMILY_TURBO_PACE", ""))
    for key in ("METADATA_TITLE", "METADATA_AUTHOR", "METADATA_DESCRIPTION", "METADATA_LICENSE",
                "METADATA_TAGS", "METADATA_TRIGGER_PHRASE", "METADATA_THUMBNAIL"):
        inputs[key] = _text(values.get(key, ""))
    return inputs
