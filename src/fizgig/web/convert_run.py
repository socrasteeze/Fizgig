"""One conversion. Started as ``python -m fizgig.web.convert_run``. Not imported."""
from __future__ import annotations


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--tuned", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--ranks", required=True)
    args = parser.parse_args()
    ranks = [int(part) for part in args.ranks.split(",") if part.strip()]

    def progress(done: int, total: int, _key: str) -> None:
        print(f"PROGRESS: {done} {total}", flush=True)

    from fizgig.extraction.model_diff import extract_diff_loras

    extract_diff_loras(
        args.base, args.tuned, args.output, ranks, name=args.name, progress=progress,
    )


if __name__ == "__main__":
    main()
