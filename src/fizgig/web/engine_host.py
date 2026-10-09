"""One worker process, one engine.

The server and the worker speak JSON lines on the worker's stdin and stdout.
A render with a higher ``gen`` cancels the one in flight, the same rule as
``LoRATrainerGUI._repair_render_gen`` and ``_run_preview_async``. Early frames
are written as they are produced and dropped when their ``gen`` is no longer
current, the same rule as ``_repair_show_early``.

``FIZGIG_WEB_FAKE_ENGINE=1`` selects a fake engine. It does not import a model
and does not touch CUDA. A factory registered with ``register_engine`` is used
first, including under that flag, so RefMod, Explorer and Royale supply their
own fake. Repair and Profiler have no factory and still get ``FakeEngine``.

Idle unload uses ``FIZGIG_WEB_ENGINE_IDLE`` seconds (default 600).
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import threading
import time
import uuid
import zlib
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from fizgig.web.procs import creationflags, hidden_console

_HOST = None
_PLUGINS: dict[str, type] = {}
ENGINES = ("repair", "profiler", "refmod", "explorer", "royale")
_LATER = frozenset({"refmod", "explorer", "royale"})


class EngineError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Cancelled(Exception):
    """The render in flight was superseded or asked to stop."""


def register_engine(name: str, factory: type) -> None:
    """Plug in a later workbench engine. ``factory`` is called with no arguments."""
    _PLUGINS[name] = factory


def png(r: int, g: int, b: int, size: int = 2) -> bytes:
    """A tiny RGB PNG. The fake engine's frames and finals."""
    raw = b"".join(b"\x00" + bytes((r & 255, g & 255, b & 255)) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _step_delay() -> float:
    try:
        return float(os.environ.get("FIZGIG_WEB_FAKE_STEP", "0.05"))
    except ValueError:
        return 0.05


class FakeEngine:
    """The stand-in the host drives in tests. Sleeps per step so a newer gen can cancel it."""

    def __init__(self, kind: str):
        self.kind = kind
        self.family = ""
        self.args: dict = {}
        self._cancel = threading.Event()

    def load(self, family: str, args: dict) -> None:
        if args.get("crash"):
            os._exit(1)
        probe = str((args or {}).get("console_probe") or "")
        if probe:
            # Console test stand-in. It starts a grandchild with no window flags.
            import runpy
            runpy.run_path(probe, run_name="__main__")
        self.family = family
        self.args = dict(args or {})

    def request_cancel(self) -> None:
        self._cancel.set()

    def clear_cancel(self) -> None:
        self._cancel.clear()

    def unload(self) -> None:
        self.args = {}

    def _sleep(self, delay: float) -> None:
        end = time.monotonic() + delay
        while time.monotonic() < end:
            if self._cancel.is_set():
                raise Cancelled()
            time.sleep(min(0.01, max(0.0, end - time.monotonic())))

    def render(self, gen: int, params: dict, on_frame) -> dict:
        if params.get("profile"):
            return self._profile(params, on_frame)
        steps = max(1, int(params.get("steps") or 3))
        delay = _step_delay()
        for step in range(1, steps + 1):
            self._sleep(delay)
            on_frame(step, steps, png(20, 40 + step, 80), "tweaked")
        clip = png(8, 8, 8) if params.get("video") else None
        return {"baseline": png(180, 40, 40), "image": png(10, 160, 60), "clip": clip}

    def _profile(self, params: dict, on_frame) -> dict:
        mode = str(params.get("mode") or "quick")
        seeds = [1234, 5678] if mode == "thorough" else [1234]
        groups = params.get("groups") or []
        delay = _step_delay()
        for index, seed in enumerate(seeds):
            self._sleep(delay)
            on_frame(index + 1, len(seeds), png(seed % 200, 30, 30), "profile")
        blocks: dict = {}
        notes: list[str] = []
        if groups:
            first = groups[0]
            label = str(first.get("label") or "group")
            for block in first.get("blocks") or []:
                blocks[str(block.get("id"))] = {"enabled": False, "strength": 1.0}
            notes.append(f"{label} off (little effect)")
        return {
            "baseline": None,
            "image": png(1, 2, 3),
            "clip": None,
            "profile": {
                "mode": mode,
                "seeds": seeds,
                "per_block": mode == "thorough",
                "blocks": blocks,
                "notes": notes,
                "prompt": params.get("prompt") or "",
                "class_prompt": params.get("class_prompt") or "",
                "seed": seeds[0],
                "size": int(params.get("size") or 768),
                "report": params.get("output") or "",
            },
        }


def _sampling(data):
    if not data:
        return None
    sigmas = data.get("sigmas")
    options = data.get("options") or ()
    return SimpleNamespace(
        name=data.get("name") or "",
        steps=int(data.get("steps") or 1),
        cfg=float(data.get("cfg") or 1),
        sigmas=tuple(sigmas) if sigmas else None,
        options=tuple(tuple(pair) for pair in options),
    )


def _blocks_to_swap(raw) -> int:
    """``LoRATrainerGUI._get_inference_blocks_to_swap`` and ``_auto_detect_blocks_to_swap``."""
    import re
    text = str(raw or "").strip()
    if not text or text.lower().startswith("auto"):
        try:
            import torch
            if torch.cuda.is_available():
                vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                if vram_gb >= 15:
                    return 0
                if vram_gb >= 10:
                    return 12
                return 16
        except Exception:
            return 0
        return 0
    match = re.match(r"\d+", text)
    return int(match.group()) if match else 0


def _pil_png(image) -> bytes:
    import io
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _clip_file(frames, dest: Path, fps: int) -> str | None:
    """Write the desktop clip's frames and, when ffmpeg is on PATH, an mp4 the page can play."""
    import shutil
    if not frames:
        return None
    folder = dest.parent / f"{dest.stem}-frames"
    folder.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        frame.save(folder / f"f{index:04d}.png")
    if shutil.which("ffmpeg") is None:
        return None
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(int(fps) or 24), "-i", str(folder / "f%04d.png"),
         "-pix_fmt", "yuv420p", str(dest)],
        check=False, capture_output=True,
        creationflags=creationflags(),
    )
    return dest.name if dest.is_file() else None


class WorkbenchAdapter:
    """Drives ``desc.make_workbench_engine()``. Imported only for a real load."""

    def __init__(self, kind: str):
        self.kind = kind
        self.family = ""
        self.desc = None
        self.engine = None
        self.primary = ""
        self.follows = False
        self._cancel = threading.Event()

    def load(self, family: str, args: dict) -> None:
        if self.kind in _LATER:
            raise RuntimeError(f"{self.kind} plugs into this host in a later phase")
        from fizgig.families.registry import get as get_family
        desc = get_family(family)
        if desc is None:
            raise RuntimeError("unknown family")
        self.desc = desc
        self.family = family
        self.follows = bool(args.get("follows_samples"))
        self.engine = desc.make_workbench_engine()
        if self.follows and args.get("preview_settings"):
            self.engine.preview_settings = dict(args["preview_settings"])
        self.engine.ensure_pipeline(
            dit_path=args.get("dit_path") or "",
            vae_path=args.get("vae_path") or "",
            text_encoder_path=args.get("text_encoder_path") or "",
            speed_lora_path=args.get("speed_lora_path") or "",
            turbo_lora_path=args.get("turbo_lora_path") or args.get("speed_lora_path") or "",
            device="cuda",
            precision=args.get("precision") or "auto",
            blocks_to_swap=_blocks_to_swap(args.get("blocks_to_swap")),
            preview_sampling=_sampling(args.get("preview_sampling")),
            audio_vae_path=args.get("audio_vae_path") or "",
            te_cache_dir=args.get("te_cache_dir") or "",
            base_mode=args.get("base_mode") or "auto",
        )
        self.engine.load_primary(args["primary"])
        self.primary = args["primary"]
        if args.get("donor"):
            self.engine.load_donor(args["donor"])

    def request_cancel(self) -> None:
        self._cancel.set()
        if self.engine is not None and hasattr(self.engine, "request_cancel"):
            self.engine.request_cancel()

    def clear_cancel(self) -> None:
        self._cancel.clear()
        if self.engine is not None and hasattr(self.engine, "clear_cancel"):
            self.engine.clear_cancel()

    def unload(self) -> None:
        engine = self.engine
        self.engine = None
        if engine is not None and hasattr(engine, "reset"):
            engine.reset()

    def render(self, gen: int, params: dict, on_frame) -> dict:
        try:
            if self.kind == "profiler" or params.get("profile"):
                return self._profile(params, on_frame)
            return self._repair(params, on_frame)
        except Cancelled:
            raise
        except Exception as exc:
            if type(exc).__name__ in {"RenderCancelled", "PreviewAborted", "SampleAborted"}:
                raise Cancelled() from exc
            raise

    def _state(self, params: dict):
        from fizgig.repair_studio.state import SliderState
        return SliderState.from_json(params.get("state") or {})

    def _repair(self, params: dict, on_frame) -> dict:
        engine = self.engine
        if self.follows and params.get("preview_settings"):
            engine.preview_settings = dict(params["preview_settings"])
        state = self._state(params)
        self.clear_cancel()
        video = bool(params.get("video")) and hasattr(engine, "render_clip")
        if video:
            early = int(params.get("early_step") or 0)

            def on_early(image, step, total, _early=early):
                if _early:
                    on_frame(int(step), int(total), _pil_png(image), "tweaked")

            base = engine.baseline_clip(state, frames=params.get("frames") or None, with_audio=False)
            tweak = engine.render_clip(
                state, frames=params.get("frames") or None, with_audio=False,
                early_step=early, on_early=on_early if early else None,
            )
            dest = Path(os.environ["FIZGIG_WEB_ENGINE_DIR"]) / f"g{params.get('gen') or 0}-clip.mp4"
            clip_name = _clip_file(tweak.get("frames") or [], dest, int(params.get("fps") or 24))
            return {
                "baseline": _pil_png(base["middle"]),
                "image": _pil_png(tweak["middle"]),
                "clip": clip_name,
            }
        engine.on_step = lambda done, total: on_frame(int(done), int(total), None, "tweaked")
        baseline = engine.generate_baseline(state)
        if self._cancel.is_set():
            raise Cancelled()
        tweaked = engine.generate_preview(state)
        return {"baseline": _pil_png(baseline), "image": _pil_png(tweaked), "clip": None}

    def _profile(self, params: dict, on_frame) -> dict:
        from fizgig.families.block_profile import repair_settings, run_ablation, weight_stats, write_report
        mode = str(params.get("mode") or "quick")
        seeds = (1234, 5678) if mode == "thorough" else (1234,)
        size = int(params.get("size") or 768)
        per_block = mode == "thorough"

        def prog(done, total, _kind, _cond):
            on_frame(int(done), int(total), None, "profile")

        abl = run_ablation(
            self.engine, prompt=str(params.get("prompt") or ""),
            class_prompt=str(params.get("class_prompt") or ""),
            seeds=seeds, width=size, height=size, per_block=per_block, on_progress=prog,
        )
        stats = weight_stats(self.desc, self.primary)
        labels = {block.id: block.label for group in self.engine.block_groups() for block in group.blocks}
        write_report(self.desc, self.primary, stats, abl, params.get("output") or "", labels)
        blocks, notes = repair_settings(abl)
        return {
            "baseline": None,
            "image": None,
            "clip": None,
            "profile": {
                "mode": mode,
                "seeds": list(seeds),
                "per_block": per_block,
                "blocks": {bid: {"enabled": bool(on), "strength": float(strength)} for bid, (on, strength) in blocks.items()},
                "notes": list(notes),
                "prompt": params.get("prompt") or "",
                "class_prompt": params.get("class_prompt") or "",
                "seed": seeds[0],
                "size": size,
                "report": params.get("output") or "",
            },
        }


def make_engine(kind: str):
    if kind not in ENGINES:
        raise RuntimeError(f"unknown engine {kind}")
    factory = _PLUGINS.get(kind)
    if factory is not None:
        return factory()
    if os.environ.get("FIZGIG_WEB_FAKE_ENGINE") == "1":
        return FakeEngine(kind)
    if kind in _LATER:
        raise RuntimeError(f"{kind} plugs into this host in a later phase")
    return WorkbenchAdapter(kind)


class Worker:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.engine = None
        self.kind = ""
        self.family = ""
        self.gen = 0
        self.busy = False
        self.pending = None
        self.gpu = None
        self.wake = threading.Condition()
        self.write_lock = threading.Lock()
        self.stop = False
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def emit(self, obj: dict) -> None:
        line = json.dumps(obj) + "\n"
        with self.write_lock:
            sys.stdout.write(line)
            sys.stdout.flush()

    def handle(self, msg: dict) -> None:
        op = msg.get("op")
        if op == "load":
            self._load(msg)
        elif op == "render":
            self._accept_render(msg)
        elif op == "cancel":
            self._cancel(msg)
        elif op == "unload":
            self._unload(msg)
        elif op == "status":
            self._status(msg)
        else:
            self.emit({"id": msg.get("id"), "op": op, "ok": False, "error": "unknown op"})

    def _acquire(self) -> bool:
        from fizgig.gpu_lock import GpuLock
        lock = GpuLock()
        if not lock.acquire():
            return False
        self.gpu = lock
        return True

    def _release(self) -> None:
        lock = self.gpu
        self.gpu = None
        if lock is not None:
            lock.release()

    def _wait_idle(self, timeout: float = 10) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.wake:
                if not self.busy and self.pending is None:
                    return
            time.sleep(0.01)

    def _load(self, msg: dict) -> None:
        with self.wake:
            self.gen += 1
            if self.engine is not None:
                self.engine.request_cancel()
            self.pending = None
        self._wait_idle()
        if self.engine is not None:
            try:
                self.engine.unload()
            except Exception:
                pass
            self.engine = None
        self._release()
        kind = str(msg.get("engine") or "")
        family = str(msg.get("family") or "")
        self.emit({"event": "loading", "engine": kind, "family": family})
        try:
            engine = make_engine(kind)
            if not self._acquire():
                self.emit({"id": msg.get("id"), "op": "load", "ok": False, "error": "the GPU is in use"})
                return
            engine.load(family, msg.get("args") or {})
        except Exception as exc:
            self._release()
            self.emit({"id": msg.get("id"), "op": "load", "ok": False, "error": str(exc)})
            self.emit({"event": "error", "message": str(exc)})
            return
        self.engine = engine
        self.kind = kind
        self.family = family
        self.emit({"id": msg.get("id"), "op": "load", "ok": True, "engine": kind, "family": family})

    def _accept_render(self, msg: dict) -> None:
        gen = int(msg.get("gen") or 0)
        with self.wake:
            if self.engine is None:
                self.emit({"id": msg.get("id"), "op": "render", "ok": False, "error": "no engine loaded"})
                return
            if gen < self.gen or (gen == self.gen and (self.busy or self.pending is not None)):
                self.emit({"id": msg.get("id"), "op": "render", "ok": True, "stale": True, "gen": gen})
                return
            self.gen = gen
            self.engine.request_cancel()
            self.pending = msg
            self.wake.notify()
        self.emit({"id": msg.get("id"), "op": "render", "ok": True, "gen": gen})

    def _cancel(self, msg: dict) -> None:
        gen = int(msg.get("gen") or 0)
        with self.wake:
            if self.engine is not None and (gen == 0 or gen == self.gen):
                self.engine.request_cancel()
        self.emit({"id": msg.get("id"), "op": "cancel", "ok": True, "gen": gen})

    def _unload(self, msg: dict) -> None:
        with self.wake:
            self.gen += 1
            if self.engine is not None:
                self.engine.request_cancel()
            self.pending = None
        self._wait_idle()
        if self.engine is not None:
            try:
                self.engine.unload()
            except Exception:
                pass
            self.engine = None
        self._release()
        self.kind = ""
        self.family = ""
        self.emit({"id": msg.get("id"), "op": "unload", "ok": True})
        self.emit({"event": "unloaded"})

    def _status(self, msg: dict) -> None:
        with self.wake:
            body = {
                "id": msg.get("id"),
                "op": "status",
                "ok": True,
                "loaded": self.engine is not None,
                "engine": self.kind,
                "family": self.family,
                "busy": self.busy or self.pending is not None,
                "gen": self.gen,
            }
        self.emit(body)

    def _loop(self) -> None:
        while not self.stop:
            with self.wake:
                while self.pending is None and not self.stop:
                    self.wake.wait()
                msg = self.pending
                self.pending = None
                if msg is None:
                    continue
                gen = int(msg.get("gen") or 0)
                if gen != self.gen:
                    continue
                self.busy = True
                engine = self.engine
            if engine is None:
                with self.wake:
                    self.busy = False
                continue
            try:
                engine.clear_cancel()
                with self.wake:
                    if gen != self.gen:
                        engine.request_cancel()
                        self.busy = False
                        continue

                def on_frame(step, total, data, side, _gen=gen):
                    with self.wake:
                        current = self.gen
                    if _gen != current:
                        return
                    name = None
                    if data:
                        name = f"g{_gen}-s{int(step)}.png"
                        (self.out_dir / name).write_bytes(data)
                    self.emit({
                        "event": "frame", "gen": _gen, "step": int(step), "total": int(total),
                        "file": name, "side": side,
                    })

                result = engine.render(gen, msg.get("params") or {}, on_frame)
                with self.wake:
                    if gen != self.gen:
                        self.emit({"event": "cancelled", "gen": gen})
                        self.busy = False
                        continue
                done = {"event": "done", "gen": gen}
                for key in ("baseline", "image", "clip"):
                    blob = result.get(key)
                    if isinstance(blob, (bytes, bytearray)) and blob:
                        ext = ".mp4" if key == "clip" else ".png"
                        name = f"g{gen}-{key}{ext}"
                        (self.out_dir / name).write_bytes(blob)
                        done[key] = name
                    elif isinstance(blob, str) and blob:
                        done[key] = blob
                if result.get("profile"):
                    done["profile"] = result["profile"]
                if result.get("records") is not None:
                    done["records"] = result["records"]
                self.emit(done)
            except Cancelled:
                self.emit({"event": "cancelled", "gen": gen})
            except Exception as exc:
                self.emit({"event": "error", "gen": gen, "message": str(exc)})
            finally:
                with self.wake:
                    if gen == self.gen:
                        self.busy = False

    def shutdown(self) -> None:
        self.stop = True
        with self.wake:
            self.gen += 1
            if self.engine is not None:
                self.engine.request_cancel()
            self.pending = None
            self.wake.notify()
        self._wait_idle(2)
        if self.engine is not None:
            try:
                self.engine.unload()
            except Exception:
                pass
            self.engine = None
        self._release()


def worker_main() -> None:
    folder = Path(os.environ.get("FIZGIG_WEB_ENGINE_DIR") or ".")
    folder.mkdir(parents=True, exist_ok=True)
    worker = Worker(folder)
    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                worker.emit({"event": "error", "message": "bad message"})
                continue
            worker.handle(msg)
    finally:
        worker.shutdown()


class EngineHost:
    def __init__(self):
        try:
            self.idle = float(os.environ.get("FIZGIG_WEB_ENGINE_IDLE", "600") or 600)
        except ValueError:
            self.idle = 600.0
        self.proc = None
        self.session: Path | None = None
        self.loaded = False
        self.busy = False
        self.engine_name = ""
        self.family = ""
        self.args: dict = {}
        self.latest = 0
        self.restarted = False
        self.events: list[dict] = []
        self.result: dict | None = None
        self.profile: dict | None = None
        self.last = time.monotonic()
        self._next_id = 1
        self._replies: dict[int, dict] = {}
        self._waiters: dict[int, threading.Event] = {}
        self._state = threading.Lock()
        self._io = threading.Lock()
        self._stop = threading.Event()
        self._announced = False
        self._watch_started = False
        self._stderr = None

    def _jobs_root(self) -> Path:
        from fizgig.web.jobs import jobs_root
        return jobs_root()

    def _touch(self) -> None:
        self.last = time.monotonic()

    def _reap(self, proc) -> None:
        """Close the pipes so Windows reports the exit, then wait."""
        if proc is None:
            return
        for stream in (proc.stdin, proc.stdout):
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _mark_dead(self) -> None:
        with self._state:
            first = not self._announced
            self._announced = True
            if first:
                self.loaded = False
                self.busy = False
                self.engine_name = ""
                self.restarted = True
                self.events.append({
                    "event": "error",
                    "message": "The engine worker stopped. It will start again on the next request.",
                    "restarted": True,
                })
                waiters = list(self._waiters.values())
            else:
                waiters = []
        self._reap(self.proc)
        for waiter in waiters:
            waiter.set()

    def _spawn(self) -> None:
        if self._stderr is not None:
            try:
                self._stderr.close()
            except Exception:
                pass
            self._stderr = None
        self.session = self._jobs_root() / "engine" / uuid.uuid4().hex[:12]
        self.session.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["FIZGIG_WEB_ENGINE_DIR"] = str(self.session)
        env["PYTHONUNBUFFERED"] = "1"
        src = str(Path(__file__).resolve().parents[2])
        previous = env.get("PYTHONPATH") or ""
        env["PYTHONPATH"] = src + (os.pathsep + previous if previous else "")
        self._stderr = open(self.session / "worker.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "fizgig.web.engine_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            env=env,
            text=True,
            bufsize=1,
            **hidden_console(),
        )
        self._announced = False
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        if not self._watch_started:
            self._watch_started = True
            threading.Thread(target=self._watch, daemon=True).start()

    def _ensure(self) -> None:
        proc = self.proc
        if proc is not None and proc.poll() is None:
            return
        if proc is not None:
            self._mark_dead()
        self._spawn()

    def _read(self, proc) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                text = line.strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if self.proc is proc:
                    self._accept(msg)
        finally:
            if self.proc is proc:
                self._mark_dead()
            else:
                self._reap(proc)

    def _public(self, msg: dict) -> dict:
        out = dict(msg)
        session = self.session
        if session is None:
            return out
        for key in ("file", "baseline", "image", "clip"):
            name = out.get(key)
            if not isinstance(name, str) or not name or os.path.isabs(name):
                continue
            path = session / name
            out[key] = str(path)
            out[key + "_url"] = "/api/engine/file?path=" + quote(str(path))
        return out

    def _accept(self, msg: dict) -> None:
        event = msg.get("event")
        gen = msg.get("gen")
        waiter = None
        with self._state:
            if event in {"frame", "done"} and gen is not None and gen != self.latest:
                if "id" in msg and "op" in msg:
                    self._replies[msg["id"]] = msg
                    waiter = self._waiters.get(msg["id"])
            else:
                if event:
                    shown = self._public(msg)
                    self.events.append(shown)
                    if event == "done" and gen == self.latest:
                        self.busy = False
                        self.result = shown
                        if shown.get("profile"):
                            self.profile = shown["profile"]
                    elif event in {"cancelled", "error"} and (gen is None or gen == self.latest):
                        self.busy = False
                    elif event == "unloaded":
                        self.loaded = False
                        self.busy = False
                        self.engine_name = ""
                if "id" in msg and "op" in msg:
                    self._replies[msg["id"]] = msg
                    waiter = self._waiters.get(msg["id"])
        if waiter is not None:
            waiter.set()

    def _send(self, payload: dict) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            self._mark_dead()
            raise EngineError("The engine worker stopped. It will start again on the next request.")
        try:
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._mark_dead()
            raise EngineError("The engine worker stopped. It will start again on the next request.") from exc

    def request(self, payload: dict, timeout: float = 30) -> dict:
        with self._io:
            self._ensure()
            with self._state:
                ident = self._next_id
                self._next_id += 1
                waiter = threading.Event()
                self._waiters[ident] = waiter
            self._send({**payload, "id": ident})
        if not waiter.wait(timeout):
            raise EngineError("the engine did not answer")
        with self._state:
            self._waiters.pop(ident, None)
            reply = self._replies.pop(ident, None)
        if reply is None:
            raise EngineError("The engine worker stopped. It will start again on the next request.")
        return reply

    def _watch(self) -> None:
        while not self._stop.wait(0.05):
            if not self.loaded or self.busy:
                continue
            if time.monotonic() - self.last < self.idle:
                continue
            try:
                self.unload()
            except Exception:
                pass

    def load(self, engine: str, family: str, args: dict) -> dict:
        self._touch()
        reply = self.request({"op": "load", "engine": engine, "family": family, "args": args}, timeout=3600)
        if not reply.get("ok"):
            self.loaded = False
            self.engine_name = ""
            raise EngineError(str(reply.get("error") or "load failed"))
        self.loaded = True
        self.engine_name = engine
        self.family = family
        self.args = dict(args or {})
        self.restarted = False
        self.busy = False
        return reply

    def render(self, params: dict, gen: int | None = None) -> int:
        self._touch()
        if gen is None or int(gen) > self.latest:
            gen = int(gen or 0) or self.latest + 1
            if gen <= self.latest:
                gen = self.latest + 1
            self.latest = int(gen)
            self.busy = True
        else:
            gen = int(gen)
        reply = self.request({"op": "render", "gen": gen, "params": params}, timeout=30)
        if not reply.get("ok"):
            if gen == self.latest:
                self.busy = False
            raise EngineError(str(reply.get("error") or "render failed"))
        return int(gen)

    def cancel(self, gen: int = 0) -> dict:
        self._touch()
        return self.request({"op": "cancel", "gen": int(gen)}, timeout=10)

    def unload(self) -> dict:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            self.loaded = False
            self.busy = False
            self.engine_name = ""
            return {"ok": True}
        if not self.loaded and not self.busy:
            return {"ok": True}
        reply = self.request({"op": "unload"}, timeout=30)
        self.loaded = False
        self.busy = False
        self.engine_name = ""
        return reply

    def status(self) -> dict:
        if self.proc is None or self.proc.poll() is not None:
            if self.proc is not None:
                self._ensure()
            else:
                return {
                    "loaded": False, "engine": "", "family": "", "busy": False,
                    "gen": self.latest, "restarted": self.restarted, "profile": self.profile,
                }
        reply = self.request({"op": "status"}, timeout=10)
        reply["restarted"] = self.restarted
        reply["profile"] = self.profile
        reply["result"] = self.result
        return reply

    def drain(self) -> list[dict]:
        with self._state:
            found = list(self.events)
            self.events.clear()
            return found

    def close(self) -> None:
        self._stop.set()
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                if self.loaded or self.busy:
                    self.unload()
            except Exception:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
        if self._stderr is not None:
            try:
                self._stderr.close()
            except Exception:
                pass
            self._stderr = None
        self._reap(proc)
        self.loaded = False
        self.busy = False
        self.proc = None


def get_host() -> EngineHost:
    global _HOST
    if _HOST is None:
        _HOST = EngineHost()
    return _HOST


def engine_loaded() -> bool:
    return _HOST is not None and bool(_HOST.loaded)


def drain() -> list[dict]:
    if _HOST is None:
        return []
    return _HOST.drain()


def shutdown() -> None:
    global _HOST
    host = _HOST
    _HOST = None
    if host is not None:
        host.close()
