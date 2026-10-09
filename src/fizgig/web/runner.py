"""Run one job's stages and exit. The server starts this detached.

A server restart does not kill this process. Stop kills the tree from outside.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fizgig.gpu_lock import GpuLock
from fizgig.training.progress import TrainingProgressTracker
from fizgig.web.jobs import _load, _now, bind_runner, mark_paused, save

_REPO = Path(__file__).resolve().parents[3]


def _loss(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    lock = GpuLock()
    if not lock.acquire():
        output = Path(job.get("output_dir") or "")
        resuming = bool(str((job.get("values") or {}).get("RESUME_TRAINING") or ""))
        if resuming or (output / ".fizgig_paused.json").is_file():
            job["status"] = "paused"
        else:
            job["status"] = "failed"
        job["ended"] = _now()
        save(folder, job)
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
    if os.name == "nt":
        popen["creationflags"] = subprocess.CREATE_NO_WINDOW

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
            proc = subprocess.Popen(stage.get("cmd") or [], **popen)
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                log.flush()
                update = tracker.consume(line)
                if update and update.get("kind") == "training":
                    job["step"] = int(update["step"])
                    job["total"] = int(update["total_steps"])
                    parsed = _loss(update.get("average_loss_text"))
                    if parsed is not None:
                        job["loss"] = parsed
                    if not save(folder, job):
                        proc.kill()
                        return
            code = proc.wait()
            if (folder / "STOP").is_file():
                job["status"] = "stopped"
                job["ended"] = _now()
                save(folder, job)
                return
            pause = output / ".pause_requested"
            paused = pause.is_file()
            if paused:
                try:
                    pause.unlink()
                except OSError:
                    pass
            if code == 0 and paused:
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
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)


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
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        for line in proc.stdout:
            log.write(line)
            log.flush()
            text = line.strip()
            if text == "READY":
                proc.stdin.write(f"RUN {folder / 'caption_job.json'}\n")
                proc.stdin.flush()
            elif text.startswith("PROGRESS:"):
                parts = text.split()
                if len(parts) >= 3:
                    try:
                        job["step"] = int(parts[1])
                        job["total"] = int(parts[2])
                        job["stage"] = "Caption"
                        if not save(folder, job):
                            break
                    except ValueError:
                        pass
            elif text == "DONE":
                saw_done = True
                try:
                    proc.stdin.write("QUIT\n")
                    proc.stdin.flush()
                except OSError:
                    pass
            elif text == "STOPPED":
                try:
                    proc.stdin.write("QUIT\n")
                    proc.stdin.flush()
                except OSError:
                    pass
                break
            elif text.startswith("FAIL:") and not saw_done and job.get("step", 0) == 0 and "job" not in text:
                # A failure before READY (model load). Keep reading until the process exits.
                pass
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
            with (folder / "log.txt").open("a", encoding="utf-8") as handle:
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
