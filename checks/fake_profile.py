"""Stand-in for profile_lora.py.

Writes the HTML report named by --output and prints one progress line.
It does not load a model or touch CUDA.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lora", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    output = args.output
    if not output.lower().endswith(".html"):
        output = str(Path(args.lora).with_suffix("")) + "_profile.html"
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<html><body>fake profile</body></html>", encoding="utf-8")
    path.with_suffix(".argv.txt").write_text("\n".join(sys.argv[1:]), encoding="utf-8")
    print("PROGRESS: 1 1", flush=True)
    print(f"Report:  {path}", flush=True)


if __name__ == "__main__":
    main()
