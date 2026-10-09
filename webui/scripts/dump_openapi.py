"""Write the server's OpenAPI document. Does not start a server.

    python webui/scripts/dump_openapi.py webui/openapi.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from fizgig.web.app import app


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    payload = json.dumps(app.openapi(), indent=2)
    if args:
        Path(args[0]).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
