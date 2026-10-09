# Web UI phase 1

**Status:** 1b and 1c built, uncommitted, on commit 6c0f49a. The desktop diff is the GPU lock only (`git diff --numstat -- lora_trainer_gui.py` is `39  2`).

**1a result:** the Training tab is a declarative form. `GET /api/form?family=<id>` returns that family's fields in desktop order, then the `train.py` flags the form does not already cover. `launch.plan()` matches the desktop command builders for all 39 built-in presets. The 8 edit and slider presets match once the pair folder has one PNG. With that folder left empty, `_generic_validate_paths` and `launch.problems()` return the same list. `launch.py` was not changed. The desktop app was not changed in 1a. The GPU lock landed in 1b.

## 1a

### Fields served

Description-driven controls (network type, optimizer, base precision, model area, and each family's own options) come from the `FamilyDescription`. Everything else `create_training_settings` shows is in `src/fizgig/web/form_spec.py`. A field is included when that family can show it. `when` says when it is hidden inside the family (Adaptive LR off, LoKR, Edit, Slider, Fine-tune, a clip in the dataset, the captioner file set).

Auto-recaption is on the form for every family with the loss watch, and only while the captioner path is set. Clip Target Megapixels is on the form for a family whose media include clips, and only while the dataset contains a clip. The Samples tab is not part of this form. The golden comparison feeds the desktop Samples tab's current values into both launches, including MiniMax's sample-length option (the Samples tab starts at 56 frames with sound; that option's first choice is Still).

| Family | Fields | Advanced | Unmapped |
|---|---:|---:|---|
| Klein 9B | 73 | 33 | Attention Mechanism, Logging Directory, Log With, Log Prefix |
| MiniMax H3 | 82 | 45 | the same four |
| Krea 2 | 67 | 35 | the same four |
| Qwen Image 2.1 | 71 | 34 | the same four |
| SDXL | 65 | 39 | the same four |
| Anima | 66 | 36 | the same four |
| Z-Image Turbo | 67 | 35 | the same four |

Those four are on the Training tab. `families/train.py` has no flag for them, and `plan()` does not read them, so a value set there does not change the launch.

Not served, and why:

- Model Type is created and hidden for every described family.
- LoRA LR ratio is created and never placed. The launch still sends 1.
- The img/txt offload switch is stored and never placed.
- The RefMod card is a separate base-model entry, not one of the seven families.

### Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v`

15 tests, 14 passed, 1 skipped, 0 failed. The skipped test is the golden test. It stays off unless `FIZGIG_GOLDEN` is `1`, so the default suite does not build the desktop window.

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

1 test, passed. 39 built-in presets. The cache commands, the train command, the dataset TOML, and the written files were the same after temp paths and line endings were normalised.

`npm --prefix webui run build` passed. `tsc --noEmit` and Vite both ran.

### Edit and slider presets

These 8 are in the 39. The comparison sets the folder a user must fill, on the desktop widget and the web form, with one PNG named like the training photo.

Slider presets, the -1 end folder:

- MiniMax H3, `✨ MiniMax H3 Slider (rank 8, 2e-4)`
- Krea 2, `✨ Krea 2 Slider (rank 8, 2e-4)`
- Qwen Image 2.1, `✨ Qwen 2.1 Slider (rank 8, 2e-4)`
- SDXL, `✨ SDXL Slider (rank 32, alpha 16, 5e-5)`
- Anima, `✨ Anima Slider (rank 8, 2e-4)`
- Z-Image Turbo, `✨ Z-Image Turbo Slider (rank 8, 2e-4)`

Edit presets, the Originals folder:

- Qwen Image 2.1, `✨ Qwen 2.1 Edit (rank 8, adaptive LR)`
- Qwen Image 2.1, `✨ Qwen 2.1 Edit Strong (rank 16, adaptive LR) - trickier edits`

With that folder left empty, `_generic_validate_paths(desc)` and `launch.problems()` on the web inputs return the same list. The desktop Start button refuses the run there too. `_generic_cache_command`, `_generic_train_command`, and `dataset_toml` still build a launch for an empty folder. The golden test does not compare them in that state.

## 1b/1c API

The browser is a thin client. Job state lives in the job folder. Every route below is behind the existing Host check, and every POST is behind the existing Origin check.

### Jobs

`POST /api/jobs`

```json
{"family": "sdxl", "values": {}, "context": {}, "confirm": []}
```

`values` are form fields. `context` carries what the Training tab does not: `models` (`{pref_key: path}`), `image_folder` when the form has no folder of its own, `DATASET_CONFIG`, `cache_root`, `samples`. `confirm` lists warning codes the user has accepted (`low_disk`, `resume_epochs`).

- 200: a job object (below).
- 404: unknown family.
- 409 `{"detail": "a run is already active"}` when a job is queued or running.
- 409 `{"detail": "the GPU is in use"}` when the GPU lock is held, including by the desktop.
- 409 `{"warnings": [{"code", "message"}]}` for a low-disk drive or a resume already at max epochs. Sending the codes in `confirm` starts the run. The messages are the desktop's.
- 422 `{"problems": [text, ...]}` when `launch.problems()` is not empty, or when `launch.plan()` then reports problems. A plan with problems does not start.

`GET /api/jobs` returns `{"jobs": [job, ...]}`, newest first.

`GET /api/jobs/{id}` returns one job:

```json
{"id", "family", "status", "pid", "stage", "step", "total", "loss", "created", "started", "ended", "output_dir"}
```

`status` is `queued`, `running`, `paused`, `stopped`, `failed`, or `done`. `step`, `total`, and `loss` are parsed from `log.txt` with `TrainingProgressTracker`. `loss` is a number or null.

`GET /api/jobs/{id}/log?offset=N` reads `log.txt` from byte `N`.

```json
{"offset": 0, "next": 120, "text": "..."}
```

`POST /api/jobs/{id}/pause` writes `<output>/.pause_requested` (empty file), the way the desktop does. The runner marks the job paused when that stage exits 0 and a state directory was saved.

`POST /api/jobs/{id}/resume` reads `.fizgig_paused.json`, starts the same job again with `--resume` set to the state directory, and removes the sidecar only once that run is actually going.

`POST /api/jobs/{id}/stop` kills the process tree (`taskkill /F /T /PID` on Windows, `killpg` elsewhere) when the stored pid and `pid_create_time` still name that runner, then marks the job stopped. A live pid whose creation time does not match is marked failed, and that process is left alone.

`POST /api/jobs/{id}/override`

```json
{"prompt": "", "seed": 1234, "width": 768, "height": 768}
```

A prompt writes `<output>/.sample_override.json` atomically as `{"prompt", "seed", "width", "height"}` (desktop defaults 1234, 768, 768). An empty prompt removes the file.

`GET /api/jobs/{id}/samples` returns `{"samples": [{"name", "url"}]}` for images under `<output>/sample`. `GET /api/jobs/{id}/samples/{name}` returns that image. The name has to be one path segment, and the file has to resolve inside the job's output directory.

### Events and system

`GET /api/events` is `text/event-stream`. Each event is `event: <name>` plus one JSON `data` line. `?once=1` sends one round and closes. The page leaves it off and keeps the stream open.

| Event | When | Data |
|---|---|---|
| `job` | about once a second, per job | the job object |
| `progress` | with each job event | `{id, stage, step, total, loss}` |
| `sample` | a sample image appears | `{id, name, url}` |
| `system` | about once a second | `{vram: {used, total} or null, ram: {used, total} or null}` |
| `notice` | a job becomes done, failed, or paused | `{id, kind, message}` `kind` is `finished`, `failed`, or `paused` |

`GET /api/system` returns the same object as the `system` event. VRAM is read the way the desktop status bar reads it (pynvml, then nvidia-smi, then the AMD reader). RAM is `psutil.virtual_memory`. No torch, and no CUDA context.

### Form additions

`GET /api/form` still returns `family`, `fields`, and `advanced`. It also returns `display_name`, `presets` (`{name, values}` already filled the way a chip should fill the form), and `models` (`{key, label, required}`).

### Files and the lock

Jobs root is `cache/web_jobs`, or `FIZGIG_WEB_JOBS` when that is set. Both `cache/web_jobs` and `cache/gpu` are covered by the existing `cache/*` ignore. Each job folder holds `job.json` and `log.txt`. `job.json` holds the id, family, form values, context, plan summary, the stage commands that will run, status, pid, `pid_create_time`, stage, step, total, loss, timestamps, and the output directory. `pid_create_time` is `psutil.Process(pid).create_time()` of the runner, written beside the pid when the runner starts.

The GPU lock is one file per CUDA device at `cache/gpu/<index>.lock`. The index is the first numeric `CUDA_VISIBLE_DEVICES` entry, otherwise 0. The holder keeps the file open. `msvcrt.locking` on Windows, `fcntl.flock` elsewhere. A crash closes the handle and the operating system drops the lock. On Windows, replacing `job.json` is retried while a reader has the file open.

The runner is `python -m fizgig.web.runner <job-folder>`. The server starts it with `hidden_console(detached=True)` from `fizgig.web.procs`. On Windows that is `CREATE_NEW_CONSOLE` plus `CREATE_NEW_PROCESS_GROUP`, and a `STARTUPINFO` of `STARTF_USESHOWWINDOW` and `SW_HIDE`. Elsewhere it is `start_new_session`. Stdout is discarded. `CREATE_NEW_CONSOLE` separates the run from the server's console, and the new process group keeps a server restart or Ctrl+C from killing it. The launch does not use `DETACHED_PROCESS`. The runner's own stage launches pass `creationflags=0` and inherit that hidden console. It runs the plan stages in order, appends their output to `log.txt`, and updates `job.json`. On startup `serve()` re-reads every job: a pid whose creation time still matches stays running, a live pid with a different creation time is failed, a dead pid with exit code 0 is done, a dead pid with a pause sidecar is paused, and any other dead pid is failed.

A LoRA pause writes `.fizgig_paused.json` (mode, state path, output name, dataset config, rank, alpha, max epochs) and resume launches the same job with `--resume`. A fine-tune pause is read from that sidecar and refused when the checkpoint is already at max epochs. `plan()` does not point `--dit` at a fine-tune checkpoint; that swap still lives in the desktop command builder.

`FIZGIG_WEB_FAKE_TRAINER` is the test stand-in. `plan()` still has to succeed. The stage that runs is that script instead of the real cache and train commands. Unset, the runner executes the plan commands.

## 1b/1c result

### Desktop diff

`git diff --numstat -- lora_trainer_gui.py` is `39  2`. The GPU lock, and nothing else in that file:

- `start_training`, after the existing queue check: if `gpu_lock.held()`, a messagebox and return.
- `_start_training_launch` takes the lock in `_launch_holding_gpu`, immediately before the first subprocess, and keeps it on `self._gpu_lock`. If acquire fails, the same messagebox and return. If that launch returns or raises before a subprocess exists, the lock is released. The two first-subprocess sites (cache preparation, and training when cache is skipped) go through the helper.
- `_on_training_subprocess_exited`, before the button refresh: release the lock.

`requirements.txt`, the root `.gitignore`, and `mirrors.py` are unchanged. No mirrored function was edited, so the pins stayed.

### Page

`run_webui.bat` rebuilds `webui/` when a source file is newer than `webui/dist`, then runs `python -m fizgig.web`. The server still refuses any bind except 127.0.0.1. The page is the training form (family, sections in desktop order, fields by kind, preset chips, Advanced collapsed, problems and warnings inline) plus the monitor (status, stage, progress, bounded log by byte offset, samples, pause, resume, stop, override). The top bar lists jobs and shows VRAM and RAM. Closing the tab and opening it again loads the job list, so a running job comes back with its log. A `when` rule that depends on what is in the dataset stays visible: the page does not scan the folder.

`webui/scripts/dump_openapi.py` writes `app.openapi()` without starting a server. `npm run build` regenerates the types and fails if `webui/src/api.d.ts` differs.

### Tests

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v`

23 tests, 22 passed, 1 skipped, 0 failed. Three runs in a row, same counts each time (24.142s, 23.043s, 23.645s). The skipped test is the golden test. The 8 job tests cover create/run/done, log offsets, progress, pause/resume/stop and the process tree (the resume check waits until `child.pid` is a new live pid), the override file, a reattach after reconcile, a recycled pid that stop and reconcile must leave alone, the GPU lock both ways, a 422 whose text is `launch.problems()`, and path, Host, Origin, and secret checks. The mirror pins still pass.

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

1 test, passed.

`npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

### Still manual

Two Phase 1 checks need a real machine and are not in `checks/`:

- Start a built-in preset on a real GPU, close the browser, reopen it, and see the live log, progress, and new samples.
- Open the page from a phone at the `tailscale serve` address. `tailscale serve` was not run.
