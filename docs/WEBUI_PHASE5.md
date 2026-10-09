# Web UI phase 5

Phase 5 is how the server is started, and one queue per GPU. Phase 4 jobs, the detached runner, the GPU lock, and the page stay as they are. Nothing in this phase starts Fizgig, or anything else, on its own.

The server runs only when you run `run_webui.bat` or `run_webui.sh`, or start the Docker container. A queue may start the next training job it already holds. There is no scheduled task, no startup shortcut, no service, and no systemd unit. That decision is row 7 in `docs/WEBUI_SCOPE.md` (2026-10-09).

## Launcher

`run_webui.sh` follows `run_webui.bat`. It puts `src` on `PYTHONPATH`, uses the venv Python when that file is present, rebuilds `webui/` when a source file is newer than `webui/dist/index.html`, and runs `python -m fizgig.web`. The server still refuses any bind except `127.0.0.1`.

## Docker

New files live under `docker/webui/`. `docker/Dockerfile` and `docker/entrypoint.sh` are unchanged.

`docker/webui/build.sh` builds the existing Dockerfile as `fizgig:desktop` when `BASE_IMAGE` is unset, then builds this image on top of it. `ARG BASE_IMAGE` defaults to `fizgig:desktop`.

The image builds the page in a Node stage (`tsc --noEmit` and `vite build`). It does not run `npm run build`, because that script refreshes API types with the repo venv. A local `npm run build` still does that check. The final stage copies `src/`, the built page, and `requirements-web.txt` onto the Fizgig image, and copies the Tailscale binaries in. It does not declare `EXPOSE`. Docker still inherits the base image's port list, and there is no way to clear that. Do not map the pod template's public 8081 port. The process listens on `127.0.0.1:8081` only.

The entrypoint starts `tailscaled` in userspace-networking mode with state under `/var/lib/tailscale` (override with `TS_STATE_DIR`). It logs in with `TS_AUTHKEY` when that is set, or with a non-empty `tailscaled.state` when it is not. It runs `tailscale serve --bg 8081`, then `python3 -m fizgig.web`. If the key is unset and there is no saved state, it prints a refusal and exits. It does not call Tailscale Funnel and it does not restart a failed process.

The image was not built here. The entrypoint was run under bash with stub `tailscale`, `tailscaled`, and `python3` binaries.

## One queue per GPU

`src/fizgig/web/devices.py` lists visible CUDA devices without importing torch. It uses `pynvml` when that imports, otherwise `nvidia-smi` (a short tool, so the launch passes `creationflags()`), otherwise `[0]`. `CUDA_VISIBLE_DEVICES` narrows a successful probe to the integer indices it names.

Each job and each queue item stores `device` (default 0). `GET /api/devices` returns the list. The training form has a GPU picker. The queue page shows one list per GPU.

The runner sets `CUDA_VISIBLE_DEVICES` to that job's index and takes `GpuLock` for the same index. Jobs on different devices may run at once. Jobs on one device do not overlap. A finish on one device starts that device's next training item and leaves the other device's queue alone. The desktop app is unchanged.

The engine host uses one device, default 0. `POST /api/engine/device` sets it when no engine is loaded. The worker is started with that `CUDA_VISIBLE_DEVICES` and locks that device. The workbench pages do not grow a second picker.

## Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py"`

103 tests, 101 passed, 2 skipped, 0 failed. Three runs in a row, same counts each time (163.468s, 158.956s, 157.624s). The two skipped tests are the golden tests. The new tests use fakes. They do not load a model, call a real `nvidia-smi`, build an image, or change Task Scheduler. They cover two devices running together, the lock and `CUDA_VISIBLE_DEVICES` on each job, a second job on a busy device refused, each device's queue advancing on its own, detection falling back to `nvidia-smi` and then to one device, the engine host locking the device it was given, `run_webui.sh` naming only `127.0.0.1`, the Docker entrypoint refusing to start without a key or saved state, and no autostart text in the web files.

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

2 tests, passed (10.013s).

`npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Gaps

- The workbench device is an API call. The Repair, RefMod, Explorer, and Royale pages do not show a picker.
- The web image was not built or run. Tailscale was not logged in, and `tailscale serve` was not run on this machine.
- The base image's `EXPOSE` list is inherited. The new Dockerfile does not add a port, and the entrypoint does not listen on a public address.

Desktop-only gaps from phases 1–4 are collected in `docs/WEBUI.md`.

## Still manual

- Train a built-in preset from the page, close the browser, reopen it, and confirm the log, progress, and samples.
- Open the page from a phone at the `tailscale serve` address. HTTPS certificates for the tailnet must be on. Set `FIZGIG_WEB_TAILNET_HOST` to the machine's tailnet name.
- Record from a phone and confirm the wav lands in the dataset folder. Run Whisper on a real take. Cut a real clip. Diff two real checkpoints and load one written LoRA.
- Import a real desktop queue, caption with Florence or Qwen, run a real face crop, and confirm a browser notification.
- Load a real family, move a Repair slider, run Quick, and save a baked file. Render RefMod, roll Explorer, and export a Royale mp4.
- On two GPUs, run one job on each at the same time, and confirm a second job on one GPU waits.
