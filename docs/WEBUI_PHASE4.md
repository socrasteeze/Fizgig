# Web UI phase 4

Phase 4 is Gizmo and the checkpoint-to-LoRA converter. Phase 3 jobs, the detached runner, the GPU lock, SSE, root-limited paths, and the generated API types stay as they are. The server does not import `gizmo.py` or `diff_to_lora_gui.py`. Both build a Tk window, and the server has to run headless.

The pure helpers the page needs are copied into `src/fizgig/web/gizmo.py` and `src/fizgig/web/convert.py`. Each copied function names the desktop function it mirrors. `checks/test_web_mirrors.py` hashes those desktop functions. A cut, a voice export, a scene scan, a transcription, and a conversion are jobs on the same runner and the same GPU lock as training. Pause, resume, and sample override still refuse anything that is not training. These jobs do not advance the training queue.

Every route is behind the existing Host check. Every POST is behind the existing Origin check. A path outside the configured roots, a `..` segment, or a link below the root is 403. Writes land in a dataset root. The converter writes in the LoRA output directory.

ffmpeg is a short tool. A launch from the server passes `procs.creationflags()`. A launch from the runner inherits the runner's hidden console (`creationflags=0` on that `Popen`, the same as the other tool jobs). `FIZGIG_WEB_FAKE_FFMPEG=1` records the argv and writes a placeholder file. It does not start ffmpeg.

## Gizmo

`GET /api/gizmo/form` is the clip spec the page needs: `fps` 24, `grid_frames` `(5, 22, 39, 56, 73, 90, 107, 124)`, `audio_grid_frames` `(22, 39, 56, 73, 90, 107, 124)`, `scene_sensitivities` (the three `SCENE_SENSITIVITIES` labels and thresholds, default `0.30`), `languages` (`WHISPER_LANGUAGES`, default `Auto detect`), and `mute_suffix` `_mute`.

`GET /api/gizmo/probe?path=` runs `probe_source` on one video or audio file inside the roots. The body is the desktop dict: `fps`, `width`, `height`, `duration`, `has_audio`, `sample_rate`, `channels`, `vcodec`, `sar`, `rotation`, `display_width`, `display_height`. No ffmpeg on PATH is 422.

`GET /api/gizmo/media?path=` returns that file with `FileResponse`, which answers HTTP Range. A `Range: bytes=0-3` request is 206 with `Content-Range: bytes 0-3/<size>` and those four bytes. A path outside the roots is 403. The page plays it in an HTML `<video>` element. In and out are source frames: the page snaps `currentTime` to `frame / fps`. The clip length is one `grid_frames` value. `start_s` sent to the cut is `in_frame / fps`, the same ratio `_planned_job` uses.

`POST /api/gizmo/upload` stores a source in a dataset folder. The multipart fields are `dest` and `file`. Extensions are `.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`, `.avi`, `.wav`, `.mp3`, `.flac`, `.m4a`. The size limit is `fs._limit` (`FIZGIG_WEB_UPLOAD_MAX`, default 64 MiB). Over the limit is 413. The leaf is the safe file name.

`POST /api/gizmo/recordings` accepts one MediaRecorder blob (`file`) into `dest`. The browser asks for the microphone only when Record is clicked. The same size limit applies. The blob is not raw PCM, so the ffmpeg input is a container, and the output is the desktop take: 32 kHz, stereo, `pcm_s16le`. The argv is `build_recording_command`:

```
ffmpeg -y -hide_banner -loglevel error -i SRC -vn -ac 2 -ar 32000 -c:a pcm_s16le DST
```

`DST` is `voice_output_name` of the upload in `dest`. The response is `path` and `command`. Under `FIZGIG_WEB_FAKE_FFMPEG=1` the file is a placeholder and ffmpeg is not started.

`POST /api/gizmo/clips` starts a job with `kind: "gizmo"` and `mode: "cut"`. The body is `source`, `dataset`, and `clips`. Each clip is `start` (seconds), `frames` (one grid length), `muted`, and optional `width`, `height`, `keep_every`, `crop` (`[x, y, w, h]`), `sar`, `caption`. Omitted width and height use `target_size(display_width, display_height, 99.0)`, which is the desktop's native size (`_size`). `with_audio` follows the probe's `has_audio`, including when muted: the `_mute` suffix is the instruction, and the track stays. The output name is `output_name`. The job's `command` is `build_export_command` for that clip (the first clip when several are sent, and `commands` holds each argv). A non-empty caption is written to `<stem>.txt` beside the mp4, the voice export's sidecar rule. Empty caption writes no text file. The desktop does not caption a video on its own. This writes one only when the page sends the text.

`POST /api/gizmo/voices` starts a job with `kind: "gizmo"` and `mode: "voice"`. The body is `source`, `dataset`, and `segments`. Each segment is `start`, `frames` (one audio grid length), and `caption`. The name is `voice_output_name`. The argv is `build_voice_export_command`, the list in `_audio_export_worker`:

```
ffmpeg -y -hide_banner -loglevel error -ss START -i SRC -vn -af aresample=32000,atrim=end_sample=N,apad=whole_len=N -ac 2 -ar 32000 -c:a pcm_s16le DST
```

`N` is `hop_exact_samples(frames)`. The caption file is `<stem>.txt` beside the wav, the caption string unchanged. A segment with an empty caption is 422.

`POST /api/gizmo/scan` starts a job with `kind: "gizmo"` and `mode: "scan"`. The body is `source`, `threshold`, `duration`, `span_s`, and `fill` (default true). The command is `build_scene_scan_command`. The runner parses stderr with `parse_scene_time` and plans starts with `plan_autochop`. The starts are written to `scans.json` in the job folder. `FIZGIG_WEB_FAKE_SCENES=1` reads `detector` from the job values instead of running ffmpeg. A scan past `AUTOCHOP_MAX_SEGMENTS` (400) is truncated to that many starts.

`POST /api/gizmo/transcribe` starts a job with `kind: "whisper"`. The body is `source`, `start`, `span`, `language` (`Auto detect` or one `WHISPER_LANGUAGES` entry), and `output` (a `.txt` path inside a dataset root). The runner holds the GPU lock. The desktop pipeline uses CPU (`device=-1`); this job does the same and still holds the lock so it does not overlap training. The extract argv, checked in the unit test and not run under the fake, is the list in `_whisper_worker`:

```
ffmpeg -y -hide_banner -loglevel error -ss START -t SPAN -i SRC -vn -ac 1 -ar 16000 -c:a pcm_s16le WAV
```

The job command is `python -m fizgig.web.whisper_run` with `--source`, `--start`, `--span`, `--language` (`auto` or the lower-case name), and `--output`. `FIZGIG_WEB_FAKE_WHISPER` is a script with those flags. It writes `saying "fake words"` to the output and prints `CAPTION:` plus that text, then `PROGRESS: 1 1`. It does not import a model. The real module writes `saying "<transcript>"`, the text `_whisper_done` inserts, and the same `CAPTION:` line. A degenerate transcript (the `_whisper_degenerate` rules) fails the job and writes nothing. The page copies the `CAPTION:` line into the caption field. A cut or a voice save then writes that text beside the file.

`GET /api/gizmo/name?source=&dataset=&muted=0&kind=clip` returns the next `output_name` or, with `kind=voice`, the next `voice_output_name`.

## Converter

`GET /api/convert/form` is the desktop inputs: `ranks` `[8, 16, 32, 64, 128, 256]`, `default_ranks` `[32, 64]`, `name` `extracted`, and `output_dir` (the LoRA output directory, or empty when Preferences has none).

`POST /api/convert/jobs` starts a job with `kind: "convert"`. The body is `base`, `tuned`, `ranks`, and `name`. Both files are `.safetensors` inside the roots. The same path for both is 422. No rank, or a rank outside the list, is 422. An empty name is `extracted`. The output directory is the LoRA output directory. The runner holds the GPU lock and runs `python -m fizgig.web.convert_run --base <file> --tuned <file> --output <dir> --name <name> --ranks <32,64>`. Ranks are in the desktop order. That module calls `extract_diff_loras(base, tuned, out, ranks, name=name)`, which writes `<name>_<timestamp>_r<rank>.safetensors`. `FIZGIG_WEB_FAKE_CONVERT` is a script with the same flags. It writes a placeholder `<name>_fake_r<rank>.safetensors` and does not import a model.

## Mirror pins

`checks/test_web_mirrors.py` also hashes, from `gizmo.py`: `audio_latents_for`, `hop_exact_samples`, `build_export_command`, `output_name`, `target_size`, `snap`, `build_scene_scan_command`, `parse_scene_time`, `parse_progress_time`, `plan_autochop`, `voice_output_name`, `probe_source`, `_audio_export_worker`, `_whisper_worker`, `_whisper_degenerate`. From `diff_to_lora_gui.py`: `_start`, `_work`.

## Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py"`

93 tests, 91 passed, 2 skipped, 0 failed. Three runs in a row, same counts each time (222.647s, 219.261s, 221.160s). The two skipped tests are the golden tests. The new tests use fakes. They do not load Whisper, a checkpoint, or CUDA. ffmpeg is asserted as an argv. One test runs ffmpeg on a generated clip when ffmpeg is on PATH, and it skips when it is not. They cover the cut argv against the desktop builder for the same in, out, and spec; scene-chop starts from a canned detector listing; clip and caption names against the desktop helpers; the recording upload's 413 and its conversion argv; a 206 with the right `Content-Range`, and a path outside the roots refused; the converter command for the same base, tuned file, ranks, and name, using the fake script; and the mirror pins.

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

2 tests, passed (12.692s).

`npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Gaps

- The page does not draw a crop. A cut uses the whole frame unless the request sends `crop`. The out mark is the transcribe end. A cut uses the selected grid length from the in mark. Save voice uses the audio grid, so a 5-frame video length is saved as 22.
- Prompted sentences, delivery, and the push-to-talk cushions stay on the desktop. The browser records a take and the server wraps it as a wav.
- Whisper stays on CPU, as the desktop pipeline does. The job holds the GPU lock.
- A video clip gets a `.txt` only when the page sends a caption. The desktop never writes one.
- The recording conversion decodes a container. The desktop's take wrapper reads raw s16le because that is what its capture writes.

## Still manual

- Cut a real clip from the page and confirm Fizgig accepts the file.
- Run Whisper on a real take.
- Record from a phone through `tailscale serve` and confirm the wav lands in the dataset folder.
- Diff two real checkpoints and load one written LoRA.
