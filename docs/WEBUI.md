# Fizgig in a browser

The page talks to a server on this machine. The server listens on `127.0.0.1:8081` only. Other devices reach it through Tailscale Serve.

Nothing starts Fizgig on its own. There is no scheduled task, no startup shortcut, no service, and no systemd unit. The server runs only while `run_webui.bat`, `run_webui.sh`, or the Docker container is running. The queue starts the next job it already holds from a thread inside the running server, including while the browser is closed. Opening the page does not start a job. A failed run does not start the next one. A training job that has already started keeps running if you close the browser.

Blank model paths, the cache folder, and the captioner are filled from Preferences when a run starts. The Training page shows the saved model paths for the family and reads them again each time you open the tab. A path you type or browse there is sent with the run. A path you leave alone comes from Preferences when the run starts. The Captions trigger word is saved when you leave its box. A later training launch uses it for the Metadata trigger phrase when that field is blank. Advanced flags are shown for reference and are not sent.

## First run

You need the Fizgig folder, its `venv` (the folder the desktop install makes, such as `install_fizgig.bat` on Windows), and Node.js (the launcher builds the page).

Install the web packages into that `venv`, not into whatever `pip` is on PATH. When the `venv` exists, the launchers and the build's API check use its Python. Then start the page.

Command Prompt:

```
venv\Scripts\python -m pip install -r requirements-web.txt
npm --prefix webui ci
run_webui.bat
```

PowerShell:

```
.\venv\Scripts\python -m pip install -r requirements-web.txt
npm --prefix webui ci
.\run_webui.bat
```

sh:

```
venv/bin/python -m pip install -r requirements-web.txt
npm --prefix webui ci
sh run_webui.sh
```

If the launcher stops with `ModuleNotFoundError: No module named 'fastapi'`, the packages went into a different Python. Run the install line for your shell again.

The launcher rebuilds `webui/` when a source file is newer than the last build, then starts the server. Open `http://127.0.0.1:8081`.

On Windows 11, if Windows Terminal is the default terminal app, a hidden console may still flash. Set the default terminal to Windows Console Host if windows appear.

## Tailscale

On the GPU machine, with Tailscale logged in and HTTPS certificates turned on for the tailnet:

```
tailscale serve --bg 8081
```

That publishes `127.0.0.1:8081` to your tailnet over HTTPS. The address looks like `https://<machine>.<tailnet>.ts.net`. Use that command only. Do not use Tailscale Funnel, and do not publish port 8081 any other way.

The server checks the `Host` header. Set this before you start the launcher, using the machine's tailnet name (no `https://`).

Command Prompt:

```
set FIZGIG_WEB_TAILNET_HOST=<machine>.<tailnet>.ts.net
```

PowerShell:

```
$env:FIZGIG_WEB_TAILNET_HOST='<machine>.<tailnet>.ts.net'
```

sh:

```
export FIZGIG_WEB_TAILNET_HOST=<machine>.<tailnet>.ts.net
```

`localhost` and `127.0.0.1` are always allowed. A browser on another device is allowed when that name matches. The server strips a trailing dot on the Host header.

## Docker

The web image is separate from the desktop image. Build it from the Fizgig folder. With no `BASE_IMAGE` set, `docker/webui/build.sh` first builds `docker/Dockerfile` as `fizgig:desktop`, then layers the web server on it:

```
sh docker/webui/build.sh
```

To layer onto an image you already built:

```
BASE_IMAGE=<name> sh docker/webui/build.sh
```

Run the container with a Tailscale auth key and a volume for Tailscale state. Give it the same GPU access you give the desktop image. Do not publish port 8081. On a pod, leave the template's public 8081 mapping unused. The container refuses to start when `TS_AUTHKEY` is unset and `/var/lib/tailscale/tailscaled.state` is missing.

Inside the container, `tailscaled` runs in userspace-networking mode, logs in with `TS_AUTHKEY`, runs `tailscale serve --bg 8081`, then starts the web server on `127.0.0.1:8081`. A later start can omit the key when the state volume still holds a login.

The entrypoint sets `FIZGIG_PREFS_FILE` to `/workspace/prefs.json` and `FIZGIG_WEB_ROOTS` to `/workspace` when you did not set them, so a first start has a preferences file and a folder root. Mount `/workspace` for datasets and preferences.

The entrypoint sets `FIZGIG_WEB_TAILNET_HOST` from `tailscale status --json` (`Self.DNSName`, trailing dot removed) when you did not set it. To set the name yourself, use the same assignments as in the Tailscale section above.

## Where files go

Paths are relative to the Fizgig folder. In the web image that folder is `/opt/fizgig`.

| What | Where |
|---|---|
| Job record | `cache/web_jobs/<job id>/job.json` |
| Log | `cache/web_jobs/<job id>/log.txt` |
| Queue | `cache/web_jobs/queue.json` |
| Samples | `<LoRA output folder>/sample/` |
| Tailscale state (Docker) | `/var/lib/tailscale` |

Deleting a job record removes that job folder. Training files stay in the output folder.

## GPUs

The training form has a GPU picker. Each GPU has its own queue. A run on one GPU does not wait for a run on another. Two runs do not share one GPU. The workbench (Repair, RefMod, Explorer, Royale, Quick, Thorough) uses one GPU. That is GPU 0 until you choose another with `POST /api/engine/device` while no engine is loaded.

## Still desktop-only

- These training fields do not change the launch: Attention Mechanism, Logging Directory, Log With, Log Prefix. LoRA LR ratio stays 1. The image/text offload switch is not on the form.
- A fine-tune resume does not point the model file at the checkpoint.
- Bilingual caption translation, the Look filter, per-task Qwen instruction presets, and find-and-replace across captions.
- Sample settings the launcher does not read: every N steps, the reference image, flow shift, and frame count. The page does not keep a separate sample box per family.
- Metadata has no custom-field editor and no Save As.
- Likeness and bleed scores. Quick and Thorough measure how much the picture changes.
- The H3 ref2va checkpoint picker, the render library, and clips with no LoRA.
- A repaired LoRA is baked by the loaded engine's save_repaired. save_repaired_lora is only the fallback when that engine has no save_repaired, and a family that fallback cannot map is refused.
- Without ffmpeg, a video render keeps the middle frame.
- The RefMod sweep, the render-history strip, and curve presets. The page shows the middle frame.
- Explorer does not send its baseline to Repair Studio.
- Royale's comparison sheet, promote, save-stills, and likeness clip. Prompt travel does not blend embeddings or chain reference latents.
- Gizmo does not draw a crop. Prompted sentences, delivery, and the push-to-talk cushions stay on the desktop. Whisper runs on the CPU. A video caption file is written only when the page sends the text.

## Still manual

These need a real GPU or a phone. The automated checks use fakes.

- Train a built-in preset, close the browser, reopen it, and confirm the log, progress, and samples.
- From a phone, open the `tailscale serve` address and record a take. Confirm the wav lands in the dataset folder.
- Import a desktop training queue and start it. Caption a folder with Florence or Qwen. Run a real face crop. Confirm a browser notification when a run finishes.
- Profile a real LoRA, extract a real LoRA, and edit a real file's metadata.
- Load a family, move a Repair slider, run Quick, and save a baked file. Render RefMod, roll Explorer, and export a Royale mp4.
- Cut a real clip, run Whisper on a real take, and diff two real checkpoints.
- On two GPUs, run one job on each at the same time, and confirm a second job on one GPU waits.
