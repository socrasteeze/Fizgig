"""Fizgig web server.

Listens on 127.0.0.1 only. There is no listen option. ``families/train.py`` is not
imported: that module loads torch. Its argument parser is read from source.
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

LOOPBACK = "127.0.0.1"
PORT = 8081
_STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_REPO = Path(__file__).resolve().parents[3]
_FAMILIES = Path(__file__).resolve().parents[1] / "families"
_ADVANCED: list | None = None

app = FastAPI(title="Fizgig")


def _allowed_names() -> set[str]:
    names = {"localhost", LOOPBACK}
    extra = os.environ.get("FIZGIG_WEB_TAILNET_HOST", "").strip()
    if extra:
        names.add(_host_name(extra))
    return names


def _host_name(value: str) -> str:
    text = value.strip().lower()
    if text.startswith("[") and "]" in text:
        return text[1:text.index("]")]
    if text.count(":") == 1:
        name, _, port = text.partition(":")
        if port.isdigit():
            return name
    return text


def _origin_name(value: str) -> str:
    return (urlsplit(value.strip()).hostname or "").lower()


@app.middleware("http")
async def check_host_origin(request, call_next):
    allowed = _allowed_names()
    if _host_name(request.headers.get("host", "")) not in allowed:
        return JSONResponse({"detail": "forbidden host"}, status_code=403)
    if request.method in _STATE_CHANGING:
        origin = request.headers.get("origin")
        if origin is not None and _origin_name(origin) not in allowed:
            return JSONResponse({"detail": "forbidden origin"}, status_code=403)
    return await call_next(request)


def _jsonable(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _precisions() -> tuple:
    tree = ast.parse((_FAMILIES / "quant.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "PRECISIONS":
                value = ast.literal_eval(node.value)
                if isinstance(value, tuple):
                    return value
    raise RuntimeError("PRECISIONS is missing")


def advanced_options() -> list:
    """Argparse options of families/train.py, without importing that module."""
    global _ADVANCED
    if _ADVANCED is not None:
        return _ADVANCED
    tree = ast.parse((_FAMILIES / "train.py").read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "setup_parser")
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "argparse": argparse,
        "quant": type("quant", (), {"PRECISIONS": _precisions()}),
    }
    exec(compile(module, "fizgig/families/train.py", "exec"), namespace)
    options = []
    for action in namespace["setup_parser"]()._actions:
        if not action.option_strings:
            continue
        choices = None if action.choices is None else list(action.choices)
        nargs = action.nargs if isinstance(action.nargs, (str, int)) or action.nargs is None else str(action.nargs)
        options.append({
            "dest": action.dest,
            "flags": list(action.option_strings),
            "help": action.help,
            "required": bool(getattr(action, "required", False)),
            "default": _jsonable(action.default),
            "choices": _jsonable(choices),
            "nargs": nargs,
        })
    _ADVANCED = options
    return options


@app.get("/api/schema")
def schema(family: str):
    from fizgig.families.registry import get as get_family

    desc = get_family(family)
    if desc is None:
        raise HTTPException(status_code=404, detail="unknown family")
    body = _jsonable(desc)
    body["advanced"] = advanced_options()
    return body


@app.get("/api/form")
def form(family: str):
    """Training-tab fields for one family, then the argparse flags the form does not already cover."""
    from fizgig.families.registry import get as get_family
    from fizgig.web.form_spec import form_for

    desc = get_family(family)
    if desc is None:
        raise HTTPException(status_code=404, detail="unknown family")
    return form_for(desc, advanced_options())


@app.post("/api/ping")
def ping():
    """No training route exists yet. This POST exists so the Origin check has a request to reject."""
    return {"ok": True}


_dist = _REPO / "webui" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")


def serve(host: str = LOOPBACK, port: int = PORT) -> None:
    if host != LOOPBACK:
        raise SystemExit("refusing to listen on a non-loopback address")
    import uvicorn
    uvicorn.run(app, host=host, port=port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m fizgig.web")
    parser.parse_args(argv)
    serve()
