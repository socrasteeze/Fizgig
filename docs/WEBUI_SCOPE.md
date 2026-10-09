# Web UI scope

**Status:** scope only, nothing built. Written 2026-10-08 against commit e677fbc. Line numbers drift; function names are the stable reference.

**Goal:** Fizgig runs as a service on the GPU machine (desktop, LAN box, Docker, or RunPod), and you drive it from any browser. Jobs keep running when the browser closes; you open it from any device on your Tailscale network, rejoin, and see live logs, samples, and a notification when a run ends. This is the model ostris/ai-toolkit, ComfyUI and Synology DSM use.

**Track:** fork-only (decided 2026-10-08). Nothing is offered upstream. The fork keeps syncing from upstream, so the design has two jobs: work well, and survive every sync without merge conflicts.

**Short answer:** this is feasible without rewriting the trainer. Everything in `src/fizgig` already runs without Tk, and training is already a subprocess. The work is (1) a Python server and a React page whose forms are generated from Fizgig's own model descriptions, (2) a job supervisor in the server, and (3) a GPU host process for the interactive workbench tools. Sized as one experienced engineer's time, a training launcher and monitor is 5-8 weeks and full parity with all 13 tabs, Gizmo and the converter is 16-28. Those numbers measure size, not calendar time for agent-built work.

## Decisions

| # | Decision | Status / recommendation | Why |
|---|---|---|---|
| 1 | Upstream or fork | **Decided: fork-only** | — |
| 2 | Coordinate with upstream issue #165 | **Decided: no.** Only watch upstream on each sync for a `src/fizgig/web` landing. | If upstream ships its own web server, a sync brings it in; decide then whether to switch to it. |
| 3 | Keep the Tk app | **Decided: yes, as an alternative.** It stays as it is. | Edits to `lora_trainer_gui.py` conflict on nearly every upstream sync: it changed in 18 of the last 20 releases. |
| 4 | Access and login | **Decided: no login; reach it over Tailscale.** The server listens on `127.0.0.1` only, and `tailscale serve 8081` publishes it to your tailnet over HTTPS. | Tailscale already decides which devices get in, so a password would only duplicate it. Listening on localhost only means the server is never reachable from the LAN or the internet by accident. |
| 5 | Server | **Decided: Python with FastAPI + uvicorn**, in a new `requirements-web.txt` | The server must be Python: the trainer, the model descriptions, `launch.plan()`, the progress parser and the workbench engines are all Python. A Node server would have to hand every one of those calls to a Python process anyway. FastAPI is the most widely used async Python framework, so streaming logs is cheap and agents know it well. The separate requirements file leaves upstream's `requirements.txt` untouched. |
| 6 | Frontend | **Decided: React + TypeScript, built with Vite (npm)** into static files that FastAPI serves | 13 tabs of interactive UI need real components and state. TypeScript gives agent-written code a compile check on every change, and types generated from FastAPI's API description keep the page and server in step. Node runs only for the build, never in production. Forms are still generated from `/api/schema`, so each upstream sync's new families and options appear without hand edits; hand-written forms drift, which is why upstream closed PR #164. |

## Keeping the fork mergeable

These rules are what make fork-only cheap to maintain:

1. **New code goes in new files only:** `src/fizgig/web/` (server), `webui/` (React source, `package.json`, its own `.gitignore` for `node_modules` and `dist`), `requirements-web.txt`, `run_webui.bat`, `docs/WEBUI_*.md`, and `checks/test_web_*.py`. New files never conflict.
2. **The server never imports `lora_trainer_gui.py`.** It calls `src/fizgig` modules (`families.launch`, `families.description`, `training.progress`, the workbench engines), which upstream keeps stable for its own CLI.
3. **The desktop app gets one change at most:** a GPU-lock check at the start of a run, a few lines in `start_training`. Everything else in it stays untouched.
4. **Logic that exists only inside GUI methods is mirrored, not moved.** Examples are Image Prep and the LoRA the Explorer mutation step. Mirroring copies the logic into `src/fizgig/web/` with a comment naming the GUI function it mirrors. Moving it would mean editing upstream's hottest file.
5. **Every mirror is pinned by a test.** `checks/test_web_mirrors.py` stores a hash of each mirrored GUI function's source. When an upstream sync changes one, the test fails and points at the mirror to update. Drift becomes a failing check instead of a silent bug.

## Upstream context (PR #164, issue #165)

Upstream doesn't bind this fork any more, but its history still informs the design.

- **PR #164, closed 2026-09-29:** a 14k-line hand-written Next.js front end. Every desktop change had to be redone by hand, and it had already fallen behind (no Qwen Image 2.1, edit LoRAs or RefMods). An automated review of it found an unauthenticated endpoint that exposed the auth token and the RunPod key.
- **Issue #165, open:** the maintainer's preferred shape matches this scope:
  - `/api/schema` from family descriptions, with argparse flags under Advanced
  - preset chips, a live log and a sample gallery
  - port 8081, login required, localhost-only on a desktop
  - pause/resume through `.pause_requested` and `--resume`
  - the desktop look

  A contributor said on 2026-10-03 it was "almost complete", but there is no PR and no `src/fizgig/web` upstream.
- **Merged foundation:** `src/fizgig/families/launch.py` and `checks.py` (2026-09-29). `launch.plan(desc, inputs)` returns the dataset TOML, the ordered stage commands, folders and files to create, and problems. The maintainer says it matches the desktop byte for byte. The caller still owns: one run at a time, clearing a stale `.pause_requested` and `.sample_override.json`, and the low-disk and resume-at-max-epochs warnings.
- **Also reusable:** `src/fizgig/training/progress.py` (`TrainingProgressTracker`, from #138) parses tqdm progress and loss from stdout.

## What exists today

| Area | State | Where |
|---|---|---|
| Family schema | 7 families described: Klein, MiniMax H3, Krea 2, Qwen Image 2.1, SDXL, Anima, Z-Image Turbo. Descriptions carry model files, presets, `lr_hint`, options, sampling, workbench block maps. | `src/fizgig/families/description.py` (`FamilyDescription`), `registry.py` |
| Generated from schema | Preferences sections, family options, presets, Samples wording, Training-tab visibility, Repair sliders, Extract block picker | `_generic_prefs_section`, `DESCRIBED_FAMILIES` |
| Hand-built | `create_training_settings` (about 1,300 lines), Repair, Royale, RefMod and Explorer UIs | `lora_trainer_gui.py` |
| Training launch | Desktop calls the shared builders (`train_command`, `cache_command`, `dataset_toml`), not `plan()`. `plan()` has no callers, not even tests. Inputs are scraped from widgets. | `_family_launch_inputs`, `_generic_train_command`, `validate_inputs` |
| Run supervision | One `current_process` slot; three subprocesses chained by callbacks (latent cache, text cache, train); stdout piped to the console | `start_training`, `_start_training_launch`, `run_subprocess` |
| Stop / pause | Stop: `taskkill /F /T` or `killpg`. Pause: `.pause_requested`, state in `.fizgig_paused.json`. | `stop_training`, pause/resume handlers |
| Queue | `presets/training_queue.json`, but items replay through the widgets before starting | `_start_next_queued`, `_apply_queue_item` |
| Samples | Trainer writes PNGs to `<output>/sample`. A stdlib `http.server` gallery on 127.0.0.1 already serves them to the system browser. | `update_gallery_html`, the gallery server |
| Override next sample | `<output>/.sample_override.json`, read by the trainer at each preview | status-bar panel; `families/train.py` |
| Headless CLI | `families/cache.py` and `families/train.py` for every family (`docs/CLI.md`); scripts for extract, profile, captioning, fetch models | `src/fizgig/scripts/` |
| Docker / RunPod | KasmVNC streams the Tk app on 6080; filebrowser on 8080; 8081 reserved for a "run monitor" that doesn't exist | `docker/Dockerfile`, `docker/entrypoint.sh` |
| Workbench engines | Plain Python classes held as single GUI attributes (10-20 GB each), unloaded on tab change, guarded by busy flags | `repair_engine`, `royale_engine`, `_explorer_engine`, ... |

The desktop app can't serve as the server's engine: it allows one run at a time, its queue replays settings through widgets, and its engines belong to whichever tab is showing. The server needs its own versions of all three.

## Architecture

**Server (`src/fizgig/web/`, `python -m fizgig.web`).** The server owns the GPU, the job queue and the files. The browser is a thin client.

- **Jobs live on disk, not in server memory.** Each run gets a job folder holding `job.json` (id, family, inputs, status, pid, step, total, timestamps, flags), `log.txt` and the samples. Runs start detached, so a server restart or crash doesn't kill training; on start the server reattaches by pid. This is ai-toolkit's approach. ComfyUI keeps its queue in memory and loses it on restart.
- **Launch path:** queue item = family id + the inputs dict → `launch.plan()` → stages run in order by the server's job supervisor. No widgets anywhere in the path.
- **Job supervisor (new, `src/fizgig/web/jobs.py`).** Covers what `start_training`, `run_subprocess`, pause/resume/stop and queue advance do on the desktop, written against `plan()`, with the caller duties listed above. It's a mirror (rule 4): it names the desktop functions it follows, and the mirror test pins them.
- **One GPU lock across processes.** A lock file per GPU set, held by whoever is training or holding an engine: desktop app, server, or a CLI run. Without it the Tk app and the server can start two runs on one card. This is the desktop's one change (rule 3).
- **Engine host for the workbench.** A worker process owns at most one engine (Repair, RefMod, Explorer, Royale, Profiler). It takes render requests, cancels the one in flight when a newer one arrives (as the debounced sliders do now), and unloads when idle or before training.
- **Live data:** SSE for log lines, progress, GPU/RAM stats and job events; plain GET for images. FastAPI also offers websockets if a workbench tool proves it needs two-way streaming. The client rejoins by job id: it fetches the tail, then reads by byte offset.
- **Control through files the trainer already reads:** `.pause_requested`, `.sample_override.json`, `--resume`. The trainer needs no changes.

**Page (`webui/`).** A React + TypeScript single-page app built by Vite into `webui/dist/`, which FastAPI serves as static files. `run_webui.bat` rebuilds it when the source is newer than the build, then starts the server; Docker builds it in a separate build stage. TypeScript types for the API are generated from FastAPI's OpenAPI description, so a server change that breaks the page fails the build. Forms render from `/api/schema`: family description first, Advanced (argparse) collapsed, presets as chips. Colors come from `COLORS` through the schema endpoint, so there's one palette. Tabs mirror the desktop's 13. A top bar has the DSM-style pieces: a job and task center, notifications (run finished, failed, paused, sample ready), and the VRAM/RAM bars from the status bar.

**Files in a browser.** Native folder pickers don't exist remotely. A server-side folder browser is limited to configured roots (datasets, outputs, models), with dataset upload (drag-and-drop) and LoRA download. On the pod, link to the existing filebrowser instead of rebuilding it.

**Access and safety.** There's no login. Tailscale is the gate, so the server's job is to never be reachable any other way:
- Listen on `127.0.0.1` only. The server refuses to start on any other address; there's no `--listen` option.
- Other devices reach it through `tailscale serve 8081`. That gives an HTTPS address of the form `<machine>.<tailnet>.ts.net`, requires HTTPS certificates turned on in the tailnet admin, and follows your Tailscale access rules. Never use `tailscale funnel`, which publishes to the public internet.
- Check `Host` and `Origin` on every state-changing request, allowing only `localhost`, `127.0.0.1` and this machine's own tailnet name. Without a login, this is what stops a web page open in your own browser from sending commands to `127.0.0.1:8081`; ComfyUI does the same.
- Resolve every path and reject anything outside the configured roots.
- Never serve `prefs.json` raw: it holds `runpod_api_key` in plain text, and everyone on the tailnet can reach the server.
- RunPod: the pod template publishes 8081 through RunPod's public proxy, which would put an unauthenticated server on the internet. In Docker, don't expose 8081; run Tailscale inside the container and use `tailscale serve` there too.

## Phases

Sizes are one experienced engineer's time; agent-built speed differs. GPU time for smoke runs is extra. Each phase ends with its acceptance checks automated in `checks/`.

| Phase | Delivers | Main work | Size |
|---|---|---|---|
| 0 | Go/no-go | Confirm upstream still has no `src/fizgig/web`; set up Node.js and the `webui/` Vite project; check `tailscale serve` works on this Windows machine; measure what each family's description covers versus the hand-built Training tab; spike `/api/schema` for one family | 2-4 days |
| 1 | Training launcher and monitor | Server on localhost with Host/Origin checks, React app and build, API types, schema endpoint, generated form with preset chips, job folders, job supervisor, `plan()` launch, SSE log and progress, sample gallery, pause/resume/stop, override next sample, GPU lock, VRAM/RAM bars, mirror test | 5-8 weeks |
| 2 | The workflow before training | Persistent queue of widget-free items, job history, notifications, folder browser and upload, Start tab, Captions (`batch_caption.py --serve` is already a subprocess), Image Prep (mirrored) | 3-5 weeks |
| 3a | Batch tools | Profiler, Extract, Metadata, Samples settings | 2-3 weeks |
| 3b | Interactive workbench | Engine host process; Repair Studio (debounced sliders, early-step frames, clip player as `<video>`), RefMod Studio, LoRA the Explorer (mutation mirrored), LoRA Royale (the crossfade runs in the browser) | 6-10 weeks |
| 4 | Side tools | Gizmo (ffmpeg clip cutting, recording in the browser, Whisper, scene chop; 5,275 lines of Tk) and the checkpoint-to-LoRA converter | 3-5 weeks |
| 5 | Running as a service | Windows autostart, a Linux systemd unit, a Docker service mode with Tailscale inside the container (can replace KasmVNC on pods), one queue per GPU set | 1-2 weeks |

## Acceptance checks

**Phase 1** is done when all of these hold:
- From a phone on the tailnet, at the `tailscale serve` address, you can start a run for a built-in preset, close the browser, reopen it and see the live log, progress and new samples.
- Restarting the server mid-run doesn't stop training, and the job reattaches with its log and progress intact.
- Pause, resume, stop and override next sample behave as they do in the desktop app.
- A golden test shows `plan()` produces the same commands, dataset TOML and files as the desktop launch for every family's built-in presets.
- The server refuses to start on a non-loopback address. A state-changing request with a foreign `Origin` or `Host` is rejected. A path outside the roots is rejected. `prefs.json` secrets never appear in any response.
- `npm run build` (including the TypeScript check) passes, and a deliberate API change that the page doesn't match fails it.
- With the desktop app training, the server refuses to start a second run on that GPU, and the reverse also holds.
- `git diff` against upstream shows no change to `lora_trainer_gui.py` beyond the GPU-lock call, and none to `requirements.txt`.
- The mirror test passes, the existing `checks/` pass, and the desktop app launches unchanged.

**Later phases:** each tab does what the desktop tab does, from the browser, with the same outputs. Repair sliders show a first frame within the desktop's latency for the same GPU.

## Out of scope

- Contributing any of this upstream.
- Rewriting or retiring the Tk app, or refactoring `lora_trainer_gui.py`.
- Multiple users or roles.
- Distributed multi-GPU training; one job per GPU set is in scope (Phase 5).
- Any way in other than Tailscale: LAN binding, port forwarding, public proxies, Tailscale Funnel.
- A login screen.
- A hosted or cloud service.

## Risks

- **Upstream drift.** Each sync can change a family, a builder, or a GUI function the server mirrors. The golden test catches launch changes and the mirror test catches mirrored logic. Run both after every sync.
- **Schema coverage.** Any setting that lives only in `create_training_settings` and not in a `FamilyDescription` ends up under Advanced, or is missing. Phase 0 measures the gap per family.
- **`plan()` is unproven in production.** Nothing calls it today. The golden test in Phase 1 is the gate.
- **Two front ends at once.** The desktop app and the server compete for the GPU unless the lock lands in Phase 1.
- **Windows process control.** Detached runs must leave the server's process tree (ai-toolkit uses a relay), and stop has to kill the whole tree.
- **Memory.** Engines are 10-20 GB each. The engine host must hold one at a time and refuse workbench work while a run trains.
- **Everyone on the tailnet can drive it.** With no login, any device or shared user on your tailnet can start runs and read your datasets. Keep the tailnet personal, or limit the machine with Tailscale access rules.
- **Node dependencies.** npm packages need occasional updates. Pin them with `package-lock.json` and keep the dependency list short (React, Vite, TypeScript, an OpenAPI type generator).
- **Agent-built code.** Without a reviewer reading every diff, the automated acceptance checks are the safety net. A phase isn't done until its checks run in `checks/` and pass.

## Sources

- Upstream: https://github.com/shootthesound/Fizgig/pull/164#issuecomment-5892572398, https://github.com/shootthesound/Fizgig/issues/165, comments 5899477984 (requirements) and 5901833974 (`launch.py` announcement).
- ai-toolkit UI: https://github.com/ostris/ai-toolkit/tree/main/ui (`cron/worker.ts`, `cron/actions/startJob.ts`, `src/middleware.ts`, `hooks/usePollLoop.tsx`).
- ComfyUI: https://github.com/Comfy-Org/ComfyUI (`server.py`, `execution.py`).
- kohya_ss: https://github.com/bmaltais/kohya_ss. Forge: https://github.com/lllyasviel/stable-diffusion-webui-forge.
- Synology DSM help: https://kb.synology.com/en-ca/DSM/help.
- Tailscale Serve: https://tailscale.com/kb/1312/serve.
