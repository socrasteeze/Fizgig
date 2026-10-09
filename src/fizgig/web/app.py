"""Fizgig web server.

Listens on 127.0.0.1 only. There is no listen option. ``families/train.py`` is not
imported: that module loads torch. Its argument parser is read from source.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import dataclasses
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

LOOPBACK = "127.0.0.1"
PORT = 8081
_STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_REPO = Path(__file__).resolve().parents[3]
_FAMILIES = Path(__file__).resolve().parents[1] / "families"
_ADVANCED: list | None = None


@asynccontextmanager
async def _lifespan(_app):
    yield
    from fizgig.web.engine_host import shutdown
    shutdown()


app = FastAPI(title="Fizgig", lifespan=_lifespan)


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


class FormOut(BaseModel):
    family: str
    display_name: str
    fields: list[dict]
    advanced: list[dict]
    presets: list[dict]
    models: list[dict]


class JobOut(BaseModel):
    id: str
    family: str
    status: str
    pid: int | None = None
    stage: str = ""
    step: int = 0
    total: int = 0
    loss: float | None = None
    created: str = ""
    started: str = ""
    ended: str = ""
    output_dir: str = ""
    kind: str = "train"


class JobCreate(BaseModel):
    family: str
    values: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    confirm: list[str] = Field(default_factory=list)


class ConfirmIn(BaseModel):
    confirm: list[str] = Field(default_factory=list)


class WarningItem(BaseModel):
    code: str
    message: str


class ProblemsOut(BaseModel):
    problems: list[str]


class ConflictOut(BaseModel):
    detail: str | None = None
    warnings: list[WarningItem] | None = None


class JobList(BaseModel):
    jobs: list[JobOut]


class LogOut(BaseModel):
    offset: int
    next: int
    text: str


class SampleItem(BaseModel):
    name: str
    url: str


class SampleList(BaseModel):
    samples: list[SampleItem]


class OverrideIn(BaseModel):
    prompt: str = ""
    seed: str | int | None = None
    width: str | int | None = None
    height: str | int | None = None


class OverrideOut(BaseModel):
    prompt: str = ""
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    active: bool | None = None


class HistoryItem(JobOut):
    duration: int | None = None


class QueueItem(BaseModel):
    id: str
    family: str
    values: dict
    context: dict
    added: str = ""
    label: str = ""


class QueueOut(BaseModel):
    items: list[QueueItem]


class QueueImport(BaseModel):
    imported: int
    skipped: int
    items: list[QueueItem]


class OrderIn(BaseModel):
    ids: list[str]


class StartOut(BaseModel):
    folder: str = ""
    images: int = 0
    captions: int = 0
    missing: int = 0
    ready: bool = False


class StartIn(BaseModel):
    folder: str = ""


class PrefsIn(BaseModel):
    values: dict = Field(default_factory=dict)


class HistoryOut(BaseModel):
    jobs: list[HistoryItem]


class CaptionIn(BaseModel):
    folder: str = ""
    name: str = ""
    text: str = ""
    trigger: str = ""
    model: str = ""
    task: str = ""
    max_tokens: int | None = None
    overwrite: bool = False
    instruction: str = ""
    include_video: bool = False


class PrepIn(BaseModel):
    folder: str = ""
    mode: str = ""
    megapixels: str = ""
    face: str = ""
    padding: str = ""
    replace_originals: bool = False


class MemoryOut(BaseModel):
    used: int
    total: int


class SystemOut(BaseModel):
    vram: MemoryOut | None = None
    ram: MemoryOut | None = None


def _call(fn, *args):
    from fizgig.web.jobs import JobError
    try:
        return fn(*args)
    except JobError as exc:
        return JSONResponse(exc.body, status_code=exc.status)


@app.get("/api/form", response_model=FormOut)
def form(family: str):
    """Training-tab fields for one family, then the argparse flags the form does not already cover."""
    from fizgig.families.registry import get as get_family
    from fizgig.web.form_spec import form_for, web_values

    desc = get_family(family)
    if desc is None:
        raise HTTPException(status_code=404, detail="unknown family")
    body = form_for(desc, advanced_options())
    body["display_name"] = desc.display_name
    body["presets"] = [
        {"name": item[0], "values": web_values(desc, item[1])}
        for item in desc.presets
    ]
    body["models"] = [
        {"key": item.pref_key, "label": item.label, "required": bool(item.required)}
        for item in desc.model_files
    ]
    return body


@app.post("/api/jobs", response_model=JobOut, responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def create_job(body: JobCreate):
    from fizgig.web import jobs
    return _call(jobs.start, body.family, body.values, body.context, body.confirm)


@app.get("/api/jobs", response_model=JobList)
def list_jobs():
    from fizgig.web import jobs
    from fizgig.web.queue import observe

    rows = jobs.list_jobs()
    observe(rows)
    return {"jobs": jobs.list_jobs()}


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def read_job(job_id: str):
    from fizgig.web import jobs
    return _call(jobs.get_job, job_id)


@app.get("/api/jobs/{job_id}/log", response_model=LogOut)
def read_log(job_id: str, offset: int = 0):
    from fizgig.web import jobs
    return _call(jobs.read_log, job_id, offset)


@app.post("/api/jobs/{job_id}/pause", response_model=JobOut)
def pause_job(job_id: str):
    from fizgig.web import jobs
    return _call(jobs.pause, job_id)


@app.post("/api/jobs/{job_id}/resume", response_model=JobOut, responses={409: {"model": ConflictOut}})
def resume_job(job_id: str, body: ConfirmIn | None = None):
    from fizgig.web import jobs
    confirm = list(body.confirm) if body is not None else []
    return _call(jobs.resume, job_id, confirm)


@app.post("/api/jobs/{job_id}/stop", response_model=JobOut)
def stop_job(job_id: str):
    from fizgig.web import jobs
    return _call(jobs.stop, job_id)


@app.post("/api/jobs/{job_id}/override", response_model=OverrideOut)
def override_job(job_id: str, body: OverrideIn):
    from fizgig.web import jobs
    return _call(jobs.write_override, job_id, body.prompt, body.seed, body.width, body.height)


@app.get("/api/jobs/{job_id}/samples", response_model=SampleList)
def list_samples(job_id: str):
    from fizgig.web import jobs
    return _call(jobs.list_samples, job_id)


@app.get("/api/jobs/{job_id}/samples/{name}")
def read_sample(job_id: str, name: str):
    from fizgig.web import jobs
    found = _call(jobs.sample_path, job_id, name)
    if isinstance(found, JSONResponse):
        return found
    return FileResponse(found)


@app.get("/api/system", response_model=SystemOut)
def system():
    from fizgig.web.system import stats
    return stats()


def _event_round(seen_status, seen_samples, first):
    """One SSE snapshot. ``once=1`` on the route returns a single round and closes."""
    from fizgig.web import jobs
    from fizgig.web.system import stats

    lines = []
    try:
        current = jobs.list_jobs()
    except Exception:
        current = []
    try:
        from fizgig.web.queue import observe
        observe(current)
        current = jobs.list_jobs()
    except Exception:
        pass
    for job in current:
        lines.append(f"event: job\ndata: {json.dumps(job)}\n\n")
        progress = {
            "id": job["id"], "stage": job["stage"], "step": job["step"],
            "total": job["total"], "loss": job["loss"],
        }
        lines.append(f"event: progress\ndata: {json.dumps(progress)}\n\n")
        previous = seen_status.get(job["id"])
        seen_status[job["id"]] = job["status"]
        if not first and previous != job["status"] and job["status"] in {"done", "failed", "paused"}:
            kind = {"done": "finished", "failed": "failed", "paused": "paused"}[job["status"]]
            notice = {"id": job["id"], "kind": kind, "message": f"{job['family']} {kind}"}
            lines.append(f"event: notice\ndata: {json.dumps(notice)}\n\n")
        try:
            listed = jobs.list_samples(job["id"]).get("samples") or []
        except Exception:
            listed = []
        known = seen_samples.setdefault(job["id"], set())
        for sample in listed:
            if sample["name"] in known:
                continue
            known.add(sample["name"])
            if not first:
                body = {"id": job["id"], "name": sample["name"], "url": sample["url"]}
                lines.append(f"event: sample\ndata: {json.dumps(body)}\n\n")
    lines.append(f"event: system\ndata: {json.dumps(stats())}\n\n")
    try:
        from fizgig.web.engine_host import drain
        for event in drain():
            lines.append(f"event: engine\ndata: {json.dumps(event)}\n\n")
    except Exception:
        pass
    return lines


@app.get("/api/events")
async def events(request: Request, once: int = 0):
    """Server-sent events: job, progress, sample, system, notice, engine.

    ``once=1`` sends a single round and closes. The page leaves it off and keeps the stream open.
    """
    async def stream():
        seen_status = {}
        seen_samples = {}
        first = True
        while True:
            for line in _event_round(seen_status, seen_samples, first):
                yield line
            first = False
            if once:
                return
            await asyncio.sleep(0.8)
            if await request.is_disconnected():
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/ping")
def ping():
    """No training route exists yet. This POST exists so the Origin check has a request to reject."""
    return {"ok": True}


@app.get("/api/queue", response_model=QueueOut)
def read_queue():
    from fizgig.web.queue import list_items
    return list_items()


@app.post("/api/queue", response_model=QueueItem)
def add_queue(body: JobCreate):
    from fizgig.web.queue import add
    return _call(add, body.family, body.values, body.context)


@app.post("/api/queue/order", response_model=QueueOut)
def order_queue(body: OrderIn):
    from fizgig.web.queue import reorder
    return _call(reorder, body.ids)


@app.delete("/api/queue/{item_id}", response_model=QueueOut)
def delete_queue_item(item_id: str):
    from fizgig.web.queue import remove
    return _call(remove, item_id)


@app.post("/api/queue/advance", response_model=JobOut, responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def advance_queue(body: ConfirmIn | None = None):
    from fizgig.web.queue import advance
    return _call(advance, [] if body is None else body.confirm)


@app.post("/api/queue/import", response_model=QueueImport)
def import_queue():
    from fizgig.web.queue import import_desktop
    return _call(import_desktop)


@app.get("/api/history", response_model=HistoryOut)
def read_history():
    from fizgig.web.jobs import history
    return {"jobs": history()}


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    from fastapi import Response
    from fizgig.web.jobs import delete_record

    result = _call(delete_record, job_id)
    if isinstance(result, JSONResponse):
        return result
    return Response(status_code=204)


@app.get("/api/prefs")
def read_prefs():
    from fizgig.web.prefs import view
    return view()


@app.put("/api/prefs")
def write_prefs(body: PrefsIn):
    from fizgig.web.prefs import save
    return _call(save, body.values)


@app.get("/api/fs")
def read_fs(path: str = ""):
    from fizgig.web.fs import listing
    return _call(listing, path)


@app.post("/api/upload")
def upload_files(
    dest: str = Form(""),
    overwrite: str = Form(""),
    files: list[UploadFile] | None = File(None),
    archive: UploadFile | None = File(None),
):
    from fizgig.web.fs import upload
    return _call(upload, dest, files or [], archive, overwrite == "1")


@app.get("/api/download")
def download_lora(path: str):
    from fizgig.web.fs import lora_file

    found = _call(lora_file, path)
    if isinstance(found, JSONResponse):
        return found
    return FileResponse(found, filename=found.name)


@app.get("/api/start", response_model=StartOut)
def read_start():
    from fizgig.web.start import current
    return current()


@app.put("/api/start", response_model=StartOut)
def write_start(body: StartIn):
    from fizgig.web.start import set_folder
    return _call(set_folder, body.folder)


@app.get("/api/captions/form")
def caption_form():
    from fizgig.web.captions import form
    return form()


@app.post("/api/captions/jobs", response_model=JobOut, responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def caption_job(body: CaptionIn):
    from fizgig.web.captions import launch
    return _call(launch, body.model_dump())


@app.post("/api/captions/static")
def caption_static(body: CaptionIn):
    from fizgig.web.captions import static
    return _call(static, body.model_dump())


@app.get("/api/captions")
def caption_list(folder: str = "", q: str = ""):
    from fizgig.web.captions import listing
    return _call(listing, folder, q)


@app.get("/api/captions/image")
def caption_image(folder: str, name: str):
    from fizgig.web.captions import image_file

    found = _call(image_file, folder, name)
    if isinstance(found, JSONResponse):
        return found
    return FileResponse(found)


@app.put("/api/captions")
def caption_save(body: CaptionIn):
    from fizgig.web.captions import save_caption
    return _call(save_caption, body.folder, body.name, body.text)


@app.get("/api/prep/form")
def prep_form():
    from fizgig.web.image_prep import form
    return form()


@app.post("/api/prep/jobs", response_model=JobOut, responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def prep_job(body: PrepIn):
    from fizgig.web.image_prep import launch
    return _call(launch, body.model_dump())


@app.get("/api/samples/form")
def samples_form(family: str):
    from fizgig.families.registry import get as get_family
    from fizgig.web.samples import form as samples_form_for

    desc = get_family(family)
    if desc is None:
        raise HTTPException(status_code=404, detail="unknown family")
    return samples_form_for(desc)


@app.get("/api/profile/form")
def profile_form(family: str = ""):
    from fizgig.web.profile import form as profile_form_for
    return _call(profile_form_for, family)


@app.post("/api/profile/jobs", response_model=JobOut, responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def profile_job(body: dict = Body(...)):
    from fizgig.web.profile import launch
    return _call(launch, body)


@app.get("/api/profiles")
def profile_reports():
    from fizgig.web.profile import reports
    return reports()


@app.get("/api/profiles/file")
def profile_report(path: str):
    from fizgig.web.profile import report_file

    found = _call(report_file, path)
    if isinstance(found, JSONResponse):
        return found
    return FileResponse(found, media_type="text/html")


@app.get("/api/extract/form")
def extract_form(family: str = ""):
    from fizgig.web.extract import form as extract_form_for
    return _call(extract_form_for, family)


@app.post("/api/extract/jobs", response_model=JobOut, responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def extract_job(body: dict = Body(...)):
    from fizgig.web.extract import launch
    return _call(launch, body)


@app.get("/api/metadata")
def metadata_read(path: str):
    from fizgig.web.metadata import read
    return _call(read, path)


@app.put("/api/metadata")
def metadata_write(body: dict = Body(...)):
    from fizgig.web.metadata import save
    return _call(save, body)


@app.post("/api/profile/engine", responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def profile_engine(body: dict = Body(...)):
    from fizgig.web.profile import start_engine
    return _call(start_engine, body)


@app.get("/api/profile/engine")
def profile_engine_status():
    from fizgig.web.profile import engine_view
    return engine_view()


@app.post("/api/profile/repair", responses={422: {"model": ProblemsOut}})
def profile_open_repair():
    from fizgig.web.profile import open_repair
    return _call(open_repair)


@app.get("/api/repair/form")
def repair_form(family: str = ""):
    from fizgig.web.repair import form as repair_form_for
    return _call(repair_form_for, family)


@app.post("/api/repair/load", responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def repair_load(body: dict = Body(...)):
    from fizgig.web.repair import load as repair_load_for
    return _call(repair_load_for, body)


@app.post("/api/repair/render", responses={422: {"model": ProblemsOut}})
def repair_render(body: dict = Body(...)):
    from fizgig.web.repair import render as repair_render_for
    return _call(repair_render_for, body)


@app.post("/api/repair/unload")
def repair_unload():
    from fizgig.web.repair import unload as repair_unload_for
    return _call(repair_unload_for)


@app.get("/api/repair/status")
def repair_status():
    from fizgig.web.repair import status as repair_status_for
    return repair_status_for()


@app.get("/api/repair/presets")
def repair_presets(family: str):
    from fizgig.web.repair import presets as repair_presets_for
    return _call(repair_presets_for, family)


@app.put("/api/repair/presets", responses={409: {"model": ConflictOut}, 422: {"model": ProblemsOut}})
def repair_save_preset(body: dict = Body(...)):
    from fizgig.web.repair import save_preset
    return _call(save_preset, body)


@app.get("/api/repair/presets/file", responses={404: {"model": ConflictOut}})
def repair_read_preset(family: str, name: str):
    from fizgig.web.repair import read_preset
    return _call(read_preset, family, name)


@app.post("/api/repair/bake", responses={422: {"model": ProblemsOut}})
def repair_bake(body: dict = Body(...)):
    from fizgig.web.repair import bake as repair_bake_for
    return _call(repair_bake_for, body)


@app.post("/api/repair/metrics", responses={422: {"model": ProblemsOut}})
def repair_metrics(body: dict = Body(...)):
    from fizgig.web.repair import metrics as repair_metrics_for
    return _call(repair_metrics_for, body)


@app.get("/api/engine/status")
def engine_status():
    from fizgig.web.repair import status as repair_status_for
    return repair_status_for()


@app.post("/api/engine/unload")
def engine_unload():
    from fizgig.web.repair import unload as repair_unload_for
    return _call(repair_unload_for)


@app.get("/api/engine/file")
def engine_media(path: str):
    from fizgig.web.fs import engine_file

    found = _call(engine_file, path)
    if isinstance(found, JSONResponse):
        return found
    return FileResponse(found)


_dist = _REPO / "webui" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")


def serve(host: str = LOOPBACK, port: int = PORT) -> None:
    if host != LOOPBACK:
        raise SystemExit("refusing to listen on a non-loopback address")
    from fizgig.web.jobs import reconcile
    reconcile()
    import uvicorn
    uvicorn.run(app, host=host, port=port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m fizgig.web")
    parser.parse_args(argv)
    serve()
