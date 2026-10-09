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

## 3b-ii

Phase 3b-ii plugs RefMod Studio, LoRA the Explorer, and LoRA Royale into the host from 3b-i. The protocol (one worker, JSON lines, `gen`, frames, the GPU lock, idle unload) stays as it is.

`make_engine` uses a `register_engine` factory before the generic fake. Repair and Profiler register nothing, so `FIZGIG_WEB_FAKE_ENGINE=1` still builds `FakeEngine` for them. Each tool module calls `register_engine` when it is imported. `python -m fizgig.web.engine_worker` imports the three modules, so the child process has the factories. A factory returns its fake when `FIZGIG_WEB_FAKE_ENGINE=1`, and the real adapter otherwise. The fake sleeps `FIZGIG_WEB_FAKE_STEP` seconds per step, writes tiny PNGs, and does not import a model.

A render result may include `records`, a JSON object. The worker copies it onto the `done` event the same way it copies `profile`. Images stay on `frame`, `baseline`, `image`, and `clip`. `records` holds labels and parameters, not file paths.

Every load follows Repair Studio: 409 when a training or caption job holds the GPU, and 409 when a job starts while an engine is loaded. Paths stay inside the configured roots.

Review fix: Royale export images and its run folder, Royale epoch and reference paths, the Explorer reference, and the RefMod scan folder are resolved inside the configured roots before use, and a path outside them is rejected with 403 before a job or render starts.

### RefMod Studio

The desktop tab is H3 only (`_rms_desc`). The page is the same.

`GET /api/refmod/form` is the setup: model (`Reference (ref2va)`, `First / Last Frame (fl2va)`), base (`REPAIR_H3_BASE_OPTIONS`), folder, prompt, seed, frames, width, height, steps, turbo, sound, early, retention, scramble, frame curve, step curve, step on, numbered, LoRA, compare (`No mod (LoRA alone)`, `No LoRA (mods alone)`, `Neither (base model)`), and the mod rows. Defaults match a fresh tab: model the first string, base the first base option, prompt `a woman smiles at the camera, soft window light`, seed `300`, frames `22 frames (~1s)`, width `640`, height `768`, steps `4`, turbo `1.0`, sound on, early on, retention `1`, scramble `-1`, frame curve and step curve the `refmod_apply` defaults, step curve off, numbered off, compare the first string. The length choices are the `_RMS_LENGTHS` labels (`Still (1 frame)`, `22 frames (~1s)`, `39 frames (~1.6s)`, and the rest of that map). `debounce_redraw_ms` is 60 (`_rms_schedule_redraw`).

`POST /api/refmod/scan` lists visual mods in the folder via `refmod_apply.scan_refmods` (audio mods stay out). An empty folder returns no mods. The import of that module happens only when the folder contains a `.safetensors` file.

`POST /api/refmod/load` loads engine `refmod` for family `minimax`. The real adapter's plan follows `_rms_engine_plan`: ref2va uses the `ref_dit` preference, fl2va uses `dit`, plus the video VAE, the text encoder, the speed LoRA at turbo strength 0.75, and the base mode (`stream`, `nf4`, or `auto` from the same prefixes as `_rms_base_mode`). Under the fake flag the load args are the paths only.

`POST /api/refmod/render` sends the setup and a `gen`. The page posts on Render. It waits 60 ms before it swaps the shown image (`_rms_schedule_redraw`). A higher `gen` cancels the render in flight. Early look matches `_rms_job`: `early_step` is 2 when early is on and steps are greater than 2, otherwise 0. The fake emits that early frame, then the with-mods image and the comparison image. `records` echoes `seed`, `prompt`, `early_step`, `compare`, and the row list. The real adapter builds the bundle with `refmod_apply.build_bundle_entries` and calls `render_refmod`, including the no-mod, no-LoRA, and neither comparison (`_rms_render`).

`GET /api/refmod/presets` lists `presets/refmod_studio/*.json` (`FIZGIG_WEB_PRESET_ROOT` when that is set). `PUT /api/refmod/presets` writes one file with `json` indent 2, the object `_rms_state` writes: `base`, `model`, `prompt`, `seed`, `frames`, `width`, `height`, `steps`, `turbo`, `sound`, `early`, `folder`, `rows` (`on`, `mod`, `value` rounded to 3 decimals, `copies`), `retention`, `scramble`, `frame_curve`, `step_curve`, `step_on`, `numbered`, `lora`, `compare`. Seed, frames, width, height, steps, turbo, and scramble are the widget strings (`300`, `22 frames (~1s)`, `640`, `768`, `4`, `1.0`, `-1`), not parsed numbers. Retention is a float. `GET /api/refmod/presets/file?name=` reads that object back (`_rms_setup_save`, `_rms_setup_load`).

### LoRA the Explorer

The mutation loop lives in `src/fizgig/web/explorer.py` as `roll_variants`. It mirrors `_explorer_generate_baseline_and_roll` and calls `SliderState.mutate`. It does not reseed. Variant 1 and 2 use the structure value. Variant 3 uses structure 0. Variant 4 drops the last pick's blocks when at least two candidates remain, and otherwise uses the full active set. Active blocks are the LoRA's blocks minus the frozen set, and the anchor is added back when it is not frozen (`_explorer_anchor_block`: the family's first block).

`GET /api/explorer/form?family=` is the setup: families with `explorer` in the workbench, LoRA, prompt, reference, reference MP, reference strength, seed `42`, resolution `512` (choices `256`, `384`, `512`, `768`), intensity `0.964`, mutations `8`, structure `1`. `debounce_ms` is 750 (the intensity and structure sliders).

`POST /api/explorer/load` loads engine `explorer` and the LoRA, and starts a baseline `SliderState` for that family with the strength on `primary_scale` (`_explorer_apply_strength`).

`POST /api/explorer/roll` syncs prompt, seed, resolution, and reference into the baseline, builds four variants, and renders. The host params are `states`: the baseline JSON, then the four variants. The fake emits one frame per state (`baseline`, then `variant`) and puts the same states on `records`. A higher `gen` cancels the roll. The page waits 750 ms after an intensity or structure edit before it sends.

`POST /api/explorer/pick` with `index` pushes the current baseline, its image name, and the frozen set onto the undo stack, records the blocks `diff_blocks` reports, and makes the picked variant the baseline (`_explorer_pick`). It then rolls.

`POST /api/explorer/freeze` with `choice` mirrors `_explorer_freeze_tweaked`. Tweaked means disabled or strength more than 0.01 away from 1. `choice` replaces the desktop's dialog: `freeze` locks the tweaked blocks, `add` unions them into the frozen set, `unlock` clears the set, `undo` restores the previous frozen set and baseline, `cancel` changes nothing. The frozen set is what the next roll leaves alone.

`POST /api/explorer/undo` pops the stack and restores the baseline and the frozen set (`_explorer_undo`). The page then rolls.

`POST /api/explorer/reset` with `mode` `full` unloads and clears the session (`_explorer_full_reset`). `defaults` unlocks and replaces the baseline with the family's default state. `baseline` unlocks and keeps the current blocks (`_explorer_restart`).

`POST /api/explorer/save` writes `<stem>_explored.safetensors` through `save_repaired_lora`, donor off. An existing file gets `_2`, `_3`, … The bake import stays inside the function.

Session state (baseline, variants, frozen blocks, last pick, undo stack) lives in the server process. `clear_session()` empties it. Tests call that before each case.

### LoRA Royale

`GET /api/royale/form?family=` is the setup: families with `royale` in the workbench, folder or one LoRA, prompt, seed `42`, width and height `512`, reference, max renders (`All` or a count), and the travel fields.

`POST /api/royale/scan` calls `lora_royale.scan.scan_checkpoints` on a folder. A single LoRA path is one item, `(stem, path)`. The result is `[{label, path}]`, the same pairs the scan returns. `select_epochs(items, max_renders)` is the desktop subset: `All` keeps every item; a count keeps that many, evenly spaced, always the first and the last (`_royale_render`).

`POST /api/royale/load` loads engine `royale`.

`POST /api/royale/render` renders the selected epochs on one seed. Params are `mode: "epochs"`, `seed`, `prompt`, `width`, `height`, `reference`, and `epochs`. The fake emits one frame per epoch with `side: "epoch"` and lists the labels on `records`. A higher `gen` cancels the render. The page does not contact the server while the crossfade slider moves. The slider blends the two neighbouring epoch images in the browser: the lower image is the left epoch, the upper image's opacity is the fraction between them (`Image.blend` in `_royale_scrub`).

`POST /api/royale/travel` with `mode` `seed`, `strength`, or `prompt` renders one scrubber sequence. Seed travel uses `journey_seeds`, the mirror of `_royale_journey_seeds` (same start seed, same waypoint count, same list). Strength travel ramps from start to end across the frames (`_royale_lora_travel`). Prompt travel builds the waypoint prompts with `lora_royale.prompt_travel` (`_royale_prompt_travel`). The fake emits one frame per step with `side: "travel"`. The page scrubs by index, client side (`_royale_sc_scrub`): one frame at a time, no blend request.

`POST /api/royale/export` starts a job with `kind: "royale"`. The body is the image paths already rendered, `format` `MP4` or `GIF`, `speed` (`Slow`, `Normal`, `Fast`), `pingpong`, `brand`, and `show_epoch`. The output name is `<run>-royale.mp4` or `.gif` (`run_name_for_folder`, else `lora`). The job's `command` is the argv `lora_royale.export.write_mp4` builds:

```
ffmpeg -y -loglevel error -f rawvideo -pix_fmt rgb24 -s WxH -r FPS -i - -an -c:v libx264 -pix_fmt yuv420p -crf 18 -preset medium -movflags +faststart OUTPUT
```

`W` and `H` are the even dimensions `_even` produces (minimum 2). `FPS` is the speed preset's third value (Normal is 22). `ffmpeg_command(binary, width, height, fps, path)` returns that list. Under `FIZGIG_WEB_FAKE_ENGINE=1` the runner records the command and writes the output file without starting ffmpeg. Otherwise the runner calls `build_frames` and `write_mp4` (or `write_gif`). The export job does not load a model. It still uses the job folder and refuses to start while an engine is loaded, the same rule as the other jobs.

### Mirror pins

`checks/test_web_mirrors.py` also hashes `create_refmod_studio_tab`, `_rms_state`, `_rms_setup_save`, `_rms_setup_load`, `_rms_job`, `_rms_render`, `_rms_show_early`, `_rms_schedule_redraw`, `create_explorer_tab`, `_explorer_generate_baseline_and_roll`, `_explorer_worker`, `_explorer_pick`, `_explorer_freeze_tweaked`, `_explorer_undo`, `_explorer_save`, `_explorer_restart`, `_explorer_full_reset`, `create_lora_royale_tab`, `_royale_scan`, `_royale_render`, `_royale_render_worker`, `_royale_scrub`, `_royale_export`, `_royale_export_worker`, `_royale_journey_seeds`, `_royale_seed_travel`, `_royale_lora_travel`, `_royale_prompt_travel`.

### Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py"`

65 tests, 63 passed, 2 skipped, 0 failed. Three runs in a row, same counts each time (236.676s, 236.24s, 246.29s). The two skipped tests are the golden tests. The new tests use the fake engines registered for `refmod`, `explorer`, and `royale`: each tool's render through the host, newest-gen cancellation, the RefMod preset round-trip in the desktop setup shape, Explorer `roll_variants` against the same `SliderState.mutate` loop on fixed seeds, freeze and undo state, the Royale epoch scan against `scan_checkpoints`, and the export job's ffmpeg argv against `write_mp4`.

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

2 tests, passed (9.759s).

`npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

### Gaps

- Likeness scoring stays on the desktop. It needs the face embedder.
- The RefMod sweep, the render-history strip, and curve-preset files stay on the desktop.
- Explorer does not hand the baseline to Repair Studio. The desktop's Refine button stays there.
- Royale's comparison sheet, promote, save-stills, and likeness clip stay on the desktop.
- The RefMod page shows the middle frame. It does not build the desktop's mp4 from the clip frames.
- Royale prompt travel on the real adapter changes the prompt for each frame. It does not interpolate prompt embeddings, and it does not chain sequential reference latents.
- A real load and render of these three tools on the GPU were not run from this page.

### Still manual (3b-ii)

- Load the H3 base from the page, render a RefMod, and compare the clip with the desktop.
- Roll the Explorer on a real LoRA and confirm one variant matches the desktop for the same seed and intensity.
- Scan a real training folder, scrub the crossfade, and export an mp4.

## No console windows

A Windows process whose parent has no console opens a console of its own unless the launch passes `CREATE_NO_WINDOW`. That flag is right for a short tool (`ffmpeg`, `taskkill`, `nvidia-smi`): `fizgig.web.procs.creationflags` returns it. The tool itself opens no window.

A training run or an engine render is different. The trainer and the engines start their own children with no flags. A parent created with `CREATE_NO_WINDOW` has no console to hand down, so Windows opens a visible console for each of those children. `fizgig.web.procs.hidden_console` avoids that. It returns `CREATE_NEW_CONSOLE` plus a `STARTUPINFO` of `STARTF_USESHOWWINDOW` and `SW_HIDE`, so the new console is never shown. A child that does not ask for its own console inherits the hidden one, and so does the rest of the tree.

The job runner is the detached case. `hidden_console(detached=True)` adds `CREATE_NEW_PROCESS_GROUP` and does not use `DETACHED_PROCESS`. `CREATE_NEW_CONSOLE` already separates the run from the server's console, and the new process group keeps a server restart or Ctrl+C from killing it. On other platforms the same call returns `start_new_session`. The runner's stage launches pass `creationflags=0` and inherit that hidden console. The engine worker uses `hidden_console()` and keeps its stdin and stdout pipes.

Every `subprocess` call under `src/fizgig/web/` passes `creationflags=` or spreads `hidden_console`. `checks/test_web_no_window.py` reads those files with `ast` and fails when a call does neither. On Windows it also starts a job through `jobs.start` and an engine through `EngineHost`, each with a stand-in that starts a grandchild with no flags. The grandchild reports `GetConsoleWindow` and `IsWindowVisible`. The test requires a console that is not visible. Off Windows that check is skipped. The checks that start a process pass `CREATE_NO_WINDOW`. The trainer, caption, profile, and extract stand-ins do not start processes of their own.
