# Web UI phase 2

The workflow before training. Phase 1 jobs, the detached runner, the GPU lock, SSE, and the form specs stay as they are. This phase adds the queue, history, notifications, preferences, the folder browser, the Start folder, captions, and image prep.

The browser is still a thin client. State lives on disk under the jobs root (`cache/web_jobs`, or `FIZGIG_WEB_JOBS`). Every route is behind the existing Host check. Every POST, PUT, and DELETE is behind the existing Origin check.

## Queue

A queue item is widget-free: a family id, the training form values, and the samples dict `launch.plan` already reads (`enabled`, `prompts`, `every`, `width`, `height`, `steps`, `cfg`, `negative`, `seed`, `at_first`). `context` also carries `image_folder`, `models`, and `concept_folders` the same way `POST /api/jobs` does.

The file is `<jobs root>/queue.json`. The server re-reads it on every call, so a restart keeps the list. A restart does not start the next item by itself.

`GET /api/queue` → `{"items": [{id, family, values, context, added, label}]}`

`POST /api/queue` body is the job create body (`family`, `values`, `context`). It appends one item. It does not start a run. 404 on an unknown family. 422 when no image folder is set.

`POST /api/queue/order` `{"ids": [ ... ]}` replaces the order. The ids must be the current set. 422 otherwise.

`DELETE /api/queue/{id}` removes one item. 404 when it is missing.

`POST /api/queue/advance` `{"confirm": []}` starts the head through `jobs.start`. The item stays at the head when the start is refused (validation, warnings, a busy GPU). `confirm` is the same warning codes as `POST /api/jobs`.

`POST /api/queue/import` reads `presets/training_queue.json` and appends. It does not write that file. `FIZGIG_WEB_DESKTOP_QUEUE` points the read at another file in tests. The mapping follows `_apply_queue_item` (and `_canon_arch` before the family lookup): architecture label → family id, `preset` → form values, `model_options` merged on top, `image_folder`, `concept_folders` → `MINIMAX_CONCEPT_DIRS`, and the Samples-tab keys → the samples dict. An entry whose family is unknown is counted in `skipped` and not added. Response: `{"imported", "skipped", "items"}`.

Auto-advance runs only when a training job this process saw leave `queued` or `running` for `done`. Failure, stop, and pause hold the queue. Caption and prep jobs are not queue items; when they finish they do not start the queue. A busy run or a held GPU lock is retried on the next poll. A validation or warning refusal holds until the queue is edited or Advance is posted. This matches the desktop, which advances only after a clean training exit.

## History

`GET /api/history` lists jobs that are not queued or running, newest first. Each row is the job object plus `duration` (seconds from `started` to `ended`, or null) and `kind` (`train`, `caption`, or `prep`). Loss and `output_dir` are the job's.

`GET /api/jobs/{id}`, the log route, and the samples route are the reopen view.

`DELETE /api/jobs/{id}` removes the job folder (`job.json`, `log.txt`) and nothing else. 409 while the job is queued or running. The output directory and the dataset are left in place.

## Notifications

SSE `notice` events are unchanged (`finished`, `failed`, `paused`). The page keeps the in-page list. A button calls `Notification.requestPermission()` and, once permission is granted, shows a browser notification for those three kinds. Nothing asks for permission on load.

## Preferences

`GET /api/prefs` is built from the `DEFAULT_PREFS` literal (read from source, not imported) plus each family's `model_files`, the same rows `_generic_prefs_section` builds.

```json
{"directories": [{"key", "label", "value"}],
 "families": [{"key", "name", "files": [{"key", "label", "value", "required", "hint", "download"}]}],
 "secrets": [{"key", "set"}]}
```

Directory rows are the `DEFAULT_PREFS` keys that end in `_dir`. Model rows are the description's files. `value` is the resolved path.

`runpod_api_key` and any key ending in `_key`, `_token`, or `_secret` appear only under `secrets` as `set` true or false. The value is never sent.

`PUT /api/prefs` `{"values": {key: path}}` updates directory and model keys. Secret keys in the body are ignored, so a save cannot blank or replace them. Any other key is ignored and kept. Portable directories (`lora_output_dir`, `profiles_dir`, `cache_dir`) are stored relative to the repo when they point inside it, absolute otherwise, the way `save_prefs` does. The write is a temp file plus replace. `FIZGIG_PREFS_FILE` selects the file. `FIZGIG_NO_PERSIST` skips the write only when that override is unset, so a test file still saves.

These directories and the parent folder of each set model path are folder-browser roots, with the repo `dataset` folder, the Start folder, and `FIZGIG_WEB_ROOTS`.

## Folder browser and upload

`GET /api/fs?path=` with an empty path lists the roots. With a path, it lists the children of that directory: `dir`, `image`, and `file`. A path is refused (403) when it contains `..`, when a symlink or a junction sits strictly below the matching root, or when the resolved path is outside the roots. The configured root may itself be a link, or live under one.

`POST /api/upload` is multipart (`python-multipart`, pinned in `requirements-web.txt`). `dest` is an existing directory inside a dataset root (the dataset pref, the repo `dataset` folder, the Start folder, or `FIZGIG_WEB_ROOTS`). `files` are images. `archive` is a zip of images. Names must be a single safe segment. Members that are absolute, contain `..`, or extract outside `dest` are rejected and nothing is written. An existing name returns 409 `{"conflicts": [names]}` and writes nothing; `overwrite=1` replaces those files. The same leaf name twice in one request, in the files or the zip entries, returns 422 `{"problems": ["duplicate name: …"]}` and writes nothing, including when `overwrite=1` is set. The total size, including uncompressed zip bytes, must be within `FIZGIG_WEB_UPLOAD_MAX` (default 64 MiB) or the response is 413.

`GET /api/download?path=` returns one `.safetensors` file that resolves inside an output root (the LoRA output pref, the profiles pref, or a job's output directory).

Every form field whose kind is `folder` or `path`, the model rows, and the preferences rows use a Browse button on this listing. A folder field picks the open directory. A path field picks a file.

## Start

`GET /api/start` and `PUT /api/start` `{"folder": path}` share one folder, stored in `<jobs root>/start.json`. The folder has to be an existing directory inside the roots. An empty string clears it.

```json
{"folder", "images", "captions", "missing", "ready"}
```

`images` and `captions` match `_analyze_dataset` (top-level image files, and `.txt` files). `missing` is the image count whose stem has no `.txt`. The page shows that summary and the five workflow steps from `create_start_tab`. Captions, Image Prep, and Training read this folder.

## Captions

`GET /api/captions/form` is the settings from the Captions tab: trigger word, model (the three Florence ids, or Qwen3-VL when the Krea 2 text encoder pref is set), Florence task, max tokens, overwrite, one instruction string, and include-video. Per-task instruction presets are not in this phase.

`POST /api/captions/jobs` starts a job with `kind: "caption"`. The runner takes the GPU lock and runs `python -m fizgig.scripts.batch_caption --serve --config <job>/worker_config.json`. It waits for `READY`, sends `RUN <job>/caption_job.json`, copies stdout into `log.txt`, and stores `PROGRESS` as step and total. `QUIT` follows `DONE` or `STOPPED`. `FIZGIG_WEB_FAKE_CAPTION` is a script that speaks the same protocol and does not load a model. Images that already have a `.txt` are left out unless overwrite is set. Stop kills the runner tree, which kills the worker.

`POST /api/captions/static` writes the trigger word into each image's `.txt`, skipping files that exist unless overwrite is set. It is not a GPU job.

`GET /api/captions?folder=&q=` lists images in that folder with their caption text. `q` matches the file name or the caption. `GET /api/captions/image?folder=&name=` returns the image. `PUT /api/captions` `{"folder", "name", "text"}` writes the `.txt` beside the image. The folder must be inside the roots, and the name must be one segment.

Translation and Whisper are not in this phase.

## Image prep

`GET /api/prep/form` is the desktop modes and options: `Auto Prep (Face Crops)`, `Resize Only`, `Face Crop Only`; megapixels `0.25` through `4.2` (default `1.0`); face `Largest Face`, `Largest Male Face`, `Largest Female Face`; padding percent (default 20); keep originals (default) or replace them.

`POST /api/prep/jobs` starts a job with `kind: "prep"`. The runner holds the GPU lock and calls `image_prep.prepare`. Output naming, the originals folder, the area resize, and the face-crop pass follow the desktop helpers. Face crops call `face_utils.crop_to_face`. The detector is `face_utils.FaceDetector` except when `FIZGIG_WEB_FAKE_FACE=1`, which uses an in-process stub and does not load a model. The Look filter is not in this phase.

## Jobs

`kind` is on the job object (`train` when omitted). Pause, resume, and sample override refuse a caption or prep job. One job at a time still goes through the existing busy check and the GPU lock.

## Mirror pins

`checks/test_web_mirrors.py` hashes these as well as the phase 1 set: `_apply_queue_item`, `_canon_arch`, `_generic_prefs_section`, `save_prefs`, `_resolve_pref_path`, `_serialize_pref_path`, `create_start_tab`, `_analyze_dataset`, `create_caption_generator`, `generate_captions`, `convert_images`, `_resize_image`, `_prep_target_area`, `_get_face_selection_mode`, `_resize_only_images`, `_face_crop_only_images`, `_auto_prep_images`.

## Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py"`

34 tests, 33 passed, 1 skipped, 0 failed. Three runs in a row, same counts each time (77.785s, 77.641s, 79.969s). The skipped test is the golden test. The new tests cover the queue (add, reorder, remove, persistence, auto-advance, read-only import), history and delete-keeps-outputs, prefs secrets, fs roots (`..`, symlink, junction), upload limit and zip-slip, Start counts, the caption job plus edit/save, and Image Prep against the desktop helpers with a stubbed face detector.

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

1 test, passed (8.137s).

`npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Review fixes

The link check stops at the configured root. A root may be a symlink or junction, or sit under one, and browsing, upload, and LoRA download accept paths under it. A symlink or junction anywhere between that root and the target is still refused, and `..` is still refused.

An upload that repeats a leaf name, across files or zip entries, is rejected with 422 and those names before anything is written.

## Gaps

- Bilingual translation and Whisper stay on the desktop.
- The Look filter stays on the desktop.
- Gizmo (video and audio cutting) stays on the desktop.
- The Samples tab editor is phase 3a. The queue stores the samples dict a launch already accepts.
- Per-task Qwen instruction presets stay on the desktop. The page has one instruction string.
- Find and replace across captions stays on the desktop.
- A fine-tune resume from the page still does not point `--dit` at the checkpoint (`plan()` never did).

## Still manual

- Import a real `presets/training_queue.json` from a desktop session and start the head on a GPU.
- Caption a folder with Florence or Qwen, and run face-crop with the real detector.
- Allow a browser notification and confirm a finished run shows one.
- Phone access through `tailscale serve` is still the phase 1 check.
