# Web UI phase 3

Phase 3a is the batch tools. Phase 2 jobs, the detached runner, the GPU lock, SSE, the form specs, and the root-limited folder browser stay as they are. This phase adds Samples settings, a weights profile, LoRA extraction, and safetensors metadata.

The browser is still a thin client. Profiler and Extract are jobs on the same lock as training. Every route is behind the existing Host check. Every POST, PUT, and DELETE is behind the existing Origin check.

## Samples

`GET /api/samples/form?family=` is the Samples tab for one family: prompts, width and height (`SAMPLE_RESOLUTIONS`, read from the desktop source), every N epochs, sample at start, seed, and the family's steps, CFG, and negative prompt. Klein also has the Distilled checkpoint tick and its RAM cache. A family with the turbo file set has Turbo strength. MiniMax has the turbo pace row (steps and percent).

Defaults and the wording (`banner`, `advanced`, `flow`, `neg`, `cfg`, `steps`, `sampler`) follow `update_samples_ui_for_architecture`, `_generic_samples_ui`, and `_apply_samples_minimax`. A CFG-free family disables negative prompt and CFG. Klein's steps box is disabled while the Distilled tick is on (`disabled_when`: `checkpoint`).

The page sends those values on `POST /api/jobs` and `POST /api/queue` inside the samples dict `launch.plan` already reads (`enabled`, `prompts`, `every`, `width`, `height`, `steps`, `cfg`, `negative`, `seed`, `at_first`, and for Klein `checkpoint` and `checkpoint_cache`). Turbo keys go beside that dict (`FAMILY_TURBO_STRENGTH`, `FAMILY_TURBO_STEPS`, `FAMILY_TURBO_PACE`). A prompt string is split into lines. When Klein's checkpoint tick is on and the request omits `int8`, the server fills it from the `inference_int8` preference, the same toggle `_get_inference_int8` reads.

## Profiler

`GET /api/profile/form?family=` is the Profiler tab's inputs: family, LoRA, mode (`weights`, `quick`, `thorough`), prompt, bleed-check prompt, subject photos, and size (`512`, `768`, `1024`). The desktop opens on Quick. This phase runs Weights only, so the form defaults to `weights`.

`POST /api/profile/jobs` starts a job with `kind: "profile"`. The body is `family`, `lora`, and `mode`. The LoRA must be a `.safetensors` file inside the roots. The runner holds the GPU lock and runs `python -m fizgig.scripts.profile_lora --lora <file> --family <key> --output <profiles_dir>/<stem>_<lora_name_suffix>_profile.html`. That output path is the one `_run_profiler_family` builds. Stdout is copied into the job log. A line `PROGRESS: <step> <total>` or a trailing `<step>/<total>` updates the job. `FIZGIG_WEB_FAKE_PROFILE` is a script that takes the same flags and does not load a model. Quick or Thorough returns 422. Stop kills the runner tree.

`GET /api/profiles` lists the `.html` files in `profiles_dir`: `{"dir", "reports": [{name, path, url}]}`.

`GET /api/profiles/file?path=` returns one of those reports. The path has to resolve inside `profiles_dir`, with the same `..` and link rules as the folder browser.

## Extract

`GET /api/extract/form?family=` is the Extract tab: family, the family's extract presets plus Custom, the block groups from `load_driver().block_map()` when the family has presets, target ranks `1`, `2`, `4`, `8`, `16` (default `4`), and the time note from `_apply_extract_family_ui`.

`POST /api/extract/jobs` starts a job with `kind: "extract"`. The body is `family`, `source`, `output_name`, `preset`, `blocks`, and `rank`. The source must be a `.safetensors` file inside the roots. The output name is one file name in the LoRA output folder (`.safetensors` is added when it is missing). An empty name uses `<source stem>_<preset slug>_r<rank>.safetensors`, the desktop suggestion. An existing file gets `_2`, `_3`, … rather than being overwritten. The runner holds the GPU lock and runs `python -m fizgig.scripts.extract_lora --family <key> --source <file> --output <path> --rank <n>` plus `--preset <name>` or, for Custom, `--blocks <id,id>`. A named preset is not also sent as blocks. Custom with nothing ticked is 422. `FIZGIG_WEB_FAKE_EXTRACT` takes the same flags and does not load a model.

## Metadata

`GET /api/metadata?path=` reads one `.safetensors` file inside the roots. The body is `path`, `title`, `author`, `license`, `tags`, `trigger`, `usage_hint`, `description`, `thumbnail`, and `extra` (every other metadata key).

`PUT /api/metadata` writes those fields back. An empty string removes that standard key. `thumbnail` is a `data:image` URI, or a path of an image inside the roots (embedded with `thumbnail_data_uri`). `extra`, when sent, replaces the other keys; when omitted, the keys already in the file stay. `sshs_model_hash`, `sshs_legacy_hash`, and `modelspec.hash_sha256` are dropped, as `_save_metadata_file` drops them. The tensor header entries are copied and the tensor bytes are appended unchanged. The previous file is copied to `<file>.bak`, then a temp file replaces the original. A path outside the roots, a `..` segment, or a link below the root is 403.

Review fix: a read parses the 8-byte length and the JSON header only, and a save copies the tensor bytes in chunks, so a metadata edit does not load a large checkpoint into memory.

## Jobs

`kind` may also be `profile` or `extract`. Pause, resume, and sample override still refuse anything that is not training. Caption, prep, profile, and extract do not advance the training queue.

## Mirror pins

`checks/test_web_mirrors.py` also hashes `create_samples_settings`, `update_samples_ui_for_architecture`, `_generic_samples_ui`, `_apply_samples_minimax`, `create_profiler_tab`, `_run_profiler`, `_run_profiler_family`, `create_extract_tab`, `_run_extract`, `_extract_worker_family`, `_apply_extract_family_ui`, `create_metadata_tab`, `_load_metadata_file`, and `_save_metadata_file`.

## Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py"`

41 tests, 39 passed, 2 skipped, 0 failed. Three runs in a row, same counts each time (143.985s, 145.006s, 144.241s). The two skipped tests are the golden tests. The new tests cover the samples form and a queue round-trip, the profiler and extract commands against the CLIs (fake scripts, no model), report serving inside `profiles_dir`, and a metadata edit on a generated safetensors file (tensor bytes unchanged, a `.bak` beside the file, a path outside the roots refused).

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

2 tests, passed (8.458s). The second compares one preset per family with non-default prompts, resolution, frequency, seed, steps, CFG, and negative prompt.

`npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Gaps

- Quick and Thorough profiling render on the workbench engine. That is phase 3b. This phase runs the weights CLI only.
- Open in Repair Studio stays on the desktop.
- Every N steps, the reference image, flow shift, and sample length (frames) stay on the desktop. `launch.plan` does not read Every N steps.
- The page does not remember each family's sample box the way the desktop stashes it. Changing family loads that family's defaults.
- Metadata has no separate custom-field editor. Other keys are kept and returned as `extra`. There is no Save As to a second path.
- A fine-tune resume from the page still does not point `--dit` at the checkpoint.

## Still manual

- Profile a real LoRA (Weights only) and open the HTML report from the page.
- Extract a real LoRA and load the file from the LoRA output folder.
- Edit a real file's metadata, confirm the tensors still load, and confirm the `.bak` is the previous file.
- Start a training run with non-default sample settings and compare one preview with the desktop.
- Phone access through `tailscale serve` is still the phase 1 check.

## 3b-i

Phase 3b-i is the engine host, Repair Studio, and the Profiler's Quick and Thorough modes. RefMod Studio, LoRA the Explorer and LoRA Royale are not in this phase. The host accepts those engine names so they can register later.

### Protocol

The server starts one child, `python -m fizgig.web.engine_worker`. They speak one JSON object per line. Requests go to the worker's stdin. Events and replies come back on stdout.

Requests:

| op | fields |
|---|---|
| load | `engine`, `family`, `args` |
| render | `gen`, `params` |
| cancel | `gen` |
| unload | |
| status | |

`engine` is `repair`, `profiler`, `refmod`, `explorer` or `royale`. Each request has an `id`. The matching reply has the same `id` and `ok`.

Events, which the page receives as SSE `engine`:

| event | when |
|---|---|
| loading | a load has started |
| frame | one step, with `gen`, `step`, `total`, and a `file` when the step produced an image |
| done | the render finished: `baseline`, `image`, `clip`, and for a profile a `profile` object |
| cancelled | this `gen` was dropped |
| error | the render failed, or the worker stopped |
| unloaded | the engine is gone and the GPU lock is released |

A render with a higher `gen` cancels the one in flight (`_run_preview_async`, `_repair_render_gen`). A frame or a final image whose `gen` is no longer current is not delivered (`_repair_show_early`).

Images go in `<jobs root>/engine/<session>/` and are served at `GET /api/engine/file?path=`, inside that folder only. The same `..` and link rules as the folder browser apply.

The worker holds the GPU lock from a successful load until unload. `POST` of a load while a training or caption job holds the lock returns 409: "A training or caption job is using the GPU. Wait for it to finish before loading an engine." Starting a GPU job while an engine is loaded returns 409: "An engine is loaded. Unload it before starting a job."

The engine unloads after `FIZGIG_WEB_ENGINE_IDLE` seconds with no load, render or cancel (default 600), on `POST /api/engine/unload`, and when the server shuts down. If the worker dies, the next request starts another and the page gets an `error` event with `restarted: true`.

`FIZGIG_WEB_FAKE_ENGINE=1` selects a fake engine. It writes tiny PNGs, emits a frame per step, and sleeps `FIZGIG_WEB_FAKE_STEP` seconds per step. It does not import a model.

### Repair Studio

`GET /api/repair/form?family=` is the tab: families with `repair` in the workbench, the driver's block groups, resolution, DiT choice (`fast` is the preview checkpoint or speed LoRA, `base` is the training model), and the preset list.

`POST /api/repair/load` loads that family's workbench engine. The plan follows `_workbench_preview_model` and `_repair_engine_plan_family`: DiT, VAE, text encoder, speed LoRA, the INT8 preference, and the inference block-swap preference. A video family also passes the audio VAE and the prompt-cache folder.

`POST /api/repair/render` sends a `SliderState` and a `gen`. The page waits 400 ms after a slider edit and 100 ms after a forced edit (`_schedule_preview`) before it sends. The host keeps only the newest `gen`. A video family can set `early_step` so the pass image streams back (`_repair_show_early`). The clip, when ffmpeg is on `PATH`, is an mp4 from the engine's frames and is played in a `<video>` element.

`PUT /api/repair/presets` writes `presets/repair_studio/<family>/` (the family's `shares_prefs_with`, else its key). The file is blocks plus `family`, the same shape `_save_repair_preset` writes. `GET /api/repair/presets/file` applies blocks only (`_load_repair_preset`). Built-ins follow `_repair_builtin_state`, including Klein's category presets.

`POST /api/repair/bake` calls `save_repaired_lora(primary, state, out, donor_path)`. `donor_path` is set only when a donor block is enabled, which is the desktop's file bake. The output name is `<primary>_repaired.safetensors`, or `<primary>_with_<donor>.safetensors` when a donor block is on. An existing file gets `_2`, `_3`, …

`POST /api/repair/metrics` runs `repair_studio.metrics.compare` on the baseline and repaired PNGs.

### Profiler

The form defaults to Quick, as the desktop does. Weights is still `POST /api/profile/jobs` and the weights CLI. Quick or Thorough on that route is 422.

`POST /api/profile/engine` loads the profiler engine and renders. Quick uses seed 1234. Thorough uses 1234 and 5678 and the per-block pass (`_run_profiler_family`). The report is the same `<stem>_<suffix>_profile.html` under `profiles_dir`.

`POST /api/profile/repair` is Open in Repair Studio (`_profiler_open_in_repair`): the LoRA, prompt, seed, size, and the suggested sliders. The page opens Repair Studio with that state.

### Mirror pins

`checks/test_web_mirrors.py` also hashes `_schedule_preview`, `_run_preview_async`, `_repair_preview_worker`, `_repair_show_early`, `_save_repaired_lora_action`, `_save_repair_preset`, `_load_repair_preset`, `_reset_repair_sliders`, `_repair_preset_dir`, `_repair_category_for_block`, `_repair_builtin_state`, `_profiler_open_in_repair`, `_workbench_preview_model`, `_repair_engine_plan_family`, `_get_inference_blocks_to_swap`, `_get_inference_int8`, and `_auto_detect_blocks_to_swap`.

### Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py"`

51 tests, 49 passed, 2 skipped, 0 failed. Three runs in a row, same counts each time (188.344s, 188.381s, 184.070s). The two skipped tests are the golden tests. The new tests use the fake engine: the protocol round trip, newest-gen cancellation, idle unload, a worker crash and restart, the GPU lock both ways (409), the Repair preset save and load in `SliderState` form, the bake call's arguments, and Quick, Thorough and the Repair handoff.

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

2 tests, passed (8.805s).

`npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

### Gaps

- RefMod Studio, LoRA the Explorer and LoRA Royale are not built. `register_engine` is how they attach.
- Likeness and bleed scores need the desktop's face embedder. Quick and Thorough on the page measure the picture change only.
- The H3 ref2va checkpoint picker, the render library, and no-LoRA clips stay on the desktop.
- The page bakes with `save_repaired_lora`. A described family on the desktop bakes with the live engine's `save_repaired` when that method exists.
- Without ffmpeg, a video render keeps the middle frame and does not produce an mp4.
- A real engine load and a slider render on the GPU were not run from this page.

### Still manual (3b-i)

- Load a real family on the page and render. Compare the first frame's latency with the desktop on the same GPU.
- Move a slider and confirm the in-flight render restarts.
- Run Quick on a real LoRA, open Repair Studio, and save a baked file.
- Play a video family's clip in the page's player.
