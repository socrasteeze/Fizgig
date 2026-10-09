"""RefMod Studio on the engine host.

Mirrors ``create_refmod_studio_tab``, ``_rms_state``, ``_rms_setup_save``,
``_rms_setup_load``, ``_rms_rescan``, ``_rms_load``, ``_rms_engine_plan``,
``_rms_job`` and ``_rms_render``. The worker imports this module.

``lora_trainer_gui.py`` is not imported. Torch, the H3 engine and
``refmod_apply`` load only inside the real adapter's methods.
"""
from __future__ import annotations

import decimal
import json
import os
import threading
from pathlib import Path

from fizgig.web.engine_host import FakeEngine, register_engine
from fizgig.web.fs import resolve_dir, resolve_file
from fizgig.web.jobs import JobError

_REPO = Path(__file__).resolve().parents[3]
_GPU_BUSY = "A training or caption job is using the GPU. Wait for it to finish before loading an engine."
_PROMPT = "a woman smiles at the camera, soft window light"
_MODELS = ("Reference (ref2va)", "First / Last Frame (fl2va)")
_BASES = (
    "Auto (by free VRAM)",
    "Stream blocks (exact int8, room for big clips)",
    "NF4 (smallest, 9.5% base error)",
)
_LENGTHS = {
    "Still (1 frame)": 1,
    "22 frames (~1s)": 22,
    "39 frames (~1.6s)": 39,
    "56 frames (~2.3s)": 56,
    "73 frames (~3s)": 73,
}
_COMPARES = ("No mod (LoRA alone)", "No LoRA (mods alone)", "Neither (base model)")
_COMPARE_MODE = {
    "No mod (LoRA alone)": "nomod",
    "No LoRA (mods alone)": "nolora",
    "Neither (base model)": "neither",
}
_SIZES = ("512", "640", "768", "960", "1024", "1152", "1280", "1536")
_DIRECTIONS = ("constant", "concept_at_start", "concept_at_middle", "concept_at_end", "concept_at_ends")
_SHAPES = (
    "linear", "ease", "sigmoid", "tanh", "quadratic", "cubic",
    "exponential", "stair", "elastic", "bump", "dip",
)
_CURVE = ["concept_at_start", "ease", 1.0]


def _step_delay() -> float:
    try:
        return float(os.environ.get("FIZGIG_WEB_FAKE_STEP", "0.05"))
    except ValueError:
        return 0.05


def _plain(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return [_plain(item) for item in sorted(value, key=lambda item: str(item))]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _records(params: dict) -> dict:
    setup = params.get("setup") if isinstance(params.get("setup"), dict) else {}
    if params.get("early_step") is not None:
        try:
            early = int(params.get("early_step") or 0)
        except (TypeError, ValueError):
            early = 0
    else:
        try:
            early = int(setup.get("early_step") or 0)
        except (TypeError, ValueError):
            early = 0
    rows = setup.get("rows") if isinstance(setup.get("rows"), list) else []
    return {
        "seed": setup.get("seed"),
        "prompt": setup.get("prompt"),
        "early_step": early,
        "compare": setup.get("compare"),
        "rows": _plain(rows),
    }


class RefmodFake(FakeEngine):
    """Fake RefMod engine. Sleeps per step and writes tiny PNGs. No model import."""

    def __init__(self):
        super().__init__("refmod")

    def render(self, gen: int, params: dict, on_frame) -> dict:
        from fizgig.web.engine_host import png
        steps = max(1, int(params.get("steps") or 3))
        early = int(params.get("early_step") or 0)
        delay = _step_delay()
        for step in range(1, steps + 1):
            self._sleep(delay)
            if early > 0 and step == early:
                on_frame(step, steps, png(30, 90, 140), "early")
        return {
            "baseline": png(180, 40, 40),
            "image": png(10, 160, 60),
            "clip": None,
            "records": _records(params),
        }


class RefmodEngine:
    """Real H3 adapter. Heavy imports stay inside the methods."""

    def __init__(self):
        self.family = ""
        self.args: dict = {}
        self.engine = None
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()
        engine = self.engine
        if engine is not None and hasattr(engine, "request_cancel"):
            engine.request_cancel()

    def clear_cancel(self) -> None:
        self._cancel.clear()
        engine = self.engine
        if engine is not None and hasattr(engine, "clear_cancel"):
            engine.clear_cancel()

    def unload(self) -> None:
        engine = self.engine
        self.engine = None
        self.args = {}
        if engine is not None and hasattr(engine, "reset"):
            engine.reset()

    def load(self, family: str, args: dict) -> None:
        """``LoRATrainerGUI._rms_load`` / ``_rms_engine_plan``."""
        self.family = family or "minimax"
        self.args = dict(args or {})
        plan = _engine_plan(self.args)
        from fizgig.families.registry import get as get_family
        desc = get_family(self.family)
        if desc is None:
            raise RuntimeError("unknown family")
        engine = desc.make_workbench_engine()
        engine.int8_attention = True
        engine.ensure_pipeline(**plan)
        self.engine = engine

    def render(self, gen: int, params: dict, on_frame) -> dict:
        """``LoRATrainerGUI._rms_render``."""
        from fizgig.web.engine_host import Cancelled
        del gen
        try:
            return self._paint(params, on_frame)
        except Cancelled:
            raise
        except Exception as exc:
            if type(exc).__name__ in {"RenderCancelled", "PreviewAborted", "SampleAborted"}:
                raise Cancelled() from exc
            raise

    def _paint(self, params: dict, on_frame) -> dict:
        from fizgig.web.engine_host import Cancelled
        engine = self.engine
        if engine is None:
            raise RuntimeError("Base not loaded.")
        state = params.get("setup") if isinstance(params.get("setup"), dict) else {}
        steps = _steps(params.get("steps") if params.get("steps") is not None else state.get("steps"))
        if params.get("early_step") is None:
            early = 2 if state.get("early") and steps > 2 else 0
        else:
            early = int(params.get("early_step") or 0)
        width, height = _size(state.get("width"), state.get("height"))
        frames = int(_LENGTHS.get(str(state.get("frames") or ""), 1))
        prompt = "" if state.get("prompt") is None else str(state.get("prompt"))
        compare = _compare_mode(state)
        lora = str(state.get("lora") or "")
        audio = str(getattr(engine, "_audio_vae_path", "") or "")
        with_audio = bool(state.get("sound") and audio and os.path.isfile(audio))
        latents, schedule, entries, numbered = _bundle(state)

        def on_early(image, step, total, _early=early):
            if _early:
                on_frame(int(step), int(total), _png_bytes(image), "early")

        self.clear_cancel()
        self._sync_lora(lora)
        if self._cancel.is_set():
            raise Cancelled()
        ref_items = engine.reference_items(latents, entries) if numbered and latents else None
        tweaked = engine.render_refmod(
            seed=_seed(state.get("seed")), prompt=prompt, width=width, height=height, frames=frames,
            regime="custom", ref_latents=latents, ref_schedule=schedule, with_audio=with_audio,
            early_step=early, on_early=on_early if early else None, steps=steps,
            turbo_strength=_turbo(state.get("turbo")), ref_items=ref_items,
        )
        if self._cancel.is_set():
            raise Cancelled()
        keep = compare == "nolora"
        baseline = engine.render_refmod(
            seed=_seed(state.get("seed")), prompt=prompt, width=width, height=height, frames=frames,
            regime="custom", with_audio=with_audio, steps=steps, turbo_strength=_turbo(state.get("turbo")),
            ref_latents=latents if keep else None, ref_schedule=schedule if keep else None,
            ref_items=ref_items if keep else None, no_lora=compare in {"nolora", "neither"},
        )
        return {
            "baseline": _png_bytes(baseline["middle"]),
            "image": _png_bytes(tweaked["middle"]),
            "clip": None,
            "records": _records(params),
        }

    def _sync_lora(self, path: str) -> None:
        """``LoRATrainerGUI._rms_sync_lora``."""
        engine = self.engine
        current = engine.primary_path if getattr(engine, "primary_network", None) is not None else None
        if not path:
            if current:
                engine.unload_primary()
            return
        if current and os.path.normcase(current) == os.path.normcase(path):
            return
        if current and engine.swap_primary_weights(path):
            return
        if current:
            engine.unload_primary()
        engine.load_primary(path)


def _png_bytes(image) -> bytes:
    import io
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _engine_plan(args: dict) -> dict:
    """``LoRATrainerGUI._rms_engine_plan`` and ``_rms_base_mode``."""
    from fizgig.families.registry import get as get_family
    from fizgig.web.prefs import roots_from_prefs
    desc = get_family("minimax")
    if desc is None:
        raise RuntimeError("unknown family")
    prefs = roots_from_prefs()

    def lookup(key):
        return str(prefs.get(key) or "").strip()

    model = str(args.get("model") or "")
    fl2va = model.startswith("First")
    dit_label = ("MiniMax H3 DiT (first/last frame / fl2va)" if fl2va
                 else "MiniMax H3 DiT (reference / ref2va)")
    dit = desc.model_path("dit" if fl2va else "ref_dit", lookup)
    vae = desc.model_path("vae", lookup)
    text = desc.model_path("text_encoder", lookup)
    for label, path in (
        (dit_label, dit),
        ("MiniMax H3 video VAE", vae),
        ("Qwen3-VL-32B text encoder", text),
    ):
        if not path or not os.path.exists(path):
            raise RuntimeError(f"{label} path not set or not found.")
    audio = desc.model_path("audio_vae", lookup)
    if audio and not os.path.exists(audio):
        audio = ""
    cache = str(prefs.get("cache_dir") or "").strip()
    base = str(args.get("base") or "")
    if base.startswith("Stream"):
        mode = "stream"
    elif base.startswith("NF4"):
        mode = "nf4"
    else:
        mode = "auto"
    return {
        "dit_path": dit,
        "vae_path": vae,
        "text_encoder_path": text,
        "device": "cuda",
        "speed_lora_path": desc.model_path("speed_lora", lookup),
        "turbo_lora_strength": 0.75,
        "te_cache_dir": str(Path(cache) / "te_prompts") if cache else "",
        "audio_vae_path": audio,
        "base_mode": mode,
    }


def _latent(meta: dict):
    from safetensors import safe_open
    path = str(meta.get("path") or "")
    label = str(meta.get("name") or "mod")
    if not path or not os.path.isfile(path):
        raise RuntimeError(f"{label} file not found.")
    with safe_open(path, framework="pt", device="cpu") as handle:
        return handle.get_tensor(str(meta.get("tensor_key") or "latent")).clone()


def _bundle(state: dict):
    """``LoRATrainerGUI._rms_job`` (bundle, step schedule, numbered references)."""
    from fizgig.minimax import refmod_apply as ra
    folder = str(state.get("folder") or "")
    found = {}
    names: list[str] = []
    if folder and os.path.isdir(folder):
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
    if any(name.lower().endswith(".safetensors") for name in names):
        for item in ra.scan_refmods(folder):
            found[str(item.get("name") or "")] = item
    rows = []
    for raw in state.get("rows") or []:
        if not isinstance(raw, dict):
            continue
        meta = found.get(str(raw.get("mod") or ""))
        if not meta:
            continue
        try:
            copies = int(raw.get("copies") or 1)
        except (TypeError, ValueError):
            copies = 1
        try:
            value = float(raw.get("value") or 0)
        except (TypeError, ValueError):
            value = 0.0
        rows.append(ra.ModRow(
            _latent(meta), meta, value=value, copies=max(1, min(10, copies)),
            enabled=bool(raw.get("on")), name=str(meta.get("name") or ""),
        ))
    numbered = bool(state.get("numbered"))
    try:
        retention = float(state.get("retention"))
    except (TypeError, ValueError):
        retention = 1.0
    frame = tuple(state.get("frame_curve") or _CURVE)
    step = tuple(state.get("step_curve") or _CURVE)
    try:
        scramble = int(str(state.get("scramble")).strip())
    except (TypeError, ValueError):
        scramble = -1
    if numbered:
        latents, _describe, entries = ra.build_bundle_entries(rows, retention=1.0, curve=None, scramble_seed=-1)
        return latents, None, entries, True
    latents, _describe, entries = ra.build_bundle_entries(
        rows, retention=retention, curve=frame, scramble_seed=scramble)
    schedule = ra.step_schedule(step, latents) if state.get("step_on") else None
    return latents, schedule, entries, False


def _flag(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _text(value, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _round3(value) -> float:
    if value is None or value == "":
        return 0.0
    number = decimal.Decimal(str(float(value)))
    return float(number.quantize(decimal.Decimal("0.001"), rounding=decimal.ROUND_HALF_UP))


def _rows(raw) -> list:
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            copies = int(item.get("copies"))
        except (TypeError, ValueError):
            copies = 1
        try:
            value = _round3(item.get("value"))
        except (TypeError, ValueError, decimal.InvalidOperation):
            value = 0.0
        rows.append({
            "on": bool(item.get("on")),
            "mod": str(item.get("mod") or ""),
            "value": value,
            "copies": max(1, min(10, copies)),
        })
    return rows


def _curve_list(raw) -> list:
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return [str(raw[0]), str(raw[1]), float(raw[2])]
        except (TypeError, ValueError):
            pass
    return list(_CURVE)


def _retention(value) -> float:
    if value is None or value == "":
        return 1.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, number))


def _steps(raw) -> int:
    if raw is None or raw == "":
        return 4
    try:
        return max(1, min(40, int(float(str(raw).strip()))))
    except (TypeError, ValueError):
        return 4


def _seed(raw) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 300


def _turbo(raw) -> float:
    try:
        return max(0.0, min(1.5, float(str(raw).strip())))
    except (TypeError, ValueError):
        return 1.0


def _size(raw_w, raw_h) -> tuple[int, int]:
    try:
        width, height = int(raw_w), int(raw_h)
    except (TypeError, ValueError):
        return 640, 768
    return max(256, width // 32 * 32), max(256, height // 32 * 32)


def _compare_mode(state: dict) -> str:
    """``LoRATrainerGUI._rms_compare_mode``."""
    lora = str(state.get("lora") or "").strip()
    if not lora or not os.path.isfile(lora):
        return "nomod"
    return _COMPARE_MODE.get(str(state.get("compare") or ""), "nomod")


def _state(source: dict) -> dict:
    """``LoRATrainerGUI._rms_state``."""
    source = source or {}
    prompt = source["prompt"] if "prompt" in source and source.get("prompt") is not None else _PROMPT
    return {
        "base": str(source.get("base") or _BASES[0]),
        "model": str(source.get("model") or _MODELS[0]),
        "prompt": str(prompt),
        "seed": _text(source.get("seed"), "300"),
        "frames": _text(source.get("frames"), "22 frames (~1s)"),
        "width": _text(source.get("width"), "640"),
        "height": _text(source.get("height"), "768"),
        "steps": _text(source.get("steps"), "4"),
        "turbo": _text(source.get("turbo"), "1.0"),
        "sound": _flag(source.get("sound"), True),
        "early": _flag(source.get("early"), True),
        "folder": str(source.get("folder") or "").strip(),
        "rows": _rows(source.get("rows")),
        "retention": _retention(source.get("retention") if "retention" in source else None),
        "scramble": _text(source.get("scramble"), "-1"),
        "frame_curve": _curve_list(source.get("frame_curve")),
        "step_curve": _curve_list(source.get("step_curve")),
        "step_on": _flag(source.get("step_on"), False),
        "numbered": _flag(source.get("numbered"), False),
        "lora": str(source.get("lora") or "").strip(),
        "compare": str(source.get("compare") or _COMPARES[0]),
    }


def _folder_arg(body: dict) -> str:
    text = str(body.get("folder") or "").strip()
    if not text:
        return ""
    return str(resolve_dir(text))


def _lora_arg(body: dict) -> str:
    text = str(body.get("lora") or "").strip()
    if not text:
        return ""
    return str(resolve_file(text, ".safetensors"))


def _preset_name(name: str) -> str:
    text = str(name or "").strip()
    if not text or text in {".", ".."} or any(char in text for char in '\\/:*?"<>|'):
        raise JobError(422, {"problems": ["Invalid preset name."]})
    path = Path(text)
    if path.name != text or path.stem != text or path.suffix:
        raise JobError(422, {"problems": ["Invalid preset name."]})
    return text


def _gpu_free() -> None:
    from fizgig.gpu_lock import held
    from fizgig.web.engine_host import engine_loaded
    from fizgig.web.jobs import _busy
    if engine_loaded():
        return
    if _busy() or held():
        raise JobError(409, {"detail": _GPU_BUSY})


def preset_root() -> Path:
    override = os.environ.get("FIZGIG_WEB_PRESET_ROOT", "").strip()
    return Path(override) if override else _REPO / "presets"


def preset_dir() -> Path:
    """``LoRATrainerGUI._rms_setup_dir``."""
    folder = preset_root() / "refmod_studio"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def install() -> None:
    """Register the refmod factory. The worker imports this module."""
    def factory():
        if os.environ.get("FIZGIG_WEB_FAKE_ENGINE") == "1":
            return RefmodFake()
        return RefmodEngine()

    register_engine("refmod", factory)


def form() -> dict:
    """``LoRATrainerGUI.create_refmod_studio_tab``."""
    saved = []
    try:
        saved = [path.stem for path in sorted(preset_dir().glob("*.json"), key=lambda item: item.name.lower())]
    except OSError:
        saved = []
    return {
        "model": _MODELS[0],
        "base": _BASES[0],
        "prompt": _PROMPT,
        "seed": "300",
        "frames": "22 frames (~1s)",
        "width": "640",
        "height": "768",
        "steps": "4",
        "turbo": "1.0",
        "sound": True,
        "early": True,
        "retention": 1.0,
        "scramble": "-1",
        "frame_curve": list(_CURVE),
        "step_curve": list(_CURVE),
        "step_on": False,
        "numbered": False,
        "compare": _COMPARES[0],
        "rows": [],
        "folder": "",
        "lora": "",
        "debounce_redraw_ms": 60,
        "models": list(_MODELS),
        "bases": list(_BASES),
        "lengths": list(_LENGTHS),
        "compares": list(_COMPARES),
        "sizes": list(_SIZES),
        "directions": list(_DIRECTIONS),
        "shapes": list(_SHAPES),
        "presets": saved,
    }


def scan(body: dict) -> dict:
    """``LoRATrainerGUI._rms_rescan`` via ``refmod_apply.scan_refmods`` (audio stays out)."""
    text = str((body or {}).get("folder") or "").strip()
    if not text:
        return {"mods": []}
    folder = Path(text)
    if not folder.is_dir():
        return {"mods": []}
    folder = resolve_dir(text)
    if not _has_safetensors(folder):
        return {"mods": []}
    from fizgig.minimax.refmod_apply import scan_refmods
    mods = []
    for item in scan_refmods(str(folder)):
        mods.append({
            "name": str(item.get("name") or ""),
            "kind": str(item.get("kind") or ""),
            "path": str(item.get("path") or ""),
        })
    return {"mods": mods}


def _has_safetensors(folder: Path) -> bool:
    try:
        children = list(folder.iterdir())
    except OSError:
        return False
    return any(child.is_file() and child.suffix.lower() == ".safetensors" for child in children)


def load(body: dict) -> dict:
    """``LoRATrainerGUI._rms_load``."""
    from fizgig.web.engine_host import EngineError, get_host
    body = body or {}
    _gpu_free()
    args = {
        "folder": _folder_arg(body),
        "lora": _lora_arg(body),
        "model": str(body.get("model") or _MODELS[0]),
        "base": str(body.get("base") or _BASES[0]),
    }
    if body.get("crash"):
        args["crash"] = True
    host = get_host()
    try:
        host.load("refmod", "minimax", args)
    except EngineError as exc:
        text = exc.message
        if "GPU is in use" in text:
            raise JobError(409, {"detail": _GPU_BUSY}) from exc
        raise JobError(422, {"problems": [text]}) from exc
    return host.status()


def render(body: dict) -> dict:
    """``LoRATrainerGUI._rms_render``. A higher ``gen`` cancels the one in flight."""
    from fizgig.web.engine_host import EngineError, get_host
    body = body or {}
    host = get_host()
    if not host.loaded or host.engine_name != "refmod":
        raise JobError(422, {"problems": ["Load the base before rendering."]})
    source = body.get("setup") if isinstance(body.get("setup"), dict) else body
    steps = _steps(body["steps"] if "steps" in body else source.get("steps"))
    state = _state(source)
    if state["folder"]:
        state["folder"] = str(resolve_dir(state["folder"]))
    if state["lora"]:
        state["lora"] = str(resolve_file(state["lora"], ".safetensors"))
    early_step = 2 if state["early"] and steps > 2 else 0
    state["early_step"] = early_step
    params = {"steps": steps, "early_step": early_step, "setup": state, "video": True}
    try:
        gen = host.render(params, None if body.get("gen") is None else int(body.get("gen")))
    except (EngineError, TypeError, ValueError) as exc:
        message = exc.message if isinstance(exc, EngineError) else str(exc)
        raise JobError(422, {"problems": [message]}) from exc
    return {"gen": gen, "status": "running"}


def presets() -> dict:
    """``LoRATrainerGUI._rms_setup_dir``."""
    folder = preset_dir()
    names = []
    try:
        names = [path.stem for path in sorted(folder.glob("*.json"), key=lambda item: item.name.lower())]
    except OSError:
        names = []
    return {"dir": str(folder), "presets": names}


def save_preset(body: dict) -> dict:
    """``LoRATrainerGUI._rms_setup_save``: the ``_rms_state`` object, indent 2."""
    body = body or {}
    name = _preset_name(str(body.get("name") or ""))
    payload = _state(body)
    path = preset_dir() / f"{name}.json"
    if path.exists() and not body.get("overwrite"):
        raise JobError(409, {"detail": f"Preset '{name}' already exists."})
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"name": name, "path": str(path)}


def read_preset(name: str) -> dict:
    """``LoRATrainerGUI._rms_setup_load``."""
    stem = _preset_name(name)
    path = preset_dir() / f"{stem}.json"
    if not path.is_file():
        raise JobError(404, {"detail": "no such preset"})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobError(422, {"problems": ["Load failed."]}) from exc
    if not isinstance(data, dict):
        raise JobError(422, {"problems": ["Load failed."]})
    return data


install()
