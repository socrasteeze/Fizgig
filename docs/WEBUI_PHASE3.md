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
