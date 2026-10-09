"""Stand-in for one plan() stage.

Prints tqdm lines the progress parser accepts, writes one sample image, and exits
when ``<output>/.pause_requested`` appears. It does not load a model or touch CUDA.

The runner sets FIZGIG_FAKE_OUTPUT, FIZGIG_FAKE_NAME, FIZGIG_FAKE_STEPS, and
FIZGIG_FAKE_SLEEP.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# 1x1 PNG.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _pause(output: Path, name: str) -> None:
    state = output / f"{name}-000001-state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "training_state.json").write_text("{}", encoding="utf-8")
    print("pause requested", flush=True)


def _asleep(seconds: float, flag: Path) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if flag.is_file():
            return True
        time.sleep(min(0.05, max(0.0, end - time.time())))
    return flag.is_file()


def main() -> None:
    output = Path(os.environ.get("FIZGIG_FAKE_OUTPUT") or ".")
    name = os.environ.get("FIZGIG_FAKE_NAME") or "lora"
    steps = int(os.environ.get("FIZGIG_FAKE_STEPS") or "4")
    delay = float(os.environ.get("FIZGIG_FAKE_SLEEP") or "0.05")
    output.mkdir(parents=True, exist_ok=True)
    (output / "child.pid").write_text(str(os.getpid()), encoding="utf-8")
    sample = output / "sample"
    sample.mkdir(parents=True, exist_ok=True)
    (sample / "sample_0001.png").write_bytes(_PNG)
    flag = output / ".pause_requested"
    for step in range(1, steps + 1):
        if flag.is_file():
            _pause(output, name)
            return
        print(
            f"steps: {step}/{steps} [00:01<00:04, 1.00it/s, avr_loss=0.42]",
            flush=True,
        )
        if _asleep(delay, flag):
            _pause(output, name)
            return
    print("stage done", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
