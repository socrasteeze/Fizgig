# Web UI phase 0

**Status:** built, uncommitted. Written 2026-10-08 on commit a0a2ef6 plus this uncommitted tree. Upstream base is origin/master e198fb8.

**Result:** go for Phase 1. The spike serves one family's schema to a React page on 127.0.0.1. The Training tab still has a large set of settings the family descriptions do not declare.

## Upstream check

`git fetch origin` left origin/master at e198fb8. That tree has no `src/fizgig/web/` (the package directories under `src/fizgig/` are the model families, training, scripts, and the rest of the library).

Issue 165 is still open. The latest comment from the person building the upstream UI says a pull request is coming. `gh pr list -R shootthesound/Fizgig --state all --search "web ui"` shows two closed pull requests, 162 and 164. Nothing on origin/master is a shipped web server, so this phase continued.

## Scaffold and spike

New files only. `lora_trainer_gui.py`, `requirements.txt`, the root `.gitignore`, and the existing modules under `src/fizgig/` are unchanged.

| Path | Role |
|---|---|
| `webui/` | Vite + React + TypeScript. `package.json` pins exact versions. `package-lock.json` is in the tree. `webui/.gitignore` ignores `node_modules/` and `dist/`. |
| `webui/src/App.tsx` | Fetches `/api/schema?family=<id>` and lists that family's model files, presets, options, learning-rate hint, and advanced flags. Read-only. Colors are the desktop `COLORS` palette. |
| `src/fizgig/web/` | FastAPI app. `python -m fizgig.web` (with `src` on the path) runs uvicorn on 127.0.0.1:8081. |
| `requirements-web.txt` | `fastapi==0.143.0`, `uvicorn==0.54.0`, `httpx==0.28.1`. |
| `checks/test_web_schema.py` | The checks below. |

Frontend dependencies, exact: `react` 19.3.0, `react-dom` 19.3.0, `typescript` 5.9.3, `vite` 8.3.4, `@vitejs/plugin-react` 6.1.2, `@types/react` 19.3.0, `@types/react-dom` 19.3.0, `openapi-typescript` 7.13.0. TypeScript is 5.9.3 because `openapi-typescript` 7.13.0 asks for TypeScript 5. `npm run build` is `tsc --noEmit && vite build`. It does not generate API types yet. The page uses a local type so the build does not need a running server. `openapi-typescript` is installed for Phase 1.

`GET /api/schema?family=<id>` returns that family's `FamilyDescription` as JSON (identity, model files, presets, options, `lr_hint`, and the other description fields) plus `advanced`, the argparse options of `src/fizgig/families/train.py`. The parser is read from source. Importing `train.py` would load torch. An unknown family returns 404.

`webui/dist/` is mounted at `/` when that directory exists at process start. Build the page, then start the server. A request for `/` after this build returned 200 and the page HTML.

The server refuses any bind address other than 127.0.0.1. `serve("0.0.0.0")` raises `SystemExit` before uvicorn runs. The command line has no listen option.

Every request must send a `Host` of `localhost`, `127.0.0.1`, or the hostname in `FIZGIG_WEB_TAILNET_HOST` (port ignored). State-changing methods (`POST`, `PUT`, `PATCH`, `DELETE`) reject a present `Origin` whose hostname is outside that set. A missing `Origin` is allowed, so a non-browser client on the machine can still call the API. Browsers send `Origin` on POST.

No route reads `prefs.json`. Responses are the family description, the train.py argument list, the static page, and the ping body.

`POST /api/ping` returns `{"ok": true}`. It was added because the spike had no state-changing route, and the Origin check needs one. It does no work.

Installing `requirements-web.txt` also installed FastAPI's own dependencies, including starlette 1.7.0, pydantic 2.14.0, and opentelemetry-api 1.45.1. Already-installed packages were left in place (`typing-extensions` stayed at 4.16.0).

## Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v`

11 tests, 11 passed, 0 failed. The six new tests cover every registry family, an unknown family (404), a foreign `Host` (403), a POST with a foreign `Origin` (403), `serve("0.0.0.0")` (`SystemExit`), and the absence of `runpod_api_key` in those responses. The other five are the existing appearance and status-bar tests.

Starlette 1.7 prints a deprecation warning on import: its `TestClient` wants `httpx2`. The suite still passes on the pinned `httpx`. This phase does not add `httpx2`.

`npm --prefix webui run build` passed. `tsc --noEmit` and Vite both ran and wrote `webui/dist/` (index.html, one CSS file, one JS file).

## Tailscale

Read-only. Version 1.102.3. `tailscale status` returned a peer table, so this install is logged in. `tailscale serve` was not run with a target, and no Tailscale setting was changed.

Background publish of port 8081, from this version's help (`tailscale serve --bg 3000` is the documented background form):

```text
tailscale serve --bg 8081
```

The help does not mention an HTTPS-certificate requirement. `--https` is described as the default mode. The only certificate sentence is an example that proxies a local server which already has an invalid or self-signed certificate (`tailscale serve https+insecure://localhost:8443`).

## Schema coverage

Compared each family's `FamilyDescription` with the controls `create_training_settings` shows for that family, using `_apply_training_arch_visibility`, `_generic_training_visibility`, and `_family_edit_rows`. The desktop window was not opened.

A control counts as declared when the description carries it: a non-fixed `FamilyOption` on the training or model card, or the choice list for that control (`network_types`, `optimizers`, `precisions`, `train_areas`). Declared, and therefore not in the counts below:

- Network Type, Optimizer Type, and Base precision, for all seven (every family has more than one precision and both LoRA and LoKR).
- Model Area to Train, Klein only (`train_areas`).
- Family options on the training screen: MiniMax H3 has 21 (20 on the training tab plus Training Base on the model card), SDXL has 2, and the other five have none. MiniMax's Samples-tab option and its fixed audio-VAE option are not training-tab controls.

Everything else the function shows is undeclared. Mutually exclusive rows are counted when the family can show them: rank and alpha, and LoKR Factor; the edit, slider, and fine-tune cards when that kind exists. Actions, hints, and banners are not counted. Model Type is hidden for every described family. The LoRA LR-ratio widget is never placed. RefMod is a separate Base Model entry in the same function and is outside this table.

**Shown for every family (38).** Output Directory, LoRA Name, Learning Rate, Network Dim, Network Alpha, Max Epochs, Save Every N Epochs, Seed, LoKR Factor, Context LoRA, Context LoRA strength, Target Megapixels, Optimizer Args, Gradient Accumulation, Max Grad Norm, Caption Extension, Batch Size, Enable Bucket, No Upscale, LR Scheduler, Warmup steps, Attention Mechanism, Logging Directory, Log With, Log Prefix, Metadata Title, Metadata Author, Metadata Description, Metadata License, Metadata Tags, Metadata Trigger Phrase, Metadata Thumbnail, Blocks Swap, Resume Training, Save State at each checkpoint, Save State at end, Keep Last, Enable Cache Preparation.

**Also shown for every family (16),** because every family has slider training, a fine-tune, and an EMA default. Kind of training. Slider: source (photo pairs or prompts), the -1 folder, shared caption, prompt base, the +1 words, the -1 words, push strength. Fine-tune: rotations, checkpoint interval, epochs per part, window size, free-each-gradient, regularisation folder, regularisation LR multiplier. Weight averaging (EMA).

That shared set is 54. Of those, 39 have a `train.py` flag and would fall under Advanced. 15 have no flag: Target Megapixels, Caption Extension, Batch Size, Enable Bucket, No Upscale, Attention Mechanism, Logging Directory, Log With, Log Prefix, Enable Cache Preparation, Kind of training, slider source, the slider -1 folder, slider caption, and the fine-tune regularisation folder.

Per-family additions, then the total:

| Family | Additions beyond the shared 54 | Not declared | Advanced | No train.py flag |
|---|---|---:|---:|---:|
| Klein 9B | Adaptive LR, Min LR, Max LR, Detect problem images, Per-image adaptive LR, Warm up look outliers, Compile Blocks, edit originals folder, edit caption, edit test photo, Timestep min, Timestep max | 66 | 49 | 17 |
| MiniMax H3 | Multi Concept, Subject 2 folder | 56 | 39 | 17 |
| Krea 2 | Adaptive LR, Min LR, Max LR, Detect problem images, Per-image adaptive LR, Warm up look outliers, Compile Blocks, Ultra mode | 62 | 47 | 15 |
| Qwen Image 2.1 | Adaptive LR, Min LR, Max LR, Detect problem images, Per-image adaptive LR, Warm up look outliers, Compile Blocks, edit originals folder, edit caption, edit test photo, Training adapter, Fast Identity Mode | 66 | 49 | 17 |
| SDXL | Detect problem images, Per-image adaptive LR, Warm up look outliers, Compile Blocks | 58 | 43 | 15 |
| Anima | Adaptive LR, Min LR, Max LR, Detect problem images, Per-image adaptive LR, Warm up look outliers, Compile Blocks | 61 | 46 | 15 |
| Z-Image Turbo | Adaptive LR, Min LR, Max LR, Detect problem images, Per-image adaptive LR, Warm up look outliers, Compile Blocks, Training adapter | 62 | 47 | 15 |

Two further controls stay out of the counts because a file on disk decides whether they appear. Auto-recaption (`--auto_recaption`) is drawn for every family with the loss watch (all except MiniMax) only when the captioner path is set. Clip Target Megapixels is drawn for MiniMax only when the dataset contains a clip. Neither is a description field.

Reference strength (Klein) and the preview-image path (Krea 2) are not in `create_training_settings`. They belong to other tabs.

## Phase 1

**Go.** The spike, the tests, the build, and the coverage count are in place. Phase 1 should start from the generated form, not from a second scaffold.

Top three risks:

1. **Schema gap.** Five families declare no training options. A form built only from `FamilyOption` would miss 56 to 66 settings on this tab. About 15 of those (17 for Klein, Qwen Image 2.1, and MiniMax) are not `train.py` flags, so an Advanced section of argparse options still misses megapixels, batch, buckets, cache, the edit folders, and Multi Concept.
2. **`plan()` is still uncalled.** Nothing in the tree calls `launch.plan()`. Phase 1 needs the golden test before a launch button starts a run.
3. **Tailscale is unproven here, and upstream may still land a server.** `tailscale serve --bg 8081` is the command this version documents, and it was not run. The help does not mention the admin HTTPS-certificate switch, so the first real publish can still fail on that. Issue 165 is open and its builder still expects to open a pull request. A later sync that adds `src/fizgig/web` has to stop for a decision before this fork's server is merged with it.
