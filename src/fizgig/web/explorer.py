"""LoRA the Explorer on the engine host.

The worker imports this module, which calls ``install``. One session lives in
this process. ``lora_trainer_gui.py`` is not imported, and this module does not
import torch, the bake path, or a workbench engine.
"""
from __future__ import annotations

import math
import os
import threading
import time

from fizgig.web.jobs import JobError

_GPU_BUSY = "A training or caption job is using the GPU. Wait for it to finish before loading an engine."
_RESOLUTIONS = ("256", "384", "512", "768")
_MUTATION_CHOICES = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "14", "16")


def _fresh() -> dict:
    return {
        "baseline": None,
        "variants": [],
        "locked": set(),
        "last_pick": set(),
        "history": [],
        "loaded": False,
        "family": "",
        "anchor": "",
        "order": [],
        "primary": "",
        "image": "",
        "prev_locked": None,
        "prev_baseline": None,
        "intensity": 0.964,
        "mutations": 8,
        "structure": 1.0,
    }


_S = _fresh()


def _fake() -> bool:
    return os.environ.get("FIZGIG_WEB_FAKE_ENGINE") == "1"


def _as_int(value, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _strength(body: dict) -> float:
    """``LoRATrainerGUI._explorer_strength``."""
    if "strength" not in body or body.get("strength") in (None, ""):
        return 1.0
    return _as_float(body.get("strength"), 1.0)


def _families():
    from fizgig.families.registry import FAMILIES
    return [desc for desc in FAMILIES.values() if desc.training_ready and "explorer" in desc.workbench]


def _desc(family: str):
    from fizgig.families.registry import get as get_family
    desc = get_family(family)
    if desc is None:
        raise JobError(404, {"detail": "unknown family"})
    if not desc.training_ready or "explorer" not in desc.workbench:
        raise JobError(422, {"problems": ["That family has no Explorer."]})
    return desc


def _block_ids(desc) -> list[str]:
    from fizgig.web.repair import block_groups
    return [block["id"] for group in block_groups(desc) for block in group["blocks"]]


def _anchor_of(desc) -> str:
    """``LoRATrainerGUI._explorer_anchor_block``: the family's first block."""
    ids = _block_ids(desc)
    return ids[0] if ids else ""


def clear_session() -> None:
    """Empty the Explorer session."""
    global _S
    _S = _fresh()


def session_view() -> dict:
    """JSON-safe baseline blocks, frozen ids, last pick, history length, variant count."""
    baseline = _S["baseline"]
    blocks = {} if baseline is None else baseline.to_json()["blocks"]
    return {
        "blocks": blocks,
        "locked": sorted(_S["locked"]),
        "last_pick": sorted(_S["last_pick"]),
        "history": len(_S["history"]),
        "variants": len(_S["variants"]),
    }


def baseline():
    """The live baseline ``SliderState``, or None. Tests read it after ``load``."""
    return _S["baseline"]


def seed_baseline(state, active_ids=None, anchor: str = "") -> None:
    """Install a baseline with no engine. ``active_ids`` are the LoRA blocks a roll mutates."""
    clear_session()
    _S["baseline"] = state
    _S["order"] = list(state.blocks if active_ids is None else active_ids)
    _S["anchor"] = str(anchor or "")
    _S["loaded"] = True


def push_history(state=None, image: str = "", locked=None) -> None:
    """Push one undo entry the way ``_explorer_pick`` does before it rolls."""
    current = _S["baseline"] if state is None else state
    if current is None:
        raise JobError(422, {"problems": ["Load a LoRA before undoing."]})
    held = _S["locked"] if locked is None else locked
    _S["history"].append((current.copy(), str(image or ""), set(held)))


def roll_variants(state, active, mutations, intensity, structure, anchor, last_pick):
    """``LoRATrainerGUI._explorer_generate_baseline_and_roll``. Does not reseed."""
    out = []
    for vi in range(4):
        vs_structure = structure if vi < 2 else 0.0
        if vi == 3 and last_pick:
            protected = set(active) - set(last_pick)
            if len(protected) < 2:
                protected = set(active)
            target = protected
        else:
            target = set(active)
        out.append(state.mutate(target, num_mutations=int(mutations), intensity=float(intensity), structure=float(vs_structure), anchor=str(anchor)))
    return out


def _active() -> set:
    """LoRA blocks minus the frozen set. The anchor is added back when it is not frozen."""
    order = _S["order"]
    locked = _S["locked"]
    anchor = _S["anchor"]
    active = {bid for bid in order if bid not in locked}
    if anchor in order and anchor not in locked:
        active.add(anchor)
    return active


def _client_image(text) -> str:
    """An image inside the configured roots, or "" when the client sent none."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    from fizgig.web.fs import IMAGE_EXTENSIONS, resolve_file
    path = resolve_file(raw, "")
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise JobError(422, {"problems": [f"not an image: {path.name}"]})
    return str(path)


def _sync(body: dict) -> None:
    """Copy the roll fields onto the baseline the way ``_explorer_generate_baseline_and_roll`` does."""
    state = _S["baseline"]
    if "reference" in body:
        state.ref_image_path = _client_image(body.get("reference"))
    if "prompt" in body:
        state.prompt = str(body.get("prompt") or "")
    if "seed" in body:
        state.seed = _as_int(body.get("seed"), state.seed)
    if "resolution" in body:
        res = _as_int(body.get("resolution"), state.preview_width)
        state.preview_width = res
        state.preview_height = res
    if "ref_mp" in body or "ref_megapixels" in body:
        raw = body.get("ref_mp") if "ref_mp" in body else body.get("ref_megapixels")
        state.ref_megapixels = _as_float(raw, state.ref_megapixels)
    if "ref_strength" in body:
        state.ref_strength = _as_float(body.get("ref_strength"), state.ref_strength)
    if "intensity" in body:
        _S["intensity"] = _as_float(body.get("intensity"), _S["intensity"])
    if "mutations" in body:
        _S["mutations"] = _as_int(body.get("mutations"), _S["mutations"])
    if "structure" in body:
        _S["structure"] = _as_float(body.get("structure"), _S["structure"])


def _require_baseline():
    if _S["baseline"] is None:
        raise JobError(422, {"problems": ["Load a LoRA before exploring."]})
    return _S["baseline"]


def _render(params: dict, body: dict) -> int:
    from fizgig.web.engine_host import EngineError, get_host
    host = get_host()
    if not host.loaded or host.engine_name != "explorer":
        raise JobError(422, {"problems": ["Load a LoRA before rendering."]})
    try:
        gen = host.render(params)
    except EngineError as exc:
        raise JobError(422, {"problems": [exc.message]}) from exc
    return gen


def _roll(body: dict) -> dict:
    state = _require_baseline()
    _sync(body)
    variants = roll_variants(
        state, _active(), _S["mutations"], _S["intensity"], _S["structure"], _S["anchor"], _S["last_pick"],
    )
    _S["variants"] = variants
    params = {
        "states": [state.to_json(), *[item.to_json() for item in variants]],
        "steps": int(body.get("steps") or 5),
    }
    gen = _render(params, body)
    return {"gen": gen, "status": "running", "variants": [item.to_json() for item in variants]}


def _default_state(source):
    """A family's default blocks, with the current prompt, seed, size, reference, and load strength kept."""
    from fizgig.repair_studio.state import BlockState, SliderState
    order = _S["order"] or list(source.blocks)
    fresh = SliderState(blocks={bid: BlockState() for bid in order})
    fresh.prompt = source.prompt
    fresh.seed = source.seed
    fresh.preview_width = source.preview_width
    fresh.preview_height = source.preview_height
    fresh.ref_image_path = source.ref_image_path
    fresh.ref_megapixels = source.ref_megapixels
    fresh.ref_strength = source.ref_strength
    fresh.primary_scale = source.primary_scale
    fresh.donor_scale = 1.0
    return fresh


def _tweaked(state) -> set:
    """Disabled, or primary strength more than 0.01 from 1. ``_explorer_freeze_tweaked``."""
    found = set()
    for bid, block in state.blocks.items():
        if not block.primary_enabled or abs(block.primary_strength - 1.0) > 0.01:
            found.add(bid)
    return found


def _unload() -> None:
    from fizgig.web.engine_host import engine_loaded, get_host
    if not engine_loaded():
        return
    host = get_host()
    if host.engine_name == "explorer":
        host.unload()


def form(family: str = "") -> dict:
    """Explorer setup: families with ``explorer`` in the workbench, and the desktop field defaults."""
    rows = _families()
    if not rows:
        raise JobError(404, {"detail": "no explorer family"})
    chosen = family if any(desc.key == family for desc in rows) else rows[0].key
    desc = _desc(chosen)
    return {
        "family": desc.key,
        "display_name": desc.display_name,
        "families": [{"key": item.key, "name": item.display_name} for item in rows],
        "resolutions": list(_RESOLUTIONS),
        "mutations": list(_MUTATION_CHOICES),
        "anchor": _anchor_of(desc),
        "defaults": {
            "seed": "42",
            "resolution": "512",
            "intensity": 0.964,
            "mutations": "8",
            "structure": 1.0,
            "ref_megapixels": 1.0,
            "ref_strength": 1.0,
            "strength": 1.0,
        },
        "debounce_ms": 750,
    }


def load(body: dict) -> dict:
    """``LoRATrainerGUI._explorer_load_lora`` and ``_explorer_apply_strength``."""
    from fizgig.repair_studio.state import BlockState, SliderState
    from fizgig.web.engine_host import EngineError, get_host
    from fizgig.web.fs import resolve_file
    from fizgig.web.repair import gpu_free
    desc = _desc(str(body.get("family") or ""))
    lora = resolve_file(str(body.get("lora") or ""), ".safetensors")
    reference = _client_image(body.get("reference"))
    gpu_free()
    strength = _strength(body)
    if _fake():
        args = {"lora": str(lora), "strength": strength, "crash": bool(body.get("crash"))}
    else:
        from fizgig.web.repair import load_plan
        args = load_plan(desc, "fast")
        args["lora"] = str(lora)
        args["strength"] = strength
        args["crash"] = bool(body.get("crash"))
        settings = body.get("preview_settings")
        if desc.workbench_follows_samples and isinstance(settings, dict):
            args["preview_settings"] = {
                "steps": settings.get("steps") or "",
                "cfg": settings.get("cfg") or "",
                "negative": str(settings.get("negative") or ""),
                "turbo": settings.get("turbo") or "0",
            }
    host = get_host()
    try:
        host.load("explorer", desc.key, args)
    except EngineError as exc:
        text = exc.message
        if "GPU is in use" in text:
            raise JobError(409, {"detail": _GPU_BUSY}) from exc
        raise JobError(422, {"problems": [text]}) from exc
    ids = _block_ids(desc)
    state = SliderState(blocks={bid: BlockState() for bid in ids})
    state.prompt = str(body.get("prompt") or "")
    state.seed = _as_int(body.get("seed"), 42)
    res = _as_int(body.get("resolution"), 512)
    state.preview_width = res
    state.preview_height = res
    state.ref_image_path = reference
    if "ref_mp" in body or "ref_megapixels" in body:
        raw = body.get("ref_mp") if "ref_mp" in body else body.get("ref_megapixels")
        state.ref_megapixels = _as_float(raw, 1.0)
    if "ref_strength" in body:
        state.ref_strength = _as_float(body.get("ref_strength"), 1.0)
    state.primary_scale = strength
    state.donor_scale = 1.0
    clear_session()
    _S["baseline"] = state
    _S["order"] = ids
    _S["anchor"] = ids[0] if ids else ""
    _S["family"] = desc.key
    _S["primary"] = str(lora)
    _S["loaded"] = True
    view = session_view()
    view["loaded"] = True
    return view


def roll(body: dict) -> dict:
    """``LoRATrainerGUI._explorer_generate_baseline_and_roll``: four variants, then a host render."""
    return _roll(body)


def pick(body: dict) -> dict:
    """``LoRATrainerGUI._explorer_pick``: stack the baseline, adopt the variant, roll again."""
    _require_baseline()
    index = _as_int(body.get("index"), -1)
    variants = _S["variants"]
    if index < 0 or index >= len(variants):
        raise JobError(422, {"problems": ["No such variant."]})
    picked = variants[index]
    old = _S["baseline"]
    token = str(body.get("image") or _S["image"] or "")
    _S["history"].append((old.copy(), token, set(_S["locked"])))
    _S["last_pick"] = set(picked.diff_blocks(old))
    _S["baseline"] = picked.copy()
    _S["image"] = ""
    return _roll(body)


def freeze(body: dict) -> dict:
    """``LoRATrainerGUI._explorer_freeze_tweaked``. Does not render."""
    state = _require_baseline()
    choice = str(body.get("choice") or "")
    if choice == "cancel":
        return session_view()
    if choice == "undo":
        if _S["prev_locked"] is None:
            return session_view()
        _S["locked"] = set(_S["prev_locked"])
        if _S["prev_baseline"] is not None:
            _S["baseline"] = _S["prev_baseline"].copy()
        return session_view()
    if choice not in {"freeze", "add", "unlock"}:
        raise JobError(422, {"problems": ["Unknown freeze choice."]})
    tweaked = _tweaked(state)
    _S["prev_locked"] = set(_S["locked"])
    _S["prev_baseline"] = state.copy()
    if choice == "freeze":
        _S["locked"] = set(tweaked)
    elif choice == "add":
        _S["locked"] = set(_S["locked"]) | tweaked
    else:
        _S["locked"] = set()
    return session_view()


def undo(body: dict | None = None) -> dict:
    """``LoRATrainerGUI._explorer_undo``. Pops the stack and does not render."""
    del body
    if not _S["history"]:
        raise JobError(422, {"problems": ["Nothing to undo."]})
    prev, image, locked = _S["history"].pop()
    _S["baseline"] = prev
    _S["image"] = image
    _S["locked"] = set(locked)
    _S["variants"] = []
    return session_view()


def reset(body: dict) -> dict:
    """``LoRATrainerGUI._explorer_full_reset`` (``full``) and ``_explorer_restart`` (the other modes)."""
    mode = str(body.get("mode") or "")
    if mode == "full":
        _unload()
        clear_session()
        return session_view()
    state = _require_baseline()
    if mode not in {"defaults", "baseline"}:
        raise JobError(422, {"problems": ["Unknown reset."]})
    _S["history"].append((state.copy(), _S["image"], set(_S["locked"])))
    _S["locked"] = set()
    _S["last_pick"] = set()
    _S["variants"] = []
    if mode == "defaults":
        _S["baseline"] = _default_state(state)
    return session_view()


def save(body: dict | None = None) -> dict:
    """``LoRATrainerGUI._explorer_save``: the loaded engine's ``save_repaired``, else the file baker."""
    del body
    state = _require_baseline()
    if not _S["primary"]:
        raise JobError(422, {"problems": ["Load a LoRA before saving."]})
    from pathlib import Path
    from fizgig.web.repair import _free, _output_dir, _refuse_unmapped, engine_bake
    dest = _free(_output_dir() / f"{Path(_S['primary']).stem}_explored.safetensors")
    summary = engine_bake("explorer", state, str(dest), False)
    if summary is None:
        _refuse_unmapped(str(_S.get("family") or ""))
        from fizgig.repair_studio.bake import save_repaired_lora
        summary = save_repaired_lora(str(_S["primary"]), state, str(dest))
    return {"path": str(dest), "summary": summary}


def _pace() -> float:
    try:
        return float(os.environ.get("FIZGIG_WEB_FAKE_STEP", "0.05"))
    except ValueError:
        return 0.05


class ExplorerFake:
    """Fake Explorer engine. Sleeps once per step so a newer gen can cancel the roll."""

    def __init__(self):
        self.family = ""
        self.args: dict = {}
        self._cancel = threading.Event()

    def load(self, family: str, args: dict) -> None:
        if args.get("crash"):
            os._exit(1)
        self.family = family
        self.args = dict(args or {})

    def request_cancel(self) -> None:
        self._cancel.set()

    def clear_cancel(self) -> None:
        self._cancel.clear()

    def unload(self) -> None:
        self.args = {}

    def save_repaired(self, out_path, state, include_donor=True):
        from fizgig.web.engine_host import FakeEngine
        return FakeEngine.save_repaired(self, out_path, state, include_donor)

    def _sleep(self, delay: float) -> None:
        from fizgig.web.engine_host import Cancelled
        if self._cancel.is_set():
            raise Cancelled()
        end = time.monotonic() + max(0.0, delay)
        while time.monotonic() < end:
            if self._cancel.is_set():
                raise Cancelled()
            time.sleep(min(0.01, max(0.0, end - time.monotonic())))

    def render(self, _gen: int, params: dict, on_frame) -> dict:
        """One frame per state: ``baseline``, then ``variant``. ``records`` counts the states."""
        from fizgig.web.engine_host import Cancelled, png
        states = params.get("states") or []
        for _ in range(max(len(states), int(params.get("steps") or 1))):
            self._sleep(_pace())
        total = len(states)
        for index in range(total):
            if self._cancel.is_set():
                raise Cancelled()
            side = "baseline" if index == 0 else "variant"
            on_frame(index + 1, total, png(20, 40 + index * 30, 80), side)
        return {"baseline": png(180, 40, 40), "image": png(10, 160, 60), "records": {"count": total}}


class ExplorerAdapter:
    """Real workbench adapter. Imports the engine only when a real load runs."""

    def __init__(self):
        self.family = ""
        self.args: dict = {}
        self.engine = None
        self.primary = ""
        self._cancel = threading.Event()

    def load(self, family: str, args: dict) -> None:
        """``LoRATrainerGUI._explorer_ensure_engine_family``, then ``load_primary``."""
        from fizgig.families.registry import get as get_family
        from fizgig.web.engine_host import _blocks_to_swap, _sampling
        desc = get_family(family)
        if desc is None:
            raise RuntimeError("unknown family")
        if args.get("crash"):
            os._exit(1)
        self.family = family
        self.args = dict(args or {})
        engine = desc.make_workbench_engine()
        engine.turbo_preview = True
        if desc.workbench_follows_samples and args.get("preview_settings"):
            engine.preview_settings = dict(args["preview_settings"])
        call = {
            "dit_path": args.get("dit_path") or "",
            "vae_path": args.get("vae_path") or "",
            "text_encoder_path": args.get("text_encoder_path") or "",
            "speed_lora_path": args.get("speed_lora_path") or "",
            "preview_sampling": _sampling(args.get("preview_sampling")),
            "device": "cuda",
            "precision": args.get("precision") or "auto",
            "blocks_to_swap": _blocks_to_swap(args.get("blocks_to_swap")),
        }
        if desc.video_workbench:
            call["te_cache_dir"] = args.get("te_cache_dir") or ""
            call["audio_vae_path"] = ""
            call["base_mode"] = args.get("base_mode") or "auto"
        engine.ensure_pipeline(**call)
        lora = args.get("lora") or args.get("primary") or ""
        engine.load_primary(lora)
        self.engine = engine
        self.primary = lora

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
        if engine is not None and hasattr(engine, "reset"):
            engine.reset()

    def render(self, _gen: int, params: dict, on_frame) -> dict:
        """``LoRATrainerGUI._explorer_worker``: one preview per state, cache cleared between variants."""
        from fizgig.web.engine_host import Cancelled
        try:
            return self._previews(params, on_frame)
        except Cancelled:
            raise
        except Exception as exc:
            if type(exc).__name__ in {"RenderCancelled", "PreviewAborted", "SampleAborted"}:
                raise Cancelled() from exc
            raise

    def _previews(self, params: dict, on_frame) -> dict:
        import io
        from fizgig.repair_studio.state import SliderState
        from fizgig.web.engine_host import Cancelled
        engine = self.engine
        raw_states = params.get("states") or []
        total = len(raw_states)
        images = []
        for index, raw in enumerate(raw_states):
            if self._cancel.is_set():
                raise Cancelled()
            state = SliderState.from_json(raw if isinstance(raw, dict) else {})
            if index:
                engine._invalidate_activation_cache()
            engine._changed_blocks = set(state.blocks.keys())
            image = engine.generate_preview(state)
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            blob = buf.getvalue()
            on_frame(index + 1, total, blob, "baseline" if index == 0 else "variant")
            images.append(blob)
        return {
            "baseline": images[0] if images else None,
            "image": images[-1] if images else None,
            "records": {"count": total},
        }


def install() -> None:
    """Register the Explorer factory. The fake is used when ``FIZGIG_WEB_FAKE_ENGINE`` is ``1``."""
    from fizgig.web.engine_host import register_engine

    def factory():
        if os.environ.get("FIZGIG_WEB_FAKE_ENGINE") == "1":
            return ExplorerFake()
        return ExplorerAdapter()

    register_engine("explorer", factory)


install()
