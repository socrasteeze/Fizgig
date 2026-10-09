#!/bin/sh
# The server listens on 127.0.0.1 only.
set -eu
cd "$(dirname "$0")"
PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
if [ -e venv/bin/python ]; then
  PY=venv/bin/python
elif [ -e venv/Scripts/python.exe ]; then
  PY=venv/Scripts/python.exe
else
  PY=python3
fi
if ! "$PY" -c "import sys; from pathlib import Path; root=Path('webui'); dist=root/'dist'/'index.html'; skip={'node_modules','dist'}; newest=max((p.stat().st_mtime for p in root.rglob('*') if p.is_file() and not (set(p.parts)&skip)), default=0); built=dist.stat().st_mtime if dist.is_file() else 0; sys.exit(0 if built>=newest else 1)"; then
  npm --prefix webui run build
fi
exec "$PY" -m fizgig.web
