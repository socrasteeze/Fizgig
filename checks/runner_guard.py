"""Teardown for web tests that can start a job.

A job runs in a detached process, ``python -m fizgig.web.runner <job folder>``, that
outlives the request that started it. Until it exits it can hold files in the test's
temp folder (Windows will not delete an open file) and the GPU lock file
``cache/gpu/<n>.lock``, which the next test reads.

Call ``end_runs`` from tearDown after the test's TestClient has exited. Exiting the
client joins the server's queue thread, so no queued item can start a run after that.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import psutil

from fizgig.web import jobs

_ACTIVE = frozenset({"queued", "running"})
_RUNNER = "fizgig.web.runner"


def runner_pids(jobs_dir: Path) -> list[int]:
    """Live runner processes for a job folder under ``jobs_dir``, with their children.

    ``jobs._spawn`` starts every runner with Popen from this process, so only this
    process's children are read. A scan of every process is too slow to run per test.
    """
    marker = os.path.normcase(str(jobs_dir))
    found: set[int] = set()
    for proc in psutil.Process().children(recursive=True):
        try:
            line = os.path.normcase(" ".join(proc.cmdline()))
        except psutil.Error:
            continue
        if _RUNNER not in line or marker not in line:
            continue
        found.add(proc.pid)
        try:
            found.update(child.pid for child in proc.children(recursive=True))
        except psutil.Error:
            pass
    return sorted(found)


def _kill(pids: list[int]) -> None:
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                child.kill()
            proc.kill()
        except psutil.Error:
            pass


def queue_thread_alive() -> bool:
    return any(thread.name == "fizgig-queue" and thread.is_alive() for thread in threading.enumerate())


def end_runs(jobs_dir: Path, timeout: float = 20.0) -> None:
    """Stop every active job under ``jobs_dir`` and wait until no runner process for it is alive.

    This is the tearDown check. It fails the test when a runner is still alive after
    ``timeout`` (the leftovers are killed first), and when the server's queue thread
    is still running.
    """
    deadline = time.time() + timeout
    while True:
        for job in jobs.list_jobs():
            if job["status"] in _ACTIVE:
                try:
                    jobs.stop(job["id"])
                except Exception:
                    pass
        alive = runner_pids(jobs_dir)
        if not alive:
            break
        if time.time() >= deadline:
            _kill(alive)
            raise AssertionError(f"a job runner is still alive after teardown (pids {alive})")
        time.sleep(0.05)
    if queue_thread_alive():
        raise AssertionError("the server queue thread is still running after the client exited")
