"""Stand-in for extract_lora.py.

Writes a marker at --output and prints progress. It does not load a model
or touch CUDA.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rank", default="4")
    parser.add_argument("--preset", default="")
    parser.add_argument("--blocks", default="")
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-extract")
    path.with_suffix(".argv.txt").write_text("\n".join(sys.argv[1:]), encoding="utf-8")
    print("PROGRESS: 1 2", flush=True)
    print("PROGRESS: 2 2", flush=True)
    print(f"Wrote {path}", flush=True)


if __name__ == "__main__":
    main()
