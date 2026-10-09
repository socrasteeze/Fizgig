"""Job folders, the caller's duties, and the controls the trainer already understands.

Mirrors the desktop pieces named on each function. ``lora_trainer_gui.py`` is not imported.
Hashes live in ``mirrors.py``.

One run at a time. A stale ``.pause_requested`` and ``.sample_override.json`` are removed
before a launch. Low disk and a resume already at max epochs are warnings: the client
sends them back in ``confirm`` to start anyway, which is the desktop's Yes on those dialogs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fizgig.families.launch import plan, problems
from fizgig.families.registry import get as get_family
from fizgig.gpu_lock import held
from fizgig.training.progress import TrainingProgressTracker
from fizgig.web.inputs import build
from fizgig.web.procs import creationflags, hidden_console

_REPO = Path(__file__).resolve().parents[3]
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# LoRATrainerGUI.DISK_WARN_GB
DISK_WARN_GB = 15
_ACTIVE = frozenset({"queued", "running"})


class JobError(Exception):
    def __init__(self, status: int, body: dict):
        super().__init__(str(body))
        self.status = status
        self.body = body


def jobs_root() -> Path:
    override = os.environ.get("FIZGIG_WEB_JOBS", "").strip()
    root = Path(override) if override else _REPO / "cache" / "web_jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_id(job_id: str) -> bool:
    return bool(job_id) and "/" not in job_id and "\\" not in job_id and job_id not in {".", ".."}


def _folder(job_id: str) -> Path:
    if not _safe_id(job_id):
        raise JobError(404, {"detail": "no such job"})
    folder = (jobs_root() / job_id).resolve()
    if not _inside(folder, jobs_root().resolve()):
        raise JobError(404, {"detail": "no such job"})
    return folder


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _load(folder: Path) -> dict | None:
    path = folder / "job.json"
    for _ in range(25):
        try:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.02)
        except OSError:
            return None
    return None


def _write(folder: Path, job: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "job.json.tmp"
    payload = json.dumps(job, indent=2)
    dest = folder / "job.json"
    # Windows denies the replace while a reader still has job.json open.
    for _ in range(25):
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, dest)
            return
        except PermissionError:
            time.sleep(0.02)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, dest)


def save(folder: Path, job: dict) -> bool:
    """Write ``job.json``. A stop file wins over queued or running. False means exit."""
    if (folder / "STOP").is_file() and job.get("status") in _ACTIVE:
        job["status"] = "stopped"
        job["ended"] = job.get("ended") or _now()
        _write(folder, job)
        return False
    _write(folder, job)
    return True


def _each():
    root = jobs_root()
    jobs = []
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        job = _load(folder)
        if job and job.get("id"):
            jobs.append(job)
    jobs.sort(key=lambda item: item.get("created") or "", reverse=True)
    return jobs


def _get(job_id: str) -> tuple[Path, dict]:
    folder = _folder(job_id)
    job = _load(folder)
    if job is None:
        raise JobError(404, {"detail": "no such job"})
    return folder, job


def _loss(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _progress(job: dict) -> dict:
    """Fill step, total, and loss from ``log.txt``. Mirrors the desktop tracker feed."""
    shown = dict(job)
    folder = jobs_root() / str(job.get("id") or "")
    log = folder / "log.txt"
    if not log.is_file():
        shown["loss"] = _loss(shown.get("loss"))
        return shown
    tracker = TrainingProgressTracker(shown.get("values", {}).get("MAX_TRAIN_EPOCHS") or 1)
    step = int(shown.get("step") or 0)
    total = int(shown.get("total") or 0)
    loss = _loss(shown.get("loss"))
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        update = tracker.consume(line)
        if update and update.get("kind") == "training":
            step = int(update["step"])
            total = int(update["total_steps"])
            parsed = _loss(update.get("average_loss_text"))
            if parsed is not None:
                loss = parsed
    shown["step"] = step
    shown["total"] = total
    shown["loss"] = loss
    return shown


def public(job: dict) -> dict:
    shown = _progress(job)
    pid = int(shown.get("pid") or 0)
    return {
        "id": shown.get("id") or "",
        "family": shown.get("family") or "",
        "status": shown.get("status") or "",
        "pid": pid or None,
        "stage": shown.get("stage") or "",
        "step": int(shown.get("step") or 0),
        "total": int(shown.get("total") or 0),
        "loss": None if isinstance(shown.get("loss"), bool) or not isinstance(shown.get("loss"), (int, float)) else shown.get("loss"),
        "created": shown.get("created") or "",
        "started": shown.get("started") or "",
        "ended": shown.get("ended") or "",
        "output_dir": shown.get("output_dir") or "",
        "kind": shown.get("kind") or "train",
    }


def list_jobs() -> list[dict]:
    return [public(job) for job in _each()]


def get_job(job_id: str) -> dict:
    _folder, job = _get(job_id)
    return public(job)


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _process_create_time(pid: int) -> float | None:
    """``psutil.Process(pid).create_time()``, or None when that process is gone."""
    try:
        import psutil
        return float(psutil.Process(int(pid)).create_time())
    except Exception:
        return None


def pid_alive(pid: int, create_time: float | None = None) -> bool:
    """True when ``pid`` is running.

    Pass the creation time stored beside the pid. Both have to match. A recycled
    pid is a different process and does not count. Omit ``create_time`` only to
    ask whether a pid exists (the stand-in trainer's ``child.pid``).
    """
    if not _pid_exists(pid):
        return False
    if create_time is None:
        return True
    actual = _process_create_time(pid)
    if actual is None:
        return False
    try:
        return abs(actual - float(create_time)) <= 0.001
    except (TypeError, ValueError):
        return False


def bind_runner(job: dict) -> None:
    """Record this process on the job: pid and creation time, side by side."""
    pid = os.getpid()
    job["pid"] = pid
    job["pid_create_time"] = _process_create_time(pid)


def _runner_alive(job: dict) -> bool:
    """True only when the stored pid is still that same process."""
    pid = int(job.get("pid") or 0)
    created = job.get("pid_create_time")
    if not pid or created is None:
        return False
    return pid_alive(pid, created)


def _fail_reused_pid(folder: Path, job: dict) -> None:
    job["status"] = "failed"
    job["ended"] = job.get("ended") or _now()
    _write(folder, job)


def reconcile() -> None:
    """Re-read every job. A live runner stays. A dead pid becomes failed, done, or paused.

    A pid that belongs to a different process (creation time does not match) is failed.
    It is not this run, and it is not killed.
    """
    for job in _each():
        if job.get("status") not in _ACTIVE:
            continue
        folder = jobs_root() / job["id"]
        if (folder / "STOP").is_file():
            job["status"] = "stopped"
            job["ended"] = job.get("ended") or _now()
            _write(folder, job)
            continue
        pid = int(job.get("pid") or 0)
        if not pid or _runner_alive(job):
            continue
        if _pid_exists(pid):
            _fail_reused_pid(folder, job)
            continue
        output = Path(job.get("output_dir") or "")
        if job.get("exit_code") == 0:
            job["status"] = "done"
        elif (output / ".fizgig_paused.json").is_file():
            job["status"] = "paused"
        else:
            job["status"] = "failed"
        job["ended"] = job.get("ended") or _now()
        _write(folder, job)


def _busy() -> bool:
    return any(job.get("status") in _ACTIVE for job in _each())


def disk_warning(out_dir: str) -> str | None:
    """The desktop's low-disk warning, or None when the run may start.

    Mirrors ``LoRATrainerGUI._confirm_disk_headroom`` (that dialog returns False to cancel).
    """
    out_dir = (out_dir or "").strip()
    if not out_dir:
        return None
    probe = out_dir
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent
    try:
        free_gb = shutil.disk_usage(probe).free / 1024 ** 3
    except OSError:
        return None
    if free_gb >= DISK_WARN_GB:
        return None
    return (
        f"Only {free_gb:.1f} GB free where your LoRAs are saved:\n{probe}\n\n"
        "A run writes a checkpoint every few epochs, plus resumable state dirs (a few hundred "
        "MB each) and sample images. Running out part-way through loses the run.\n\n"
        "Free some space, or lower Save Every N Epochs and Keep Last.\n\n"
        "Start training anyway?"
    )


def resume_warning(resume_path: str, max_epochs) -> str | None:
    """The desktop's resume-at-max-epochs warning, or None.

    Mirrors ``LoRATrainerGUI._confirm_resume_has_epochs_left``.
    """
    resume_path = (resume_path or "").strip()
    if not resume_path:
        return None
    matched = re.search(r"-(\d{6})-state$", os.path.basename(resume_path.rstrip("/\\")))
    if not matched:
        return None
    state_epoch = int(matched.group(1))
    try:
        max_epochs = int(max_epochs)
    except (TypeError, ValueError):
        return None
    if state_epoch < max_epochs:
        return None
    return (
        f"That state is already at epoch {state_epoch}, and Max Train Epochs is {max_epochs}.\n\n"
        "Resuming it will not train anything — it will just write the final LoRA from the "
        "restored state. That is what you want if you paused on the last epoch and are "
        "finishing the run.\n\n"
        f"To train further, cancel and raise Max Train Epochs above {state_epoch} first.\n\n"
        "Continue anyway?"
    )


def _warnings(inputs: dict, confirm: list[str]) -> list[dict]:
    pending = []
    disk = disk_warning(str(inputs.get("LORA_OUTPUT_DIR") or ""))
    if disk and "low_disk" not in confirm:
        pending.append({"code": "low_disk", "message": disk})
    resume = resume_warning(str(inputs.get("RESUME_TRAINING") or ""), inputs.get("MAX_TRAIN_EPOCHS"))
    if resume and "resume_epochs" not in confirm:
        pending.append({"code": "resume_epochs", "message": resume})
    return pending


def _clear_stale(output: Path) -> None:
    """Remove a leftover pause flag and sample override. Mirrors the start of ``start_training``."""
    for name in (".pause_requested", ".sample_override.json"):
        path = output / name
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def _executed(planned, fake: str) -> list[dict]:
    if not fake:
        return [{"name": stage.name, "cmd": [str(part) for part in stage.cmd]} for stage in planned.stages]
    if not os.path.isfile(fake):
        raise JobError(422, {"problems": ["the stand-in trainer is missing"]})
    cmd = [sys.executable, fake]
    for stage in planned.stages:
        parts = [str(part) for part in stage.cmd]
        if "--resume" in parts:
            cmd += ["--resume", parts[parts.index("--resume") + 1]]
            break
    return [{"name": "Training", "cmd": cmd}]


def _write_plan_files(planned, output: Path) -> None:
    pending = []
    for path, text in planned.files:
        dest = Path(path)
        if not _inside(dest, output):
            raise JobError(422, {"problems": ["refusing to write a file outside the output directory"]})
        pending.append((dest, text))
    for folder in planned.dirs:
        dest = Path(folder)
        if not _inside(dest, output):
            raise JobError(422, {"problems": ["refusing to create a folder outside the output directory"]})
        pending.append((dest, None))
    for dest, text in pending:
        if text is None:
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def _engine_blocks() -> None:
    """A loaded workbench engine holds the GPU lock. The user unloads it first."""
    from fizgig.web.engine_host import engine_loaded
    if engine_loaded():
        raise JobError(409, {"detail": "An engine is loaded. Unload it before starting a job."})


def start(family: str, values: dict, context: dict, confirm: list[str], existing: dict | None = None) -> dict:
    _engine_blocks()
    desc = get_family(family)
    if desc is None:
        raise JobError(404, {"detail": "unknown family"})
    if _busy():
        raise JobError(409, {"detail": "a run is already active"})
    if held():
        raise JobError(409, {"detail": "the GPU is in use"})

    values = dict(values or {})
    context = dict(context or {})
    if not str(values.get("image_folder") or "").strip() and context.get("image_folder"):
        values["image_folder"] = context["image_folder"]
    output_text = str(values.get("LORA_OUTPUT_DIR") or context.get("LORA_OUTPUT_DIR") or "").strip()
    if output_text:
        values["LORA_OUTPUT_DIR"] = output_text
        if not str(context.get("DATASET_CONFIG") or values.get("DATASET_CONFIG") or "").strip():
            context["DATASET_CONFIG"] = str(Path(output_text) / "dataset.toml")
    inputs = build(desc, values, context)
    found = problems(desc, inputs)
    if found:
        raise JobError(422, {"problems": found})
    pending = _warnings(inputs, list(confirm or []))
    if pending:
        raise JobError(409, {"warnings": pending})
    planned = plan(desc, inputs)
    if planned.problems:
        raise JobError(422, {"problems": list(planned.problems)})

    output = Path(str(inputs.get("LORA_OUTPUT_DIR") or ""))
    output.mkdir(parents=True, exist_ok=True)
    _clear_stale(output)
    _write_plan_files(planned, output.resolve())

    job_id = existing["id"] if existing else uuid.uuid4().hex[:12]
    folder = jobs_root() / job_id
    stop_file = folder / "STOP"
    if stop_file.is_file():
        stop_file.unlink()
    _engine_blocks()
    if _busy():
        raise JobError(409, {"detail": "a run is already active"})
    if held():
        raise JobError(409, {"detail": "the GPU is in use"})
    fake = os.environ.get("FIZGIG_WEB_FAKE_TRAINER", "").strip()
    job = {
        "id": job_id,
        "kind": "train",
        "family": family,
        "values": values,
        "context": context,
        "plan": {
            "summary": [stage.name for stage in planned.stages],
            "stages": _executed(planned, fake),
        },
        "status": "queued",
        "pid": 0,
        "pid_create_time": None,
        "stage": "",
        "step": int(existing.get("step") or 0) if existing else 0,
        "total": int(existing.get("total") or 0) if existing else 0,
        "loss": existing.get("loss") if existing else None,
        "created": existing.get("created") if existing else _now(),
        "started": "",
        "ended": "",
        "output_dir": str(output),
        "dataset_config": str(inputs.get("DATASET_CONFIG") or ""),
        "exit_code": None,
    }
    _write(folder, job)
    from fizgig.web.queue import arm
    arm(job_id)
    _spawn(job_id)
    return public(job)


def _train_only(job: dict) -> None:
    if (job.get("kind") or "train") != "train":
        raise JobError(409, {"detail": "not a training run"})


def start_task(kind: str, family: str, values: dict, output_dir: str, before_spawn) -> dict:
    """A caption, prep, profile or extract job. Same folder, lock, and runner as a training job."""
    _engine_blocks()
    if _busy():
        raise JobError(409, {"detail": "a run is already active"})
    if held():
        raise JobError(409, {"detail": "the GPU is in use"})
    job_id = uuid.uuid4().hex[:12]
    folder = jobs_root() / job_id
    job = {
        "id": job_id,
        "kind": kind,
        "family": family,
        "values": values,
        "context": {},
        "plan": {"summary": [kind], "stages": []},
        "status": "queued",
        "pid": 0,
        "pid_create_time": None,
        "stage": "",
        "step": 0,
        "total": 0,
        "loss": None,
        "created": _now(),
        "started": "",
        "ended": "",
        "output_dir": output_dir,
        "exit_code": None,
    }
    _engine_blocks()
    if _busy():
        raise JobError(409, {"detail": "a run is already active"})
    if held():
        raise JobError(409, {"detail": "the GPU is in use"})
    _write(folder, job)
    try:
        if before_spawn is not None:
            before_spawn(folder, job)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    _spawn(job_id)
    return public(job)


def _duration(started: str, ended: str):
    if not started or not ended:
        return None
    try:
        begin = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")
        stop = datetime.strptime(ended, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return max(0, int((stop - begin).total_seconds()))


def history() -> list[dict]:
    rows = []
    for job in _each():
        if job.get("status") in _ACTIVE:
            continue
        shown = public(job)
        shown["duration"] = _duration(shown.get("started") or "", shown.get("ended") or "")
        rows.append(shown)
    return rows


def delete_record(job_id: str) -> None:
    """Remove the job folder only. Training outputs and datasets stay where they are."""
    folder, job = _get(job_id)
    if job.get("status") in _ACTIVE:
        raise JobError(409, {"detail": "the job is still active"})
    shutil.rmtree(folder)


def _spawn(job_id: str) -> None:
    env = os.environ.copy()
    src = str(_REPO / "src")
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src + (os.pathsep + previous if previous else "")
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [sys.executable, "-m", "fizgig.web.runner", str(jobs_root() / job_id)]
    kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=str(_REPO),
        close_fds=True,
    )
    # Own hidden console and process group, so a restart or Ctrl+C leaves the run alive.
    process = subprocess.Popen(cmd, **hidden_console(detached=True), **kwargs)
    # The runner is detached on purpose. Dropping this handle is not the run exiting.
    process.returncode = 0


def pause(job_id: str) -> dict:
    """Write ``.pause_requested``. Mirrors the file write in ``_pause_training``."""
    folder, job = _get(job_id)
    _train_only(job)
    if job.get("status") != "running":
        raise JobError(409, {"detail": "No active training to pause."})
    output = Path(job.get("output_dir") or ".")
    output.mkdir(parents=True, exist_ok=True)
    flag = output / ".pause_requested"
    flag.parent.mkdir(parents=True, exist_ok=True)
    open(flag, "w").close()
    return public(_load(folder) or job)


def _ft_epochs(path: str) -> tuple[int, int]:
    """``(next_window, epochs_done)``. Mirrors ``ft_checkpoint_continuation``."""
    next_window, epochs_done = 0, 0
    try:
        from safetensors import safe_open
        with safe_open(path, framework="pt") as handle:
            meta = handle.metadata() or {}
        next_window = int(meta.get("fizgig_next_start_window", 0) or 0)
        epochs_done = int(meta.get("fizgig_ft_epochs_done", 0) or 0)
    except Exception:
        pass
    matched = re.search(r"-(\d{6})\.safetensors$", os.path.basename(path or ""))
    if matched:
        epochs_done = int(matched.group(1))
    return next_window, epochs_done


def resume(job_id: str, confirm: list[str] | None = None) -> dict:
    """Start the paused job again. Mirrors ``_resume_training`` and ``.fizgig_paused.json``."""
    _folder, job = _get(job_id)
    _train_only(job)
    if job.get("status") != "paused":
        raise JobError(409, {"detail": "No paused training to resume."})
    output = Path(job.get("output_dir") or ".")
    meta = {}
    sidecar = output / ".fizgig_paused.json"
    if sidecar.is_file():
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
    state_path = str(meta.get("state_path") or job.get("state_path") or "")
    mode = str(meta.get("mode") or "state")
    values = dict(job.get("values") or {})
    context = dict(job.get("context") or {})
    if mode == "ft":
        if not state_path or not os.path.isfile(state_path):
            raise JobError(409, {"detail": f"Paused fine-tune checkpoint not found:\n{state_path}"})
        _window, epochs_done = _ft_epochs(state_path)
        try:
            total = int(float(str(values.get("MAX_TRAIN_EPOCHS") or 0).strip() or 0))
        except (TypeError, ValueError):
            total = 0
        if total - epochs_done <= 0:
            name = os.path.basename(state_path)
            raise JobError(409, {"detail": (
                f"This fine-tune has already trained {epochs_done} epoch(s) — at or past "
                f"Max Train Epochs ({total}).\n\n"
                f"{name} IS the finished model — deploy it as-is.\n\n"
                f"To train it further, raise Max Train Epochs above {epochs_done} and click "
                "Resume Training again.")})
        context["ft_resume"] = {"checkpoint": state_path, "output_name": values.get("LORA_NAME", "")}
        context["resuming"] = True
        values["RESUME_TRAINING"] = ""
    else:
        if not state_path or not os.path.isdir(state_path):
            raise JobError(409, {"detail": f"Paused state directory not found:\n{state_path}"})
        values["RESUME_TRAINING"] = state_path
        context["resuming"] = True
    return start(job["family"], values, context, list(confirm or []), existing=job)


def stop(job_id: str) -> dict:
    """Kill the process tree and mark the job stopped. Mirrors ``stop_training``."""
    folder, job = _get(job_id)
    if job.get("status") not in _ACTIVE:
        raise JobError(409, {"detail": "No active process to stop"})
    pid = int(job.get("pid") or 0)
    # A recycled pid is someone else's process. Do not kill its tree.
    if pid and _pid_exists(pid) and not _runner_alive(job):
        _fail_reused_pid(folder, job)
        return public(job)
    (folder / "STOP").write_text("", encoding="utf-8")
    if _runner_alive(job):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                creationflags=creationflags(),
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
    job["status"] = "stopped"
    job["ended"] = _now()
    _write(folder, job)
    return public(job)


def _whole(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def write_override(job_id: str, prompt, seed, width, height) -> dict:
    """Write or remove ``.sample_override.json``. Mirrors ``_on_sample_override_changed``."""
    _folder, job = _get(job_id)
    _train_only(job)
    output = Path(job.get("output_dir") or ".")
    if not _inside(output, output):
        raise JobError(404, {"detail": "not found"})
    path = output / ".sample_override.json"
    text = "" if prompt is None else str(prompt).strip()
    if not text:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
        return {"prompt": "", "active": False}
    data = {
        "prompt": text,
        "seed": _whole(seed, 1234),
        "width": _whole(width, 768),
        "height": _whole(height, 768),
    }
    output.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)
    return data


def read_log(job_id: str, offset: int) -> dict:
    folder, _job = _get(job_id)
    path = (folder / "log.txt").resolve()
    if not _inside(path, folder.resolve()):
        raise JobError(404, {"detail": "not found"})
    if not path.is_file():
        return {"offset": 0, "next": 0, "text": ""}
    size = path.stat().st_size
    start = max(0, int(offset))
    if start > size:
        start = size
    with open(path, "rb") as handle:
        handle.seek(start)
        blob = handle.read()
    return {"offset": start, "next": start + len(blob), "text": blob.decode("utf-8", "replace")}


def _safe_name(name: str) -> bool:
    if not name or name in {".", ".."}:
        return False
    return name == Path(name).name and "/" not in name and "\\" not in name


def list_samples(job_id: str) -> dict:
    _folder, job = _get(job_id)
    output = Path(job.get("output_dir") or "")
    folder = output / "sample"
    samples = []
    if folder.is_dir() and _inside(folder, output):
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _IMAGE_EXT:
                continue
            if _inside(path, output):
                samples.append({
                    "name": path.name,
                    "url": f"/api/jobs/{job_id}/samples/{path.name}",
                })
    return {"samples": samples}


def sample_path(job_id: str, name: str) -> Path:
    if not _safe_name(name):
        raise JobError(404, {"detail": "not found"})
    _folder, job = _get(job_id)
    output = Path(job.get("output_dir") or "").resolve()
    path = (output / "sample" / name).resolve()
    if not _inside(path, output) or not path.is_file():
        raise JobError(404, {"detail": "not found"})
    return path


def detect_state_dir(out_dir: Path, out_name: str) -> Path | None:
    """Highest ``<name>-NNNNNN-state`` with a commit marker. Mirrors ``_detect_latest_state_dir``."""
    if not out_name or not out_dir.is_dir():
        return None
    pattern = re.compile(rf"^{re.escape(out_name)}-(\d{{6}})-state$")
    found = []
    try:
        entries = list(out_dir.iterdir())
    except OSError:
        return None
    for entry in entries:
        matched = pattern.match(entry.name)
        if not matched or not entry.is_dir():
            continue
        if any((entry / marker).is_file() for marker in ("training_state.json", "random_states_0.pkl")):
            found.append((int(matched.group(1)), entry))
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


def mark_paused(folder: Path, job: dict) -> None:
    """Record a graceful pause. Mirrors the sidecar write in ``_on_training_subprocess_exited``."""
    output = Path(job.get("output_dir") or ".")
    name = str((job.get("values") or {}).get("LORA_NAME") or "")
    state = detect_state_dir(output, name)
    if state is None:
        job["status"] = "failed"
        job["exit_code"] = 0
        job["ended"] = _now()
        return
    values = job.get("values") or {}
    sidecar = {
        "mode": "state",
        "state_path": str(state),
        "output_name": name,
        "dataset_config": str(job.get("dataset_config") or values.get("DATASET_CONFIG") or ""),
        "network_dim": str(values.get("NETWORK_DIM", "")),
        "network_alpha": str(values.get("NETWORK_ALPHA", "")),
        "max_train_epochs": str(values.get("MAX_TRAIN_EPOCHS", "")),
    }
    with open(output / ".fizgig_paused.json", "w", encoding="utf-8") as handle:
        json.dump(sidecar, handle, indent=2)
    job["status"] = "paused"
    job["state_path"] = str(state)
    job["exit_code"] = 0
    job["ended"] = _now()
    _write(folder, job)
