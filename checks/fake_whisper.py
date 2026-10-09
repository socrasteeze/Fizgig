"""Stand-in for fizgig.web.whisper_run.

Writes a fixed caption and prints progress. It does not load a model.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--span", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = 'saying "fake words"'
    path.write_text(text, encoding="utf-8")
    print("CAPTION: " + text, flush=True)
    print("PROGRESS: 1 1", flush=True)


if __name__ == "__main__":
    main()
