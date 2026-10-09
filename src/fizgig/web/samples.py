"""Samples-tab form for one described family.

Defaults and wording follow ``update_samples_ui_for_architecture``,
``_generic_samples_ui``, and ``_apply_samples_minimax``. The resolutions are
the desktop ``SAMPLE_RESOLUTIONS`` list, read from source. ``lora_trainer_gui.py``
is not imported. Hashes live in ``mirrors.py``.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

_GUI = Path(__file__).resolve().parents[3] / "lora_trainer_gui.py"
_RESOLUTIONS: tuple | None = None

# The desktop's Klein wording, then a described family's own samples_text on top.
_KLEIN = {
    "banner": "Preview prompts rendered periodically during training (Distilled 4-step). "
              "Samples land in <output_dir>/sample/ and the Gallery button below opens the viewer.",
    "advanced": "Architecture-specific knobs. Distilled models disable Negative Prompt; "
                "non-distilled models disable CFG Scale.",
    "flow": "Base samples only — Distilled uses its own schedule",
    "neg": "Base samples only — Distilled ignores it",
    "cfg": "Base samples only — Distilled uses no CFG",
}
_PROMPT = "A high quality photo"
_NEGATIVE = ("blurry, low detail, noisy, washed out, oversaturated, distorted anatomy, extra limbs, "
             "duplicate objects, text, watermark, logo, frame, cropped subject, flat lighting, muddy colors")


def resolutions() -> list[str]:
    """The Samples tab's width and height list."""
    global _RESOLUTIONS
    if _RESOLUTIONS is None:
        tree = ast.parse(_GUI.read_text(encoding="utf-8"))
        found = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SAMPLE_RESOLUTIONS":
                    found = ast.literal_eval(node.value)
        if not isinstance(found, list):
            raise RuntimeError("SAMPLE_RESOLUTIONS is missing")
        _RESOLUTIONS = tuple(str(item) for item in found)
    return list(_RESOLUTIONS)


def _speed_file(desc) -> str:
    speed = desc.preview_speed()
    if speed is None or not speed.pref_key or desc.samples_turbo_pace:
        return ""
    from fizgig.web.prefs import roots_from_prefs

    path = str(roots_from_prefs().get(speed.pref_key) or "").strip()
    return path if path and os.path.isfile(path) else ""


def wording(desc) -> dict:
    """The Samples tab's banner and notes for this family."""
    if desc.train_preview_checkpoint:
        text = dict(_KLEIN)
    else:
        text = dict(
            _KLEIN,
            banner=(f"Preview prompts rendered periodically during training, on the {desc.display_name} "
                    f"model being trained. Samples land in <output_dir>/sample/ and the Gallery button "
                    f"below opens the viewer."),
            advanced=f"{desc.display_name}'s sampling settings: the negative prompt and CFG Scale.",
        )
    text.update(dict(desc.samples_text))
    cfg_free = bool(desc.samples_cfg_free)
    if not cfg_free and not desc.train_preview_checkpoint and not ({k for k, _ in desc.samples_text} - {"sampler"}):
        text["flow"] = f"Not used for {desc.display_name} previews"
        text["neg"] = "Used when CFG Scale is above 1"
        text["cfg"] = desc.preview_cfg_note or "1 = no CFG. Above 1 the negative prompt applies."
    text["steps"] = _steps_note(desc, bool(_speed_file(desc)), text)
    text.setdefault("sampler", dict(desc.samples_text).get("sampler", ""))
    return text


def _steps_note(desc, speed_on: bool, text: dict) -> str:
    speed = desc.preview_speed()
    defaults = desc.preview_speed_defaults() or (None, None)
    speed_steps, speed_strength = defaults
    if desc.train_preview_checkpoint:
        note = "Base samples only — Distilled is locked at 4 steps"
    elif speed_on and speed is not None:
        if not speed_strength:
            note = (f"{desc.display_name}: {speed_steps} steps on the plain model by default. For fast previews set "
                    f"Turbo strength to {speed.strength:g} and steps to {speed.settings.steps} (the {speed.name}, set in "
                    f"Preferences)")
        else:
            note = (f"{desc.display_name}: the {speed.name} (set in Preferences), default {speed_steps} steps at strength "
                    f"{speed_strength:g}. At {speed.settings.steps} steps it uses its own schedule, otherwise the model's "
                    f"standard one")
    else:
        note = f"{desc.display_name}: {desc.preview_steps} steps at CFG {desc.preview_cfg:g}"
        if speed is not None and speed_steps is not None:
            note += f" - set the {speed.name} in Preferences for {speed_steps}-step previews"
    sampler = dict(desc.samples_text).get("sampler")
    if sampler and not desc.train_preview_checkpoint:
        note = f"{note} · {sampler}"
    if desc.samples_cfg_free and text.get("steps"):
        return text["steps"]
    return note


def _steps_default(desc, speed_on: bool):
    entry = desc.architecture_entry()
    steps = entry["sample_steps_default"]
    defaults = desc.preview_speed_defaults()
    if desc.samples_turbo_pace:
        if defaults and str(steps) == str(defaults[0]):
            return desc.preview_steps
        return steps
    if speed_on and defaults:
        return defaults[0]
    return steps


def _choice(value, choices: list[str]) -> list[str]:
    text = str(value)
    if text in choices:
        return list(choices)
    return [text, *choices]


def _field(key, label, kind, default, help="", choices=None, disabled=False, disabled_when=""):
    row = {"key": key, "label": label, "kind": kind, "default": default, "help": help}
    if choices:
        row["choices"] = list(choices)
    if disabled:
        row["disabled"] = True
    if disabled_when:
        row["disabled_when"] = disabled_when
    return row


def form(desc) -> dict:
    """The Samples form for ``desc``."""
    entry = desc.architecture_entry()
    sizes = resolutions()
    notes = wording(desc)
    speed_on = bool(_speed_file(desc))
    negative = entry["sample_negative_default"]
    fields = [
        _field("enabled", "Enable Sample Generation", "bool", True, help=""),
        _field("prompts", "Prompt", "lines", _PROMPT,
               help="Each line is a separate prompt."),
        _field("width", "Width", "choice", str(entry["sample_width_default"]),
               choices=_choice(entry["sample_width_default"], sizes)),
        _field("height", "Height", "choice", str(entry["sample_height_default"]),
               choices=_choice(entry["sample_height_default"], sizes)),
        _field("steps", "Steps", "int", _steps_default(desc, speed_on), help=notes["steps"],
               disabled_when="checkpoint" if desc.train_preview_checkpoint else ""),
        _field("seed", "Seed", "int", 1234, help="0 = random"),
        _field("every", "Every N Epochs", "int", 1,
               help="How often previews render. 0 disables that cadence."),
        _field("at_first", "Sample at Start", "bool", True),
        _field("cfg", "CFG Scale", "float", entry["sample_cfg_default"], help=notes["cfg"],
               disabled=bool(entry["sample_cfg_fixed"])),
        _field("negative", "Negative Prompt", "text", negative if negative is not None else _NEGATIVE,
               help=notes["neg"], disabled=bool(entry["sample_is_distilled"])),
    ]
    if desc.train_preview_checkpoint:
        fields.append(_field("checkpoint", "Use Distilled model for samples (4-step, matches ComfyUI)",
                             "bool", True))
        fields.append(_field("checkpoint_cache", "Cache sample model in RAM", "choice", "auto",
                             choices=["auto", "on", "off"]))
    defaults = desc.preview_speed_defaults()
    if desc.samples_turbo_pace:
        fields.append(_field("FAMILY_TURBO_STEPS", "Turbo steps", "int", 6,
                             help="Previews only. 6 steps at 75% is the tested recommendation."))
        fields.append(_field("FAMILY_TURBO_PACE", "Turbo strength %", "int", 75, help=""))
    elif speed_on and defaults is not None:
        fields.append(_field("FAMILY_TURBO_STRENGTH", "Turbo strength", "float", f"{defaults[1]:g}",
                             help="How strongly the turbo LoRA loads for previews."))
    return {
        "family": desc.key,
        "display_name": desc.display_name,
        "resolutions": sizes,
        "wording": notes,
        "fields": fields,
        "gaps": [
            "Every N steps",
            "Reference image",
            "Flow shift",
            "Sample length",
        ],
    }


def pack(values: dict) -> dict:
    """Form values as the ``context`` fragment ``launch.plan`` reads."""
    values = values or {}
    prompts = values.get("prompts", _PROMPT)
    if isinstance(prompts, str):
        lines = prompts.splitlines()
    else:
        lines = ["" if item is None else str(item) for item in prompts]
    samples = {
        "enabled": bool(values.get("enabled", True)),
        "prompts": lines,
        "every": str(values.get("every", "1")).strip(),
        "width": str(values.get("width", "")).strip(),
        "height": str(values.get("height", "")).strip(),
        "steps": str(values.get("steps", "")).strip(),
        "cfg": str(values.get("cfg", "")).strip(),
        "negative": str(values.get("negative", "")).strip(),
        "seed": str(values.get("seed", "")).strip(),
        "at_first": bool(values.get("at_first", True)),
    }
    if "checkpoint" in values:
        samples["checkpoint"] = bool(values["checkpoint"])
        cache = str(values.get("checkpoint_cache") or "auto")
        samples["checkpoint_cache"] = cache if cache in {"auto", "on", "off"} else "auto"
    context = {"samples": samples}
    for key in ("FAMILY_TURBO_STRENGTH", "FAMILY_TURBO_STEPS", "FAMILY_TURBO_PACE"):
        if key in values and str(values[key]).strip():
            context[key] = str(values[key]).strip()
    return context
