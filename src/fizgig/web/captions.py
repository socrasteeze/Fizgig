"""Caption jobs and the caption editor.

The job speaks the ``batch_caption.py --serve`` protocol (READY, RUN, PROGRESS, OK,
FAIL, STOPPED, DONE, QUIT). Settings follow the Captions tab. Static captions follow
``generate_captions``. Translation and Whisper are not here.
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

from fizgig.web.fs import IMAGE_EXTENSIONS, resolve_dir
from fizgig.web.jobs import JobError
from fizgig.web.start import require_folder

_FLORENCE = (
    "MiaoshouAI/Florence-2-base-PromptGen",
    "microsoft/Florence-2-base",
    "microsoft/Florence-2-large",
)
_REVISIONS = {
    "MiaoshouAI/Florence-2-base-PromptGen": "da7ac9f3deac56a928e2fd4d94d8bb985d231299",
    "microsoft/Florence-2-base": "5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac",
    "microsoft/Florence-2-large": "21a599d414c4d928c9032694c424fb94458e3594",
}
_CODE_REVISIONS = {
    "MiaoshouAI/Florence-2-base-PromptGen": "f6c1a25888ffc1d945ee8a1a77ac833c7303d46e",
}
_TASKS = ("<CAPTION>", "<DETAILED_CAPTION>", "<MORE_DETAILED_CAPTION>")
_QWEN = "Qwen3-VL 4B (Krea 2 text encoder)"
_VIDEO = {".mp4"}


def _qwen_path() -> str:
    """The Krea 2 text-encoder file when it is set and on disk, else ``""``."""
    from fizgig.web.prefs import roots_from_prefs

    path = str(roots_from_prefs().get("krea2_text_encoder") or "").strip()
    if path and os.path.isfile(path):
        return path
    return ""


def _eval_strings(node, names: dict) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _eval_strings(node.left, names) + _eval_strings(node.right, names)
    raise ValueError("not a string expression")


_BUILTIN_INSTRUCTION: str | None = None


def _builtin_training_instruction() -> str:
    """The desktop training-caption instruction. ``embedder`` imports torch, so parse it."""
    global _BUILTIN_INSTRUCTION
    if _BUILTIN_INSTRUCTION is not None:
        return _BUILTIN_INSTRUCTION
    path = Path(__file__).resolve().parents[1] / "krea2" / "embedder.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    wanted = {"SUBJECT_RULE", "NO_PREAMBLE_RULE", "CAPTION_INSTRUCTION"}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted:
            names[target.id] = _eval_strings(node.value, names)
    _BUILTIN_INSTRUCTION = names["CAPTION_INSTRUCTION"]
    return _BUILTIN_INSTRUCTION


def _default_instruction() -> str:
    from fizgig.web.prefs import roots_from_prefs

    raw = roots_from_prefs().get("caption_qwen_instructions")
    if isinstance(raw, dict):
        saved = str(raw.get("training") or "").strip()
        if saved:
            return saved
    return _builtin_training_instruction()


def _default_model() -> str:
    return _QWEN if _qwen_path() else _FLORENCE[0]


def form() -> dict:
    choices = list(_FLORENCE)
    if _qwen_path():
        choices.append(_QWEN)
    return {
        "fields": [
            {"key": "trigger", "label": "Trigger Word", "kind": "text", "default": "",
             "help": "Prepended to every caption."},
            {"key": "model", "label": "Model", "kind": "choice", "default": _default_model(),
             "choices": choices, "help": "Florence downloads itself. Qwen uses the Krea 2 text encoder."},
            {"key": "task", "label": "Task", "kind": "choice", "default": "<DETAILED_CAPTION>",
             "choices": list(_TASKS), "help": "Florence task. Qwen uses the instruction instead."},
            {"key": "max_tokens", "label": "Max Tokens", "kind": "int", "default": 120, "help": ""},
            {"key": "overwrite", "label": "Overwrite existing caption files", "kind": "bool",
             "default": False, "help": "Off keeps an image that already has a .txt."},
            {"key": "instruction", "label": "Instruction", "kind": "text",
             "default": _default_instruction(),
             "help": "Sent to Qwen. Florence ignores it."},
            {"key": "include_video", "label": "Include video clips", "kind": "bool",
             "default": False, "help": "Caption .mp4 files as well as stills."},
        ],
        "gaps": ["Bilingual translation", "Whisper"],
    }


def _images(folder: str, include_video: bool) -> list[str]:
    allowed = set(IMAGE_EXTENSIONS)
    if include_video:
        allowed |= _VIDEO
    found = []
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if os.path.isfile(full) and os.path.splitext(name)[1].lower() in allowed:
            found.append(full)
    return found


def _settings(body: dict, folder: str) -> dict:
    model = str(body.get("model") or _default_model())
    if model not in _FLORENCE and model != _QWEN:
        raise JobError(422, {"problems": ["unknown caption model"]})
    task = str(body.get("task") or "<DETAILED_CAPTION>")
    if task not in _TASKS:
        raise JobError(422, {"problems": ["unknown caption task"]})
    try:
        tokens = int(body.get("max_tokens") if body.get("max_tokens") not in (None, "") else 120)
    except (TypeError, ValueError):
        tokens = 120
    return {
        "folder": folder,
        "trigger": str(body.get("trigger") or "").strip(),
        "model": model,
        "task": task,
        "max_tokens": max(1, tokens),
        "overwrite": bool(body.get("overwrite")),
        "instruction": str(body.get("instruction") or "").strip() or _default_instruction(),
        "include_video": bool(body.get("include_video")),
    }


def write_files(folder: Path, settings: dict) -> None:
    """Worker config and the RUN job, next to the Fizgig job record."""
    qwen = settings["model"] == _QWEN
    config = {
        "backend": "qwen" if qwen else "florence",
        "include_video": bool(settings.get("include_video")),
    }
    if qwen:
        encoder = _qwen_path()
        if not encoder or not os.path.isfile(encoder):
            raise JobError(422, {"problems": ["Qwen3-VL text encoder path is not set or not found"]})
        config["text_encoder"] = encoder
        instruction = settings.get("instruction") or ""
        if not instruction:
            raise JobError(422, {"problems": ["the instruction can't be empty"]})
        (folder / "instruction.txt").write_text(instruction, encoding="utf-8")
    else:
        config["florence_model"] = settings["model"]
        revision = _REVISIONS.get(settings["model"])
        code = _CODE_REVISIONS.get(settings["model"])
        if revision:
            config["florence_revision"] = revision
        if code:
            config["florence_code_revision"] = code
    images = _images(settings["folder"], bool(settings.get("include_video")))
    if not settings.get("overwrite"):
        images = [path for path in images if not os.path.isfile(os.path.splitext(path)[0] + ".txt")]
    if not images:
        raise JobError(422, {"problems": ["no images to caption"]})
    (folder / "images.txt").write_text("".join(path + "\n" for path in images), encoding="utf-8")
    job = {
        "list_file": str(folder / "images.txt"),
        "max_new_tokens": int(settings["max_tokens"]),
        "trigger": settings.get("trigger") or "",
        "stop_file": str(folder / "caption_stop"),
    }
    if qwen:
        job["instruction_file"] = str(folder / "instruction.txt")
    else:
        job["florence_task"] = settings["task"]
    (folder / "caption_job.json").write_text(json.dumps(job), encoding="utf-8")
    (folder / "worker_config.json").write_text(json.dumps(config), encoding="utf-8")


def command(folder: Path) -> list[str]:
    config = str(folder / "worker_config.json")
    fake = os.environ.get("FIZGIG_WEB_FAKE_CAPTION", "").strip()
    if fake:
        return [sys.executable, fake, "--serve", "--config", config]
    return [sys.executable, "-m", "fizgig.scripts.batch_caption", "--serve", "--config", config]


def launch(body: dict) -> dict:
    from fizgig.web import jobs

    folder = require_folder(str(body.get("folder") or ""))
    settings = _settings(body, folder)
    return jobs.start_task("caption", "caption", settings, folder, lambda job_folder, _job: write_files(job_folder, settings))


def static(body: dict) -> dict:
    """Write the trigger word into each caption file. Mirrors ``generate_captions``."""
    folder = require_folder(str(body.get("folder") or ""))
    trigger = str(body.get("trigger") or "").strip()
    if not trigger:
        raise JobError(422, {"problems": ["Please enter a trigger word in the Trigger Word box first."]})
    overwrite = bool(body.get("overwrite"))
    allowed = set(IMAGE_EXTENSIONS)
    if body.get("include_video"):
        allowed |= _VIDEO
    created = skipped = 0
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if not os.path.isfile(full) or os.path.splitext(name)[1].lower() not in allowed:
            continue
        dest = os.path.splitext(full)[0] + ".txt"
        if os.path.exists(dest) and not overwrite:
            skipped += 1
            continue
        Path(dest).write_text(trigger, encoding="utf-8")
        created += 1
    return {"created": created, "skipped": skipped}


def _leaf(name: str) -> str:
    text = (name or "").replace("\\", "/")
    leaf = text.split("/")[-1]
    if text != leaf or leaf in {"", ".", ".."}:
        raise JobError(422, {"problems": ["unsafe name"]})
    return leaf


def listing(folder: str, query: str) -> dict:
    path = str(resolve_dir(require_folder(folder)))
    needle = (query or "").strip().lower()
    items = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if not os.path.isfile(full) or os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
            continue
        caption_path = os.path.splitext(full)[0] + ".txt"
        caption = ""
        if os.path.isfile(caption_path):
            caption = Path(caption_path).read_text(encoding="utf-8", errors="replace")
        if needle and needle not in name.lower() and needle not in caption.lower():
            continue
        items.append({
            "name": name,
            "caption": caption,
            "url": "/api/captions/image?folder=" + _quote(path) + "&name=" + _quote(name),
        })
    return {"folder": path, "items": items}


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def image_file(folder: str, name: str) -> Path:
    path = Path(resolve_dir(require_folder(folder)))
    leaf = _leaf(name)
    if Path(leaf).suffix.lower() not in IMAGE_EXTENSIONS:
        raise JobError(404, {"detail": "no such image"})
    found = (path / leaf).resolve()
    try:
        found.relative_to(path.resolve())
    except ValueError:
        raise JobError(404, {"detail": "no such image"}) from None
    if not found.is_file():
        raise JobError(404, {"detail": "no such image"})
    return found


def save_caption(folder: str, name: str, text: str) -> dict:
    found = image_file(folder, name)
    dest = found.with_suffix(".txt")
    tmp = dest.with_suffix(".txt.tmp")
    tmp.write_text(text if text is not None else "", encoding="utf-8")
    os.replace(tmp, dest)
    return {"name": found.name, "caption": text or ""}
