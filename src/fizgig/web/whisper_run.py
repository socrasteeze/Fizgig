"""One Whisper pass. Started as ``python -m fizgig.web.whisper_run``.

Not imported by the server. The model load stays in this process.
"""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


def _whisper_degenerate(text, span):
    """gizmo.py Gizmo._whisper_degenerate."""
    words = text.split()
    if len(text) > max(80, span * 30):
        return True
    if len(words) >= 10 and len(set(w.lower() for w in words)) / len(words) < 0.4:
        return True
    return False


def _local_model():
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(
            "openai/whisper-base", local_files_only=True,
            allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors"],
        )
    except Exception:
        return None


def _hear(pipe, sample, language):
    kw = {"generate_kwargs": {"language": language, "task": "transcribe"}} if language else {}
    return (pipe(dict(sample), **kw).get("text") or "").strip()


def main(argv: list[str] | None = None) -> int:
    from fizgig.web.gizmo import build_whisper_extract_command, find_ffmpeg

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--span", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("ffmpeg was not found", flush=True)
        return 1
    span = float(args.span)
    handle, wav = tempfile.mkstemp(prefix="fizgig-whisper-", suffix=".wav")
    os.close(handle)
    try:
        cmd = build_whisper_extract_command(ffmpeg, args.source, wav, float(args.start), span)
        proc = subprocess_run(cmd)
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "replace")[-300:]
            print(err or "could not extract the segment", flush=True)
            return 1
        from transformers import pipeline
        import numpy as np
        import wave
        model = _local_model() or "openai/whisper-base"
        pipe = pipeline("automatic-speech-recognition", model=model, device=-1)
        with wave.open(wav) as raw_wav:
            raw = np.frombuffer(raw_wav.readframes(raw_wav.getnframes()), dtype=np.int16)
        sample = {"raw": raw.astype(np.float32) / 32768.0, "sampling_rate": 16000}
        language = None if args.language == "auto" else args.language
        text = _hear(pipe, sample, language)
        if language is None and _whisper_degenerate(text, span):
            text = _hear(pipe, sample, "english")
        if not text or _whisper_degenerate(text, span):
            return 1
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        line = f'saying "{text}"'
        output.write_text(line, encoding="utf-8")
        print("CAPTION: " + line, flush=True)
        print("PROGRESS: 1 1", flush=True)
        return 0
    except Exception as exc:
        print(f"Whisper could not run: {exc}", flush=True)
        return 1
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def subprocess_run(cmd):
    import subprocess
    from fizgig.web import procs
    return subprocess.run(cmd, capture_output=True, creationflags=procs.creationflags())


if __name__ == "__main__":
    raise SystemExit(main())
