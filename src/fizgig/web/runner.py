"""Run one job's stages and exit. The server starts this detached.

A server restart does not kill this process. Stop kills the tree from outside.
Stages inherit this process's hidden console and pass no window flags, so the
tools they start stay hidden as well.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from fizgig.gpu_lock import GpuLock
from fizgig.training.progress import TrainingProgressTracker
from fizgig.web.jobs import _load, _now, bind_runner, mark_paused, save

_REPO = Path(__file__).resolve().parents[3]

# batch_caption --serve: "FAIL: <image name> (<reason>)" is one image, and the batch goes on.
# Any other FAIL line after RUN is fatal for the job.
_PER_IMAGE_FAIL = re.compile(r"^FAIL: [^()]+?\.[A-Za-z0-9]+ \(.*\)$")

# A loaded engine's worker can still hold the card's lock for a moment after the server
# has let go. The run waits this long for it, polling every _LOCK_POLL seconds.
# FIZGIG_WEB_LOCK_GRACE overrides the grace in seconds (tests use 1).
_LOCK_GRACE = 15.0
_LOCK_POLL = 0.25


def _loss(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lock_grace() -> float:
    raw = (os.environ.get("FIZGIG_WEB_LOCK_GRACE") or "").strip()
    try:
        value = float(raw) if raw else _LOCK_GRACE
    except ValueError:
        return _LOCK_GRACE
    return value if value >= 0 else _LOCK_GRACE


def _log_line(folder: Path, text: str) -> None:
    with (folder / "log.txt").open("a", encoding="utf-8", errors="replace") as log:
        log.write(text + "\n")


def _wait_for_gpu(folder: Path, job: dict, lock: GpuLock, device: int) -> bool:
    """Take the card's lock before any stage runs. True only when this process holds it.

    The server refuses a start while the lock is held. A lock that is still held
    when the runner starts (an engine worker letting go) is waited for, up to the
    grace. False means the job is already recorded as stopped, paused, or failed.
    """
    if lock.acquire():
        return True
    grace = _lock_grace()
    _log_line(folder, f"Waiting up to {grace:g} s for GPU {device} to be released by another process.")
    # While waiting, the record carries this runner's pid. A pid-less queued record is
    # failed by reconcile after its grace, and stop and reconcile both read the pid.
    bind_runner(job)
    if not save(folder, job):
        return False
    deadline = time.monotonic() + grace
    while True:
        if (folder / "STOP").is_file():
            job["status"] = "stopped"
            job["ended"] = job.get("ended") or _now()
            save(folder, job)
            return False
        if lock.acquire():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_LOCK_POLL, remaining))
    _log_line(folder, f"GPU {device} is in use by another run; job not started.")
    output = Path(job.get("output_dir") or "")
    resuming = bool(str((job.get("values") or {}).get("RESUME_TRAINING") or ""))
    if resuming or (output / ".fizgig_paused.json").is_file():
        job["status"] = "paused"
    else:
        job["status"] = "failed"
    job["ended"] = _now()
    save(folder, job)
    return False


def run_folder(folder: Path) -> None:
    folder = folder.resolve()
    job = _load(folder)
    if job is None:
        return
    if (folder / "STOP").is_file():
        job["status"] = "stopped"
        job["ended"] = job.get("ended") or _now()
        save(folder, job)
        return

    raw = job.get("device")
    try:
        device = 0 if raw is None or raw == "" else int(raw)
    except (TypeError, ValueError):
        device = 0
    os.environ["CUDA_VISIBLE_DEVICES"] = str(device)
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    lock = GpuLock(device)
    if not _wait_for_gpu(folder, job, lock, device):
        return

    try:
        kind = job.get("kind") or "train"
        if kind == "caption":
            _run_caption(folder, job)
        elif kind == "prep":
            _run_prep(folder, job)
        elif kind == "profile":
            from fizgig.web.profile import command
            _run_tool(folder, job, command(job))
        elif kind == "extract":
            from fizgig.web.extract import command
            _run_tool(folder, job, command(job))
        elif kind == "royale":
            from fizgig.web.royale import run_job
            run_job(folder, job)
        elif kind == "gizmo":
            from fizgig.web.gizmo import run_job
            run_job(folder, job)
        elif kind == "whisper":
            from fizgig.web.gizmo import run_whisper
            run_whisper(folder, job)
        elif kind == "convert":
            from fizgig.web.convert import command
            _run_tool(folder, job, command(job))
        else:
            _run(folder, job)
    finally:
        lock.release()


def _run(folder: Path, job: dict) -> None:
    output = Path(job.get("output_dir") or ".")
    resume = str((job.get("values") or {}).get("RESUME_TRAINING") or "")
    job["status"] = "running"
    bind_runner(job)
    job["started"] = _now()
    job["ended"] = ""
    if not save(folder, job):
        return
    if resume:
        sidecar = output / ".fizgig_paused.json"
        try:
            if sidecar.is_file():
                sidecar.unlink()
        except OSError:
            pass

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["FIZGIG_FAKE_OUTPUT"] = str(output)
    env["FIZGIG_FAKE_NAME"] = str((job.get("values") or {}).get("LORA_NAME") or "")
    tracker = TrainingProgressTracker((job.get("values") or {}).get("MAX_TRAIN_EPOCHS") or 1)
    log_path = folder / "log.txt"
    popen = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=str(_REPO),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        if resume:
            log.write(f"\n=== RESUMING from {resume} ===\n")
            log.flush()
        for stage in (job.get("plan") or {}).get("stages") or []:
            if (folder / "STOP").is_file():
                job["status"] = "stopped"
                job["ended"] = _now()
                save(folder, job)
                return
            job["stage"] = stage.get("name") or ""
            if not save(folder, job):
                return
            # No window flags: inherit the runner's hidden console.
            proc = subprocess.Popen(
                stage.get("cmd") or [],
                creationflags=0,
                **popen,
            )
            assert proc.stdout is not None
            code = 1
            try:
                for line in proc.stdout:
                    try:
                        log.write(line)
                        log.flush()
                    except OSError:
                        pass
                    update = tracker.consume(line)
                    if update and update.get("kind") == "training":
                        job["step"] = int(update["step"])
                        job["total"] = int(update["total_steps"])
                        parsed = _loss(update.get("average_loss_text"))
                        if parsed is not None:
                            job["loss"] = parsed
                        try:
                            if not save(folder, job):
                                proc.kill()
                                break
                        except OSError:
                            pass
                if proc.poll() is None and (folder / "STOP").is_file():
                    proc.kill()
                code = proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    try:
                        proc.wait()
                    except OSError:
                        pass
                if proc.stdout is not None:
                    proc.stdout.close()
            if (folder / "STOP").is_file():
                job["status"] = "stopped"
                job["ended"] = _now()
                save(folder, job)
                return
            # A cache stage must keep going. The trainer is what reads the flag.
            if (stage.get("name") or "") == "Training":
                pause = output / ".pause_requested"
                if code == 0 and pause.is_file():
                    try:
                        pause.unlink()
                    except OSError:
                        pass
                    mark_paused(folder, job)
                    return
            if code != 0:
                job["status"] = "failed"
                job["exit_code"] = code
                job["ended"] = _now()
                save(folder, job)
                return
        job["status"] = "done"
        job["exit_code"] = 0
        job["ended"] = _now()
        save(folder, job)


def _begin(folder: Path, job: dict) -> bool:
    job["status"] = "running"
    bind_runner(job)
    job["started"] = job.get("started") or _now()
    job["ended"] = ""
    return save(folder, job)


def _finish(folder: Path, job: dict, status: str, code: int) -> None:
    job["status"] = status
    job["exit_code"] = code
    job["ended"] = _now()
    save(folder, job)


def _popen(cmd, env, stdin):
    kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=stdin,
        cwd=str(_REPO),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    # No window flags: inherit the runner's hidden console.
    return subprocess.Popen(cmd, creationflags=0, **kwargs)


def _run_caption(folder: Path, job: dict) -> None:
    """Speak the batch_caption --serve protocol and copy it into log.txt."""
    from fizgig.web.captions import command

    if not _begin(folder, job):
        return
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    src = str(_REPO / "src")
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src + (os.pathsep + previous if previous else "")
    log_path = folder / "log.txt"
    proc = _popen(command(folder), env, subprocess.PIPE)
    assert proc.stdin is not None and proc.stdout is not None
    saw_done = False
    sent_run = False
    fatal = False
    quit_sent = False

    def quit_worker() -> None:
        # The worker reads QUIT only between runs. Keep reading its stdout until it exits, so its pipe never fills.
        nonlocal quit_sent
        if quit_sent:
            return
        quit_sent = True
        try:
            proc.stdin.write("QUIT\n")
            proc.stdin.flush()
        except OSError:
            pass

    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        for line in proc.stdout:
            try:
                log.write(line)
                log.flush()
            except OSError:
                pass
            text = line.strip()
            if text == "READY":
                proc.stdin.write(f"RUN {folder / 'caption_job.json'}\n")
                proc.stdin.flush()
                sent_run = True
            elif text.startswith("FAIL:") and sent_run and not _PER_IMAGE_FAIL.match(text):
                fatal = True
                quit_worker()
            elif text.startswith("PROGRESS:"):
                parts = text.split()
                if len(parts) >= 3:
                    try:
                        job["step"] = int(parts[1])
                        job["total"] = int(parts[2])
                        job["stage"] = "Caption"
                        if not save(folder, job):
                            quit_worker()
                    except ValueError:
                        pass
            elif text == "DONE":
                # The worker prints DONE after a job-level FAIL too. That job is failed, not done.
                saw_done = not fatal
                quit_worker()
            elif text == "STOPPED":
                quit_worker()
            # Per-image FAIL lines and a FAIL before RUN (model load) are logged above. Reading goes on.
    code = proc.wait()
    if (folder / "STOP").is_file() or (folder / "caption_stop").is_file():
        _finish(folder, job, "stopped", code)
    elif saw_done and code == 0:
        _finish(folder, job, "done", 0)
    else:
        _finish(folder, job, "failed", code)


def _tool_step(line: str):
    text = line.strip()
    if text.startswith("PROGRESS:"):
        parts = text.split()
        if len(parts) >= 3:
            try:
                return int(parts[1]), int(parts[2])
            except ValueError:
                return None
    import re
    matched = re.search(r"(\d+)\s*/\s*(\d+)\s*$", text)
    if matched:
        return int(matched.group(1)), int(matched.group(2))
    return None


def _run_tool(folder: Path, job: dict, cmd: list[str]) -> None:
    """Run a profiler or extract command. Stdout is the job log."""
    if not _begin(folder, job):
        return
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    src = str(_REPO / "src")
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src + (os.pathsep + previous if previous else "")
    log_path = folder / "log.txt"
    proc = _popen(cmd, env, subprocess.DEVNULL)
    assert proc.stdout is not None
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        for line in proc.stdout:
            log.write(line if line.endswith("\n") else line + "\n")
            log.flush()
            step = _tool_step(line)
            if step is not None:
                job["step"], job["total"] = step
                if not save(folder, job):
                    proc.kill()
                    break
            if (folder / "STOP").is_file():
                proc.kill()
                break
    code = proc.wait()
    if (folder / "STOP").is_file():
        _finish(folder, job, "stopped", code)
    elif code == 0:
        _finish(folder, job, "done", 0)
    else:
        _finish(folder, job, "failed", code)


def _run_prep(folder: Path, job: dict) -> None:
    from fizgig.web.image_prep import prepare

    if not _begin(folder, job):
        return
    job["stage"] = "Image Prep"
    if not save(folder, job):
        return
    log_path = folder / "log.txt"

    def write(text: str) -> None:
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            log.write(text)
            log.flush()

    prepare(job.get("values") or {}, write)
    _finish(folder, job, "done", 0)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: python -m fizgig.web.runner <job-folder>")
    folder = Path(args[0])
    try:
        run_folder(folder)
    except Exception:
        import traceback
        try:
            with (folder / "log.txt").open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(traceback.format_exc())
            job = _load(folder)
            if job and job.get("status") in {"queued", "running"}:
                job["status"] = "failed"
                job["ended"] = _now()
                save(folder, job)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    main()
