"""Stand-in for fizgig.web.convert_run.

Writes one placeholder per rank. It does not load a model or touch CUDA.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--tuned", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--ranks", required=True)
    args = parser.parse_args()
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    for part in args.ranks.split(","):
        text = part.strip()
        if not text:
            continue
        rank = int(text)
        (folder / f"{args.name}_fake_r{rank}.safetensors").write_bytes(b"fake")
    print("PROGRESS: 1 1", flush=True)


if __name__ == "__main__":
    main()
