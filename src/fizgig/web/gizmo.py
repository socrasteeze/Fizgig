"""Gizmo clip, voice, scene, and transcription jobs.

The math is copied from ``gizmo.py``. That module builds a Tk window, so the
server does not import it. Each copied function names the desktop original.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from fizgig.web import procs
from fizgig.web.fs import _limit, _read_limited, _safe_leaf, dataset_roots, resolve_dir, resolve_file
from fizgig.web.jobs import JobError

# gizmo.py clip and voice spec.
FPS = 24
GRID_FRAMES = (5, 22, 39, 56, 73, 90, 107, 124)
LATENT_FRAMES = {frames: 5 * n + 2 for n, frames in enumerate(GRID_FRAMES)}
SIZE_STEP = 32
AUDIO_SAMPLE_RATE = 32000
AUDIO_CHANNELS = 2
MUTE_SUFFIX = "_mute"
AUDIO_HOP = 800
AUDIO_GRID_FRAMES = (22, 39, 56, 73, 90, 107, 124)
SCENE_SENSITIVITIES = (
    ("Normal — most footage", 0.30),
    ("More cuts — fast-cut or handheld footage", 0.22),
    ("Fewer cuts — slow or static footage", 0.40),
)
AUTOCHOP_MAX_SEGMENTS = 400
WHISPER_LANGUAGES = [
    "Auto detect", "English", "French", "German", "Spanish", "Italian",
    "Portuguese", "Dutch", "Polish", "Welsh", "Russian", "Ukrainian",
    "Japanese", "Chinese", "Korean", "Arabic", "Hindi",
]

_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a"}
_MEDIA_EXTS = _VIDEO_EXTS | _AUDIO_EXTS
_RECORD_EXTS = {".webm", ".ogg", ".wav", ".m4a", ".mp4", ".mp3", ".flac"}
_FAKE_PROBE = {
    "fps": 24, "width": 64, "height": 64, "duration": 10, "has_audio": False,
    "sample_rate": None, "channels": None, "vcodec": None, "sar": 1.0,
    "rotation": 0, "display_width": 64, "display_height": 64,
}

# gizmo.py _SHOWINFO_TIME
_SHOWINFO_TIME = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")
# gizmo.py _PROGRESS_TIME
_PROGRESS_TIME = re.compile(r"\btime=(\d+):(\d+):(\d+(?:\.\d+)?)")


def audio_latents_for(frames):
    """gizmo.py audio_latents_for."""
    return int(round(frames / FPS * 40))


def hop_exact_samples(frames):
    """gizmo.py hop_exact_samples."""
    return audio_latents_for(frames) * AUDIO_HOP


def find_ffmpeg():
    """gizmo.py find_ffmpeg."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    import shutil
    return shutil.which("ffmpeg")


def probe_source(ffmpeg, path):
    """gizmo.py probe_source."""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path],
        capture_output=True, text=True, creationflags=procs.creationflags(),
    )
    out = proc.stderr or ""
    info = {"fps": None, "width": None, "height": None, "duration": None,
            "has_audio": False, "sample_rate": None, "channels": None, "vcodec": None,
            "sar": 1.0, "rotation": 0, "display_width": None, "display_height": None}

    matched = re.search(r"Stream #\d+:\d+.*?: Video: (\w+).*?, (\d{2,5})x(\d{2,5})", out, re.S)
    if matched:
        info["vcodec"] = matched.group(1)
        info["width"], info["height"] = int(matched.group(2)), int(matched.group(3))
    matched = re.search(r"SAR (\d+):(\d+)", out)
    if matched and int(matched.group(2)):
        info["sar"] = int(matched.group(1)) / int(matched.group(2))
    matched = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", out)
    if matched:
        info["rotation"] = int(round(float(matched.group(1)))) % 360
    matched = re.search(r"(\d+(?:\.\d+)?)\s+fps", out)
    if matched:
        info["fps"] = float(matched.group(1))
    matched = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if matched:
        info["duration"] = int(matched.group(1)) * 3600 + int(matched.group(2)) * 60 + float(matched.group(3))
    matched = re.search(r"Stream #\d+:\d+.*?: Audio: [^,]+, (\d+) Hz, (\w+)", out)
    if matched:
        info["has_audio"] = True
        info["sample_rate"] = int(matched.group(1))
        info["channels"] = {"mono": 1, "stereo": 2}.get(matched.group(2))

    if not info["width"] or not info["fps"]:
        raise ValueError(f"{os.path.basename(path)} has no video stream Gizmo can read.")
    dw = max(2, int(round(info["width"] * info["sar"])))
    dh = info["height"]
    if info["rotation"] in (90, 270):
        dw, dh = dh, dw
    info["display_width"], info["display_height"] = dw, dh
    return info


def snap(value):
    """gizmo.py snap."""
    return max(SIZE_STEP, int(value) // SIZE_STEP * SIZE_STEP)


def target_size(src_w, src_h, megapixels):
    """gizmo.py target_size."""
    aspect = src_w / src_h
    max_w, max_h = snap(src_w), snap(src_h)
    want_area = min(megapixels * 1_000_000, max_w * max_h)
    best = None
    for height in range(SIZE_STEP, max_h + SIZE_STEP, SIZE_STEP):
        ideal_w = height * aspect
        for width in {snap(ideal_w), snap(ideal_w) + SIZE_STEP}:
            if width < SIZE_STEP or width > max_w:
                continue
            err = abs((width / height) - aspect) / aspect
            cost = abs(width * height - want_area) / want_area + 3.0 * err
            if best is None or cost < best[0]:
                best = (cost, (width, height))
    return best[1] if best else (max_w, max_h)


def build_export_command(ffmpeg, src, dst, start_s, frames, width, height,
                         keep_every=None, with_audio=True, crop=None, sar=1.0):
    """gizmo.py build_export_command."""
    if keep_every:
        vf = f"select='not(mod(n\\,{keep_every}))',setpts=N/({FPS}*TB)"
    else:
        vf = f"fps={FPS}"
    if crop:
        cx, cy, cw, ch = crop
        if abs(sar - 1.0) > 1e-3:
            vf += ",scale=iw*sar:ih:flags=lanczos,setsar=1"
        vf += f",crop={cw}:{ch}:{cx}:{cy}"
    vf += (f",scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos"
           f",crop={width}:{height},setsar=1")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{max(0.0, start_s):.3f}", "-i", src,
           "-vf", vf, "-frames:v", str(frames),
           "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-r", str(FPS)]
    if with_audio:
        cmd += ["-af", f"aresample={AUDIO_SAMPLE_RATE},atrim=0:{frames / FPS:.6f},"
                       f"asetpts=PTS-STARTPTS",
                "-ac", str(AUDIO_CHANNELS), "-ar", str(AUDIO_SAMPLE_RATE),
                "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    return cmd + ["-movflags", "+faststart", dst]


def output_name(src_path, out_dir, muted, claimed=()):
    """gizmo.py output_name."""
    stem = os.path.splitext(os.path.basename(src_path))[0]
    while stem.lower().endswith(MUTE_SUFFIX):
        stem = stem[:-len(MUTE_SUFFIX)]
    stem = re.sub(r"[^\w\-]+", "_", stem).strip("_") or "clip"
    for i in range(1, 1000):
        taken = any(os.path.exists(os.path.join(out_dir, f"{stem}_{i:02d}{suffix}.mp4"))
                    or f"{stem}_{i:02d}{suffix}.mp4" in claimed
                    for suffix in ("", MUTE_SUFFIX))
        if not taken:
            return os.path.join(out_dir, f"{stem}_{i:02d}{MUTE_SUFFIX if muted else ''}.mp4")
    raise RuntimeError("1000 clips from one source — give the output folder a clean start.")


def voice_output_name(src_path, out_dir, claimed=()):
    """gizmo.py voice_output_name."""
    stem = os.path.splitext(os.path.basename(src_path))[0]
    stem = re.sub(r"[^\w\-]+", "_", stem).strip("_") or "voice"
    for i in range(1, 1000):
        name = f"{stem}_{i:02d}.wav"
        if not os.path.exists(os.path.join(out_dir, name)) and name not in claimed:
            return os.path.join(out_dir, name)
    raise RuntimeError("1000 segments from one recording — give the output folder a clean start.")


def build_scene_scan_command(ffmpeg, src, threshold):
    """gizmo.py build_scene_scan_command."""
    vf = f"scale=320:-2:flags=bilinear,select=gt(scene\\,{threshold:g}),showinfo"
    return [ffmpeg, "-hide_banner", "-i", src, "-vf", vf, "-an", "-f", "null", "-"]


def parse_scene_time(stderr_line):
    """gizmo.py parse_scene_time."""
    if "pts_time" not in stderr_line:
        return None
    matched = _SHOWINFO_TIME.search(stderr_line)
    return float(matched.group(1)) if matched else None


def parse_progress_time(stderr_line):
    """gizmo.py parse_progress_time."""
    matched = _PROGRESS_TIME.search(stderr_line)
    if not matched:
        return None
    return int(matched.group(1)) * 3600 + int(matched.group(2)) * 60 + float(matched.group(3))


def plan_autochop(cut_times, duration, span_s, fill=True):
    """gizmo.py plan_autochop."""
    bounds = [0.0] + sorted(t for t in cut_times if 0.0 < t < duration) + [duration]
    starts = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a + 1e-6 < span_s:
            continue
        if fill:
            t = a
            while t + span_s <= b + 1e-6:
                starts.append(t)
                t += span_s
        else:
            starts.append(a)
    return starts


def build_voice_export_command(ffmpeg, src, dst, start, frames):
    """gizmo.py Gizmo._audio_export_worker."""
    n = hop_exact_samples(frames)
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start:.3f}", "-i", src, "-vn",
            "-af", (f"aresample={AUDIO_SAMPLE_RATE},atrim=end_sample={n},"
                    f"apad=whole_len={n}"),
            "-ac", str(AUDIO_CHANNELS), "-ar", str(AUDIO_SAMPLE_RATE),
            "-c:a", "pcm_s16le", dst]


def build_recording_command(ffmpeg, src, dst):
    """Recording container to 32 kHz stereo pcm_s16le."""
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-vn", "-ac", "2", "-ar", "32000", "-c:a", "pcm_s16le", dst]


def build_whisper_extract_command(ffmpeg, src, wav, start, span):
    """gizmo.py Gizmo._whisper_worker extract argv."""
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", src,
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav]


def _fake_ffmpeg() -> bool:
    return os.environ.get("FIZGIG_WEB_FAKE_FFMPEG", "").strip() == "1"


def _media(text: str) -> Path:
    found = resolve_file(str(text or ""), "")
    if found.suffix.lower() not in _MEDIA_EXTS:
        raise JobError(422, {"problems": [f"not a media file: {found.name}"]})
    return found


def _number(value, label: str) -> float:
    if isinstance(value, bool) or value is None or value == "":
        raise JobError(422, {"problems": [f"{label} is required"]})
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise JobError(422, {"problems": [f"{label} is required"]}) from exc


def _grid(value, allowed) -> int:
    if isinstance(value, bool) or value is None or value == "":
        raise JobError(422, {"problems": ["frames must be a grid length"]})
    try:
        frames = int(value)
    except (TypeError, ValueError) as exc:
        raise JobError(422, {"problems": ["frames must be a grid length"]}) from exc
    if frames not in allowed:
        raise JobError(422, {"problems": ["frames must be a grid length"]})
    return frames


def _upload(dest, file, exts: set[str]):
    if file is None or not (getattr(file, "filename", None) or ""):
        raise JobError(422, {"problems": ["nothing to upload"]})
    folder = resolve_dir(str(dest or ""), dataset_roots())
    leaf = _safe_leaf(file.filename or "")
    if Path(leaf).suffix.lower() not in exts:
        raise JobError(422, {"problems": [f"not a media file: {leaf}"]})
    data = _read_limited(file, _limit(), 0)
    return folder, leaf, data


def form() -> dict:
    return {
        "fps": FPS,
        "grid_frames": list(GRID_FRAMES),
        "audio_grid_frames": list(AUDIO_GRID_FRAMES),
        "scene_sensitivities": [
            {"label": label, "threshold": threshold}
            for label, threshold in SCENE_SENSITIVITIES
        ],
        "threshold": SCENE_SENSITIVITIES[0][1],
        "languages": list(WHISPER_LANGUAGES),
        "language": "Auto detect",
        "mute_suffix": MUTE_SUFFIX,
    }


def probe(path: str) -> dict:
    found = _media(path)
    if _fake_ffmpeg():
        return dict(_FAKE_PROBE)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise JobError(422, {"problems": ["ffmpeg was not found"]})
    try:
        return probe_source(ffmpeg, str(found))
    except ValueError as exc:
        raise JobError(422, {"problems": [str(exc)]}) from exc


def next_name(source: str, dataset: str, muted: bool, kind: str) -> dict:
    src = _media(source)
    folder = resolve_dir(str(dataset or ""), dataset_roots())
    if kind == "voice":
        path = voice_output_name(str(src), str(folder))
    else:
        path = output_name(str(src), str(folder), bool(muted))
    return {"name": os.path.basename(path), "path": path}


def upload_source(dest, file) -> dict:
    folder, leaf, data = _upload(dest, file, _MEDIA_EXTS)
    target = folder / leaf
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return {"written": [leaf], "folder": str(folder)}


def save_recording(dest, file) -> dict:
    folder, leaf, data = _upload(dest, file, _RECORD_EXTS)
    dst = voice_output_name(leaf, str(folder))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    handle, src = tempfile.mkstemp(prefix="rec-", suffix=Path(leaf).suffix, dir=str(folder))
    os.close(handle)
    ffmpeg = find_ffmpeg()
    command = build_recording_command(ffmpeg, src, dst)
    try:
        Path(src).write_bytes(data)
        if _fake_ffmpeg():
            Path(dst).write_bytes(b"fake-wav")
        else:
            if not ffmpeg:
                raise JobError(422, {"problems": ["ffmpeg was not found"]})
            proc = subprocess.run(command, capture_output=True, creationflags=procs.creationflags())
            if proc.returncode != 0 or not os.path.exists(dst):
                err = (proc.stderr or b"").decode("utf-8", "replace")[-300:]
                raise JobError(422, {"problems": [err or "could not convert the recording"]})
    finally:
        try:
            os.remove(src)
        except OSError:
            pass
    return {"path": dst, "command": command, "folder": str(folder)}


def _clip_info(source: Path, clips: list) -> dict:
    needs_size = False
    for clip in clips:
        if not isinstance(clip, dict):
            raise JobError(422, {"problems": ["clips are required"]})
        if clip.get("width") in (None, "") or clip.get("height") in (None, ""):
            needs_size = True
    try:
        return probe(str(source))
    except JobError:
        if needs_size:
            raise
        return {"has_audio": False, "sar": 1.0, "display_width": None, "display_height": None}


def _crop(value):
    if not value:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise JobError(422, {"problems": ["crop must be x, y, w, h"]})
    return tuple(int(part) for part in value)


def _keep(value):
    if value in (None, "", 0):
        return None
    return int(value)


def launch_clips(body: dict) -> dict:
    from fizgig.web import jobs

    body = body or {}
    source = _media(str(body.get("source") or ""))
    folder = resolve_dir(str(body.get("dataset") or ""), dataset_roots())
    clips = body.get("clips")
    if not isinstance(clips, list) or not clips:
        raise JobError(422, {"problems": ["clips are required"]})
    info = _clip_info(source, clips)
    ffmpeg = find_ffmpeg()
    claimed: list[str] = []
    stored = []
    commands = []
    for clip in clips:
        frames = _grid(clip.get("frames"), GRID_FRAMES)
        muted = bool(clip.get("muted"))
        if clip.get("width") in (None, "") or clip.get("height") in (None, ""):
            width, height = target_size(info["display_width"], info["display_height"], 99.0)
        else:
            width, height = int(clip["width"]), int(clip["height"])
        sar = clip.get("sar")
        sar = float(info.get("sar") or 1.0) if sar in (None, "") else float(sar)
        dst = output_name(str(source), str(folder), muted, claimed)
        claimed.append(os.path.basename(dst))
        caption = "" if clip.get("caption") is None else str(clip.get("caption"))
        cmd = build_export_command(
            ffmpeg, str(source), dst, _number(clip.get("start"), "start"), frames, width, height,
            keep_every=_keep(clip.get("keep_every")), with_audio=bool(info.get("has_audio")),
            crop=_crop(clip.get("crop")), sar=sar,
        )
        stored.append({
            "start": _number(clip.get("start"), "start"), "frames": frames, "muted": muted,
            "width": width, "height": height, "keep_every": _keep(clip.get("keep_every")),
            "crop": list(_crop(clip.get("crop")) or []) or None, "sar": sar,
            "caption": caption, "dst": dst, "with_audio": bool(info.get("has_audio")),
        })
        commands.append(cmd)
    values = {"mode": "cut", "source": str(source), "dataset": str(folder), "clips": stored}

    def stamp(job_folder, job):
        job["command"] = commands[0]
        job["commands"] = commands
        job["stage"] = "Gizmo"
        jobs.save(job_folder, job)

    return jobs.start_task("gizmo", "gizmo", values, str(folder), stamp)


def launch_voices(body: dict) -> dict:
    from fizgig.web import jobs

    body = body or {}
    source = _media(str(body.get("source") or ""))
    folder = resolve_dir(str(body.get("dataset") or ""), dataset_roots())
    segments = body.get("segments")
    if not isinstance(segments, list) or not segments:
        raise JobError(422, {"problems": ["segments are required"]})
    ffmpeg = find_ffmpeg()
    claimed: list[str] = []
    stored = []
    commands = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise JobError(422, {"problems": ["segments are required"]})
        caption = "" if segment.get("caption") is None else str(segment.get("caption"))
        if not caption.strip():
            raise JobError(422, {"problems": ["a voice segment needs a caption"]})
        frames = _grid(segment.get("frames"), AUDIO_GRID_FRAMES)
        start = _number(segment.get("start"), "start")
        dst = voice_output_name(str(source), str(folder), claimed)
        claimed.append(os.path.basename(dst))
        stored.append({"start": start, "frames": frames, "caption": caption, "dst": dst})
        commands.append(build_voice_export_command(ffmpeg, str(source), dst, start, frames))
    values = {"mode": "voice", "source": str(source), "dataset": str(folder), "segments": stored}

    def stamp(job_folder, job):
        job["command"] = commands[0]
        job["commands"] = commands
        job["stage"] = "Gizmo"
        jobs.save(job_folder, job)

    return jobs.start_task("gizmo", "gizmo", values, str(folder), stamp)


def launch_scan(body: dict) -> dict:
    from fizgig.web import jobs

    body = body or {}
    source = _media(str(body.get("source") or ""))
    if "duration" not in body or body.get("duration") in (None, ""):
        raise JobError(422, {"problems": ["duration is required"]})
    if "span_s" not in body or body.get("span_s") in (None, ""):
        raise JobError(422, {"problems": ["span_s is required"]})
    duration = _number(body.get("duration"), "duration")
    span_s = _number(body.get("span_s"), "span_s")
    if span_s <= 0:
        raise JobError(422, {"problems": ["span_s is required"]})
    raw_threshold = body.get("threshold")
    threshold = 0.30 if raw_threshold in (None, "") else _number(raw_threshold, "threshold")
    fill = True if body.get("fill") is None else bool(body.get("fill"))
    detector = body.get("detector") if isinstance(body.get("detector"), str) else ""
    ffmpeg = find_ffmpeg()
    command = build_scene_scan_command(ffmpeg, str(source), threshold)
    values = {
        "mode": "scan", "source": str(source), "threshold": threshold,
        "duration": duration, "span_s": span_s, "fill": fill, "detector": detector,
    }

    def stamp(job_folder, job):
        job["command"] = command
        job["stage"] = "Gizmo"
        jobs.save(job_folder, job)

    return jobs.start_task("gizmo", "gizmo", values, str(source.parent), stamp)


def _whisper_lang(raw) -> str:
    language = "Auto detect" if raw in (None, "") else str(raw)
    if language not in WHISPER_LANGUAGES:
        raise JobError(422, {"problems": ["unknown language"]})
    if language == "Auto detect":
        return "auto"
    return language.lower()


def _whisper_command(source: Path, start: float, span: float, language: str, output: Path) -> list[str]:
    flags = ["--source", str(source), "--start", f"{start:.3f}", "--span", f"{span:.3f}",
             "--language", language, "--output", str(output)]
    fake = os.environ.get("FIZGIG_WEB_FAKE_WHISPER", "").strip()
    if fake:
        return [sys.executable, fake, *flags]
    return [sys.executable, "-m", "fizgig.web.whisper_run", *flags]


def _txt_output(text: str) -> Path:
    raw = (text or "").strip()
    path = Path(raw)
    if path.suffix.lower() != ".txt":
        raise JobError(422, {"problems": ["output must be a .txt file"]})
    parent = resolve_dir(str(path.parent), dataset_roots())
    return parent / _safe_leaf(path.name)


def launch_transcribe(body: dict) -> dict:
    from fizgig.web import jobs

    body = body or {}
    source = _media(str(body.get("source") or ""))
    output = _txt_output(str(body.get("output") or ""))
    start = _number(body.get("start"), "start")
    span = _number(body.get("span"), "span")
    if span <= 0:
        raise JobError(422, {"problems": ["span is required"]})
    language = _whisper_lang(body.get("language"))
    command = _whisper_command(source, start, span, language, output)
    values = {
        "source": str(source), "start": start, "span": span,
        "language": language, "output": str(output),
    }

    def stamp(job_folder, job):
        job["command"] = command
        job["stage"] = "Whisper"
        jobs.save(job_folder, job)

    return jobs.start_task("whisper", "whisper", values, str(output.parent), stamp)


def _append(folder: Path, text: str) -> None:
    with (folder / "log.txt").open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")


def _stopped(folder: Path) -> bool:
    return (folder / "STOP").is_file()


def _export(folder: Path, job: dict, rows: list, finish) -> None:
    commands = list(job.get("commands") or [])
    if len(commands) != len(rows):
        finish(folder, job, "failed", 1)
        return
    for row, cmd in zip(rows, commands):
        if _stopped(folder):
            finish(folder, job, "stopped", 0)
            return
        dst = str(row.get("dst") or "")
        if not dst:
            finish(folder, job, "failed", 1)
            return
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        if _fake_ffmpeg():
            Path(dst).write_bytes(b"fake")
        else:
            proc = subprocess.run(list(cmd), capture_output=True, creationflags=procs.creationflags())
            if _stopped(folder):
                finish(folder, job, "stopped", proc.returncode or 0)
                return
            if proc.returncode != 0:
                _append(folder, (proc.stderr or b"").decode("utf-8", "replace")[-500:])
                finish(folder, job, "failed", proc.returncode)
                return
        caption = row.get("caption") or ""
        if caption:
            Path(os.path.splitext(dst)[0] + ".txt").write_text(str(caption), encoding="utf-8")
    if _stopped(folder):
        finish(folder, job, "stopped", 0)
        return
    finish(folder, job, "done", 0)


def _scan(folder: Path, job: dict, finish) -> None:
    values = job.get("values") or {}
    if _stopped(folder):
        finish(folder, job, "stopped", 0)
        return
    if os.environ.get("FIZGIG_WEB_FAKE_SCENES", "").strip() == "1":
        text = str(values.get("detector") or "")
    else:
        # showinfo is written to stderr; merge it so the cut list is on stdout.
        proc = subprocess.run(
            list(job.get("command") or []),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", creationflags=procs.creationflags(),
        )
        if _stopped(folder):
            finish(folder, job, "stopped", proc.returncode or 0)
            return
        if proc.returncode != 0:
            _append(folder, proc.stdout or "")
            finish(folder, job, "failed", proc.returncode)
            return
        text = proc.stdout or ""
    times = []
    for line in text.splitlines():
        found = parse_scene_time(line)
        if found is not None:
            times.append(found)
    starts = plan_autochop(
        times, float(values.get("duration") or 0), float(values.get("span_s") or 0),
        bool(values.get("fill", True)),
    )[:AUTOCHOP_MAX_SEGMENTS]
    (folder / "scans.json").write_text(json.dumps({"starts": starts}), encoding="utf-8")
    _append(folder, "STARTS: " + " ".join(f"{item:.6f}" for item in starts))
    finish(folder, job, "done", 0)


def run_job(folder: Path, job: dict) -> None:
    from fizgig.web.runner import _begin, _finish

    if not _begin(folder, job):
        return
    values = job.get("values") or {}
    mode = str(values.get("mode") or "")
    if mode == "scan":
        _scan(folder, job, _finish)
    elif mode == "voice":
        _export(folder, job, list(values.get("segments") or []), _finish)
    elif mode == "cut":
        _export(folder, job, list(values.get("clips") or []), _finish)
    else:
        _finish(folder, job, "failed", 1)


def run_whisper(folder: Path, job: dict) -> None:
    from fizgig.web.runner import _run_tool

    _run_tool(folder, job, list(job.get("command") or []))
