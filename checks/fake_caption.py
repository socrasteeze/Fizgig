"""Stand-in for batch_caption.py --serve.

Speaks the same stdout protocol and writes a caption file. It does not load a model.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--config", default="")
    args = parser.parse_args()
    if not args.serve or not args.config:
        print("FAIL: --config required with --serve", flush=True)
        return 1
    print("READY", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "QUIT":
            break
        if not line.startswith("RUN "):
            print(f"FAIL: unknown command {line!r}", flush=True)
            continue
        path = line[4:].strip()
        try:
            with open(path, encoding="utf-8") as handle:
                job = json.load(handle)
            with open(job["list_file"], encoding="utf-8") as handle:
                images = [item.strip() for item in handle if item.strip()]
            total = len(images)
            if not total:
                print("FAIL: no images in list", flush=True)
                print("DONE", flush=True)
                continue
            trigger = (job.get("trigger") or "").strip()
            text = f"{trigger}, fake caption" if trigger else "fake caption"
            stopped = False
            for index, image in enumerate(images, 1):
                stop = (job.get("stop_file") or "").strip()
                if stop and os.path.exists(stop):
                    stopped = True
                    break
                print(f"PROGRESS: {index} {total}", flush=True)
                caption = os.path.splitext(image)[0] + ".txt"
                with open(caption, "w", encoding="utf-8") as handle:
                    handle.write(text)
                print(f"OK: {os.path.basename(image)}", flush=True)
            print("STOPPED" if stopped else "DONE", flush=True)
        except Exception as exc:
            print(f"FAIL: job ({exc})", flush=True)
            print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
