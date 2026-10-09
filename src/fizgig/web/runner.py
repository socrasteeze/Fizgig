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
