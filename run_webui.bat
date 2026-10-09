@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
set "PY=%CD%\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import sys; from pathlib import Path; root=Path('webui'); dist=root/'dist'/'index.html'; skip={'node_modules','dist'}; newest=max((p.stat().st_mtime for p in root.rglob('*') if p.is_file() and not (set(p.parts)&skip)), default=0); built=dist.stat().st_mtime if dist.is_file() else 0; sys.exit(0 if built>=newest else 1)"
if errorlevel 1 call npm --prefix webui run build
if errorlevel 1 exit /b 1
"%PY%" -m fizgig.web
