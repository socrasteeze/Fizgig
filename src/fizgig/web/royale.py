"""LoRA Royale on the engine host. The worker imports this module.

Mirrors ``create_lora_royale_tab``, ``_royale_scan``, ``_royale_render``,
``_royale_journey_seeds``, ``_royale_seed_travel``, ``_royale_lora_travel``,
``_royale_prompt_travel``, ``_royale_export`` and ``_royale_export_worker``.
The argv is the one ``lora_royale.export.write_mp4`` builds.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from fizgig.web.jobs import JobError

_GPU_BUSY = "A training or caption job is using the GPU. Wait for it to finish before loading an engine."
_SPEED_FPS = {"Slow": 14, "Normal": 22, "Fast": 32}
_MAX = ("All", "6", "8", "10", "12", "16", "20")
_CANCELLED = {"RenderCancelled", "PreviewAborted", "SampleAborted"}


def _fake() -> bool:
    return os.environ.get("FIZGIG_WEB_FAKE_ENGINE") == "1"


def _even(n: int) -> int:
    """``lora_royale.export._even``, then at least 2 (``write_mp4``)."""
    value = int(n)
    value = value if value % 2 == 0 else value - 1
    return max(2, value)


def _number(value, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def select_epochs(items, max_renders):
    """The evenly spaced subset in ``LoRATrainerGUI._royale_render``."""
    if max_renders is None or max_renders == "" or max_renders == "All":
        return list(items)
    n = int(max_renders)
    if n < 2 or len(items) <= n:
        return list(items)
    idx = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
    return [items[i] for i in idx]


def journey_seeds(start, end, n):
    """``LoRATrainerGUI._royale_journey_seeds``. Mids come from ``start`` only."""
    import random

    n = max(2, int(n))
    start, end = int(start), int(end)
    if n == 2:
        return [start, end]
    rng = random.Random(start * 2654435761 + 12345)
    mids = [rng.randint(0, 2**31 - 1) for _ in range(n - 2)]
    return [start] + mids + [end]


def ffmpeg_command(binary, width, height, fps, path) -> list[str]:
    """The argv ``lora_royale.export.write_mp4`` passes to ffmpeg."""
    w, h = _even(width), _even(height)
    return [
        str(binary), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(int(fps)), "-i", "-",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", "-preset", "medium", "-movflags", "+faststart", str(path),
    ]


def _fps(speed: str) -> int:
    return _SPEED_FPS.get(speed, _SPEED_FPS["Normal"])


def _families():
    from fizgig.families.registry import FAMILIES
    return [desc for desc in FAMILIES.values() if desc.training_ready and "royale" in desc.workbench]


def _desc(family: str):
    rows = _families()
    if not rows:
        raise JobError(404, {"detail": "no royale family"})
    if not family:
        return rows[0]
    found = next((item for item in rows if item.key == family), None)
    if found is None:
        raise JobError(422, {"problems": ["That family has no LoRA Royale."]})
    return found


def _gpu_free() -> None:
    from fizgig.gpu_lock import held
    from fizgig.web.engine_host import engine_loaded
    from fizgig.web.jobs import _busy
    if engine_loaded():
        return
    if _busy() or held():
        raise JobError(409, {"detail": _GPU_BUSY})


def _epochs(raw) -> list[dict]:
    found = []
    for item in raw or []:
        if isinstance(item, dict):
            found.append({"label": item.get("label"), "path": str(item.get("path") or "")})
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            found.append({"label": item[0], "path": str(item[1])})
    return found


def scan(body: dict) -> dict:
    """``LoRATrainerGUI._royale_scan``. One LoRA path is a single ``(stem, path)`` item."""
    from fizgig.lora_royale.scan import scan_checkpoints
    from fizgig.web.fs import resolve_dir, resolve_file
    body = body or {}
    if str(body.get("lora") or "").strip():
        path = resolve_file(str(body.get("lora")), ".safetensors")
        return {"items": [{"label": path.stem, "path": str(path)}]}
    text = str(body.get("folder") or "").strip()
    if not text or not Path(text).is_dir():
        return {"items": []}
    folder = resolve_dir(text)
    pairs = scan_checkpoints(str(folder))
    return {"items": [{"label": label, "path": path} for label, path in pairs]}


def form(family: str = "") -> dict:
    """Setup fields from ``create_lora_royale_tab`` for families with royale in the workbench."""
    rows = _families()
    if not rows:
        raise JobError(404, {"detail": "no royale family"})
    chosen = family if any(item.key == family for item in rows) else rows[0].key
    desc = next(item for item in rows if item.key == chosen)
    return {
        "family": desc.key,
        "display_name": desc.display_name,
        "families": [
            {"key": item.key, "name": item.display_name, "video": bool(item.video_workbench)}
            for item in rows
        ],
        "prompt": "",
        "seed": "42",
        "width": "512",
        "height": "512",
        "reference": "",
        "max_renders": "12",
        "max_renders_choices": list(_MAX),
        "speeds": list(_SPEED_FPS),
        "formats": ["MP4", "GIF"],
        "speed": "Normal",
        "format": "MP4",
    }


def _load_args(desc, body: dict) -> dict:
    from fizgig.web.fs import resolve_dir, resolve_file
    lora = str(body.get("lora") or "").strip()
    folder = str(body.get("folder") or "").strip()
    if _fake():
        args = {"crash": bool(body.get("crash"))}
        if lora:
            args["lora"] = str(resolve_file(lora, ".safetensors"))
        elif folder and Path(folder).is_dir():
            args["folder"] = str(resolve_dir(folder))
        return args
    from fizgig.web.repair import load_plan
    plan = load_plan(desc, "fast")
    if lora:
        plan["lora"] = str(resolve_file(lora, ".safetensors"))
    if folder and Path(folder).is_dir():
        plan["folder"] = str(resolve_dir(folder))
    settings = body.get("preview_settings")
    if desc.workbench_follows_samples and isinstance(settings, dict):
        plan["preview_settings"] = dict(settings)
    return plan


def load(body: dict) -> dict:
    """``_royale_validate_models_family`` then the engine host. Fake args are the lora or folder and crash."""
    from fizgig.web.engine_host import EngineError, get_host
    desc = _desc(str((body or {}).get("family") or ""))
    _gpu_free()
    try:
        args = _load_args(desc, body or {})
    except JobError:
        raise
    host = get_host()
    try:
        host.load("royale", desc.key, args)
    except EngineError as exc:
        text = exc.message
        if "GPU is in use" in text:
            raise JobError(409, {"detail": _GPU_BUSY}) from exc
        raise JobError(422, {"problems": [text]}) from exc
    return host.status()


def _host_render(params: dict, gen):
    from fizgig.web.engine_host import EngineError, get_host
    host = get_host()
    if not host.loaded or host.engine_name != "royale":
        raise JobError(422, {"problems": ["Load a LoRA before rendering."]})
    try:
        return host.render(params, None if gen is None else int(gen))
    except EngineError as exc:
        raise JobError(422, {"problems": [exc.message]}) from exc


def render(body: dict) -> dict:
    """``LoRATrainerGUI._royale_render``: one seed, the selected epochs."""
    body = body or {}
    raw = body.get("epochs")
    if raw is None:
        raw = body.get("items")
    epochs = _epochs(select_epochs(_epochs(raw), body.get("max_renders")))
    from fizgig.web.fs import resolve_file
    for item in epochs:
        if item["path"]:
            item["path"] = str(resolve_file(item["path"], ".safetensors"))
    steps = body.get("steps")
    count = max(1, len(epochs)) if steps is None or steps == "" else max(1, int(steps))
    params = {
        "mode": "epochs",
        "seed": _number(body.get("seed"), 42),
        "prompt": str(body.get("prompt") or ""),
        "width": _number(body.get("width"), 512),
        "height": _number(body.get("height"), 512),
        "reference": _client_image(body.get("reference")),
        "epochs": epochs,
        "steps": count,
    }
    gen = _host_render(params, body.get("gen"))
    return {"gen": gen, "status": "running", "epochs": epochs}


def _words(body: dict) -> list[str]:
    from fizgig.lora_royale.prompt_travel import parse_custom, waypoints_for
    raw = body.get("words")
    if isinstance(raw, str):
        return parse_custom(raw)
    if isinstance(raw, list) and raw:
        return [str(word).strip() for word in raw if str(word).strip()]
    if body.get("dimension"):
        return list(waypoints_for(str(body.get("dimension"))))
    return []


def travel(body: dict) -> dict:
    """``_royale_seed_travel``, ``_royale_lora_travel``, or ``_royale_prompt_travel``."""
    from fizgig.web.fs import resolve_file
    body = body or {}
    kind = str(body.get("mode") or body.get("kind") or "")
    if kind not in {"seed", "strength", "prompt"}:
        raise JobError(422, {"problems": ["Travel mode must be seed, strength, or prompt."]})
    n = max(2, _number(body.get("frames"), 2))
    params = {
        "mode": "travel",
        "kind": kind,
        "steps": n,
        "prompt": str(body.get("prompt") or body.get("base") or ""),
        "seed": _number(body.get("seed"), 42),
        "width": _number(body.get("width"), 512),
        "height": _number(body.get("height"), 512),
        "reference": _client_image(body.get("reference")),
    }
    path = str(body.get("path") or body.get("lora") or "").strip()
    if path:
        params["path"] = str(resolve_file(path, ".safetensors"))
    extra: dict = {}
    if kind == "seed":
        seed_a = body.get("seed") if body.get("seed_a") in (None, "") else body.get("seed_a")
        seed_b = 0 if body.get("seed_b") in (None, "") else body.get("seed_b")
        waypoints = 2 if body.get("waypoints") in (None, "") else body.get("waypoints")
        seeds = journey_seeds(seed_a if seed_a not in (None, "") else 42, seed_b, waypoints)
        params["seeds"] = seeds
        extra["seeds"] = seeds
    elif kind == "strength":
        start = _float(body.get("s_start"), 0.0)
        end = _float(body.get("s_end"), 1.0)
        strengths = [start + (end - start) * (i / (n - 1)) for i in range(n)]
        params["strengths"] = strengths
        extra["strengths"] = strengths
    else:
        from fizgig.lora_royale.prompt_travel import build_waypoint_prompts
        words = _words(body)
        base = str(body.get("base") or body.get("prompt") or "")
        prompts = build_waypoint_prompts(base, words)
        params["prompt"] = base
        params["prompts"] = prompts
        extra["prompts"] = prompts
    gen = _host_render(params, body.get("gen"))
    return {"gen": gen, "status": "running", "frames": n, **extra}


def _image_size(path: str, body: dict) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(path) as image:
            return int(image.size[0]), int(image.size[1])
    except Exception:
        return _number(body.get("width"), 512), _number(body.get("height"), 512)


def _binary() -> str:
    from fizgig.lora_royale.export import _find_ffmpeg
    return _find_ffmpeg() or "ffmpeg"


def _output_dir() -> str:
    from fizgig.web.prefs import roots_from_prefs
    folder = str(roots_from_prefs().get("lora_output_dir") or "").strip()
    if not folder:
        raise JobError(422, {"problems": ["Set the LoRA output folder in Preferences."]})
    return folder


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


def export(body: dict) -> dict:
    """``LoRATrainerGUI._royale_export``. The job command is the ``write_mp4`` argv."""
    from fizgig.lora_royale.scan import run_name_for_folder
    from fizgig.web import jobs
    from fizgig.web.fs import resolve_dir
    body = body or {}
    images = [str(item) for item in (body.get("images") or []) if str(item or "").strip()]
    if not images:
        raise JobError(422, {"problems": ["Render some epochs first, then export the morph."]})
    images = [_client_image(item) for item in images]
    fmt = str(body.get("format") or "MP4").upper()
    if fmt not in {"MP4", "GIF"}:
        fmt = "MP4"
    speed = str(body.get("speed") or "Normal")
    if speed not in _SPEED_FPS:
        speed = "Normal"
    folder_text = str(body.get("folder") or "").strip()
    run = run_name_for_folder(str(resolve_dir(folder_text))) if folder_text else ""
    run = run or "lora"
    dest = str(Path(_output_dir()) / f"{run}-royale{'.mp4' if fmt == 'MP4' else '.gif'}")
    width, height = _image_size(images[0], body)
    values = {
        "images": images,
        "format": fmt,
        "speed": speed,
        "pingpong": bool(body.get("pingpong", True)),
        "brand": bool(body.get("brand", True)),
        "show_epoch": bool(body.get("show_epoch", True)),
        "dest": dest,
        "width": width,
        "height": height,
    }
    family = str(body.get("family") or "royale")

    def stamp(folder, job):
        if fmt == "MP4":
            job["command"] = ffmpeg_command(_binary(), width, height, _fps(speed), dest)
        else:
            job["command"] = []
            job["command_kind"] = "gif"
        job["stage"] = "Royale"
        jobs.save(folder, job)

    return jobs.start_task("royale", family, values, str(Path(dest).parent), stamp)


def run_job(folder: Path, job: dict) -> None:
    """``LoRATrainerGUI._royale_export_worker``. ``run_folder`` already holds the GPU lock."""
    from fizgig.web.runner import _begin, _finish
    if not _begin(folder, job):
        return
    values = job.get("values") or {}
    images = values.get("images") if isinstance(values.get("images"), list) else []
    images = [str(item) for item in images if str(item or "").strip()]
    dest = str(values.get("dest") or "")
    if not images or not dest:
        _finish(folder, job, "failed", 1)
        return
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _fake():
        target.write_bytes(b"fake-mp4")
        _finish(folder, job, "done", 0)
        return
    from PIL import Image
    from fizgig.lora_royale import export as rexport
    pairs = []
    for path in images:
        with Image.open(path) as image:
            pairs.append((Path(path).stem, image.convert("RGB").copy()))
    fmt = str(values.get("format") or "MP4").upper()
    speed = str(values.get("speed") or "Normal")
    frames = rexport.build_frames(
        pairs,
        speed=speed,
        pingpong=bool(values.get("pingpong", True)),
        brand=bool(values.get("brand", True)),
        show_epoch=bool(values.get("show_epoch", True)),
        max_size=None if fmt == "MP4" else 768,
    )
    if fmt == "MP4":
        rexport.write_mp4(frames, str(target), speed=speed)
    else:
        rexport.write_gif(frames, str(target), speed=speed)
    _finish(folder, job, "done", 0)


class RoyaleFake:
    """One PNG per epoch or travel step. Sleeps on the fake step delay so a newer gen can cancel."""

    def __init__(self):
        from fizgig.web.engine_host import FakeEngine
        self._engine = FakeEngine("royale")

    def load(self, family: str, args: dict) -> None:
        self._engine.load(family, args)

    def request_cancel(self) -> None:
        self._engine.request_cancel()

    def clear_cancel(self) -> None:
        self._engine.clear_cancel()

    def unload(self) -> None:
        self._engine.unload()

    def render(self, gen: int, params: dict, on_frame) -> dict:
        from fizgig.web.engine_host import _step_delay, png
        steps = max(1, int(params.get("steps") or 1))
        delay = _step_delay()
        mode = str(params.get("mode") or "")
        kind = str(params.get("kind") or "")
        side = "travel" if mode == "travel" else "epoch"
        last = b""
        for step in range(1, steps + 1):
            self._engine._sleep(delay)
            last = png(20, (40 + step) % 256, 80)
            on_frame(step, steps, last, side)
        if mode == "travel" and kind == "seed":
            records = {"mode": "seed", "seeds": list(params.get("seeds") or [])}
        elif mode == "travel" and kind == "strength":
            records = {"mode": "strength", "strengths": list(params.get("strengths") or [])}
        elif mode == "travel" and kind == "prompt":
            records = {"mode": "prompt", "prompts": list(params.get("prompts") or [])}
        else:
            labels = []
            for item in params.get("epochs") or []:
                labels.append(item.get("label") if isinstance(item, dict) else item)
            records = {"mode": mode or "epochs", "labels": labels}
        return {"baseline": None, "image": last, "records": records}


class RoyaleAdapter:
    """``make_workbench_engine`` and ``ensure_pipeline``, then ``load_primary`` / ``generate_preview``."""

    def __init__(self):
        self.family = ""
        self.args: dict = {}
        self.desc = None
        self.engine = None
        self._pipe: dict = {}
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

    def load(self, family: str, args: dict) -> None:
        """``LoRATrainerGUI._royale_validate_models_family`` and ``_royale_ensure_pipeline_loaded``."""
        from fizgig.families.registry import get as get_family
        from fizgig.web.engine_host import _blocks_to_swap, _sampling
        desc = get_family(family)
        if desc is None or "royale" not in desc.workbench:
            raise RuntimeError("unknown family")
        self.desc = desc
        self.family = family
        self.args = dict(args or {})
        self.engine = desc.make_workbench_engine()
        settings = args.get("preview_settings")
        if desc.workbench_follows_samples and isinstance(settings, dict):
            self.engine.preview_settings = dict(settings)
        pipe = {
            "dit_path": args.get("dit_path") or "",
            "vae_path": args.get("vae_path") or "",
            "text_encoder_path": args.get("text_encoder_path") or "",
            "speed_lora_path": args.get("speed_lora_path") or "",
            "device": "cuda",
            "precision": args.get("precision") or "auto",
            "blocks_to_swap": _blocks_to_swap(args.get("blocks_to_swap")),
            "preview_sampling": _sampling(args.get("preview_sampling")),
            "audio_vae_path": args.get("audio_vae_path") or "",
        }
        self.engine.ensure_pipeline(**pipe)
        self._pipe = pipe

    def unload(self) -> None:
        engine = self.engine
        self.engine = None
        self.args = {}
        if engine is not None and hasattr(engine, "reset"):
            engine.reset()

    def _stopped(self) -> None:
        from fizgig.web.engine_host import Cancelled
        if self._cancel.is_set():
            raise Cancelled()

    def _use(self, path: str) -> None:
        """``LoRATrainerGUI._royale_load_or_swap_primary``."""
        engine = self.engine
        if engine is None:
            raise RuntimeError("royale engine is not loaded")
        if not path:
            raise RuntimeError("no LoRA path")
        if getattr(engine, "primary_network", None) is None:
            engine.load_primary(path)
            return
        if getattr(engine, "primary_path", None) == path:
            return
        if engine.swap_primary_weights(path):
            return
        engine.reset()
        engine.ensure_pipeline(**self._pipe)
        engine.load_primary(path)

    def _state(self, params: dict):
        from fizgig.repair_studio.state import BlockState, SliderState
        if self.desc is None:
            raise RuntimeError("royale engine is not loaded")
        try:
            groups = self.desc.load_driver().block_map()
        except Exception as exc:
            raise RuntimeError("could not build the family's block map") from exc
        blocks = {block.id: BlockState() for group in groups for block in group.blocks}
        state = SliderState(
            blocks=blocks,
            seed=_number(params.get("seed"), 42),
            prompt=str(params.get("prompt") or ""),
            preview_width=_number(params.get("width"), 512),
            preview_height=_number(params.get("height"), 512),
        )
        ref = str(params.get("reference") or "")
        if ref and os.path.isfile(ref):
            state.ref_image_path = ref
        return state

    def _preview(self, state, **kwargs) -> bytes:
        from fizgig.web.engine_host import Cancelled, _pil_png
        self._stopped()
        engine = self.engine
        if engine is None:
            raise RuntimeError("royale engine is not loaded")
        try:
            image = engine.generate_preview(state, **kwargs)
        except Cancelled:
            raise
        except Exception as exc:
            if type(exc).__name__ in _CANCELLED:
                raise Cancelled() from exc
            raise
        if image is None:
            raise RuntimeError("preview returned nothing")
        return _pil_png(image)

    def _lora(self, params: dict) -> str:
        path = str(params.get("path") or self.args.get("lora") or "")
        if not path:
            raise RuntimeError("no LoRA path")
        return path

    def render(self, gen: int, params: dict, on_frame) -> dict:
        mode = str(params.get("mode") or "")
        if mode == "epochs":
            return self._epochs(params, on_frame)
        if mode == "travel":
            return self._travel(params, on_frame)
        raise RuntimeError(f"unknown royale mode {mode}")

    def _epochs(self, params: dict, on_frame) -> dict:
        epochs = params.get("epochs") or []
        if not epochs:
            raise RuntimeError("no epochs")
        last = b""
        labels = []
        total = len(epochs)
        for index, item in enumerate(epochs):
            label = item.get("label") if isinstance(item, dict) else item
            path = str(item.get("path") or "") if isinstance(item, dict) else ""
            self._use(path)
            last = self._preview(self._state(params))
            on_frame(index + 1, total, last, "epoch")
            labels.append(label)
        return {"baseline": None, "image": last, "records": {"mode": "epochs", "labels": labels}}

    def _travel(self, params: dict, on_frame) -> dict:
        kind = str(params.get("kind") or "")
        n = max(2, int(params.get("steps") or 2))
        self._use(self._lora(params))
        if kind == "seed":
            return self._seed_travel(params, on_frame, n)
        if kind == "strength":
            return self._strength_travel(params, on_frame, n)
        if kind == "prompt":
            return self._prompt_travel(params, on_frame, n)
        raise RuntimeError(f"unknown travel kind {kind}")

    def _seed_travel(self, params: dict, on_frame, n: int) -> dict:
        """``LoRATrainerGUI._royale_travel_worker``: ``seed_b`` and ``travel_t`` per frame."""
        seeds = [int(seed) for seed in (params.get("seeds") or [])]
        if len(seeds) < 2:
            raise RuntimeError("seed travel needs two seeds")
        nseg = len(seeds) - 1
        last = b""
        for index in range(n):
            pos = (index / float(n - 1)) * nseg
            slot = min(int(pos), nseg - 1)
            state = self._state(params)
            state.seed = seeds[slot]
            last = self._preview(state, seed_b=seeds[slot + 1], travel_t=pos - slot)
            on_frame(index + 1, n, last, "travel")
        return {"baseline": None, "image": last, "records": {"mode": "seed", "seeds": seeds}}

    def _strength_travel(self, params: dict, on_frame, n: int) -> dict:
        """``LoRATrainerGUI._royale_lora_travel_worker``, applied as ``primary_scale``."""
        strengths = [float(value) for value in (params.get("strengths") or [])]
        if len(strengths) != n:
            start = _float(params.get("s_start"), 0.0)
            end = _float(params.get("s_end"), 1.0)
            strengths = [start + (end - start) * (i / (n - 1)) for i in range(n)]
        last = b""
        for index, strength in enumerate(strengths):
            state = self._state(params)
            state.primary_scale = strength
            last = self._preview(state)
            on_frame(index + 1, n, last, "travel")
        return {"baseline": None, "image": last, "records": {"mode": "strength", "strengths": strengths}}

    def _prompt_travel(self, params: dict, on_frame, n: int) -> dict:
        """``LoRATrainerGUI._royale_pt_worker``: the waypoint prompt changes each frame."""
        prompts = [str(prompt) for prompt in (params.get("prompts") or [])]
        last = b""
        for index in range(n):
            state = self._state(params)
            if prompts:
                if len(prompts) == 1:
                    state.prompt = prompts[0]
                else:
                    pos = index / float(n - 1) * (len(prompts) - 1)
                    state.prompt = prompts[min(int(round(pos)), len(prompts) - 1)]
            last = self._preview(state)
            on_frame(index + 1, n, last, "travel")
        return {"baseline": None, "image": last, "records": {"mode": "prompt", "prompts": prompts}}


def install() -> None:
    from fizgig.web.engine_host import register_engine

    def factory():
        if os.environ.get("FIZGIG_WEB_FAKE_ENGINE") == "1":
            return RoyaleFake()
        return RoyaleAdapter()

    register_engine("royale", factory)


install()
