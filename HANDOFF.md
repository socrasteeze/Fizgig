# HANDOFF

**Updated:** 2026-10-09 · **Branch:** master · **HEAD:** f635346 · **Tree:** dirty (Phase 2 uncommitted)

## State
Phase 2 is uncommitted on f635346. The page can queue a training run, browse and upload a dataset, edit prefs, caption, and prep images. A stand-in trainer, a fake caption server, and a stubbed face detector cover the checks. A real GPU run and phone access through `tailscale serve` are still manual (`docs/WEBUI_PHASE2.md`).
The next step is Phase 3a: Profiler, Extract, Metadata, Samples settings.

## Done this session
- Queue, history, prefs, folder browser, upload, Start folder, captions, and image prep. API in `docs/WEBUI_PHASE2.md`.
- New modules under `src/fizgig/web/`: `queue.py`, `prefs.py`, `fs.py`, `start.py`, `captions.py`, `image_prep.py`. Routes in `app.py`. Caption and prep run through the existing runner and GPU lock.
- Page tabs in `webui/src/extra.tsx`, wired from `webui/src/App.tsx`. In-page notices stay. Browser notifications ask only from a button.
- `python-multipart==0.0.20` in `requirements-web.txt` (upload). No other new dependency.
- Default suite: 34 tests, 33 passed, 1 skipped. Three runs, same counts (77.785s, 77.641s, 79.969s). Golden: 1 passed. `npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Open
1. Phase 3a: Profiler, Extract, Metadata, Samples settings.
2. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
3. At 150% the fixed 1580x1124 window truncates tab labels in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).
4. A real GPU run from the page, phone access through `tailscale serve`, a real caption model, and a real face detector.

## Decisions
- Fork-only, nothing offered upstream (user, 2026-10-08). New files only, no imports of `lora_trainer_gui.py`, GUI logic mirrored and pinned by a hash test rather than moved.
- The queue advances only after a training job this process watched finishes cleanly. Failure, stop, and pause hold it. A server restart keeps the list and does not start it.
- Desktop `presets/training_queue.json` is imported read-only. The mapping follows `_apply_queue_item`.
- Prefs secrets (`runpod_api_key`, and keys ending in `_key`, `_token`, or `_secret`) are never sent and never overwritten by a web save.
- Caption and prep are jobs on the same lock as training. `FIZGIG_WEB_FAKE_CAPTION` and `FIZGIG_WEB_FAKE_FACE=1` stand in for the checks. Translation, Whisper, the Look filter, and Gizmo stay on the desktop.
- No login (user): the server listens on 127.0.0.1 only. Tailscale Serve is the only way in.
- Low disk and a resume already at max epochs are warnings. The page sends the codes back in `confirm` to start anyway.

## Traps
- `origin` is upstream: fetch only, push disabled. Push only to fork, on master, when asked, via the clean workflow. `AGENTS.md`, the agent notes file, and `.git/hooks/pre-push` exist only in this checkout.
- The golden test fills the edit Originals folder and the slider -1 end folder before it compares commands. Do not change `launch.py` or the GUI to hide a difference (`docs/WEBUI_PHASE1.md`).
- Never post on upstream issues or PRs, and never open one. If a sync brings in `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- This checkout's venv, prefs and output LoRAs are real. Test launches use `FIZGIG_NO_PERSIST` and an isolated prefs file. `--launch` may create a CUDA context. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` from the web server (that import loads torch). The Host check rejects a test client's default host, so tests use 127.0.0.1. `FIZGIG_WEB_FAKE_TRAINER` replaces plan stages after `plan()` succeeds. Do not set it in a real launch.
- `plan()` does not point `--dit` at a fine-tune checkpoint. A fine-tune resume from the page is not the desktop's continuation.
- Deleting a job record removes only the job folder. It must not delete the output directory or the dataset.

## Verify
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe checks\check_appearance.py
$env:FIZGIG_GOLDEN='1'; .\venv\Scripts\python.exe -m unittest checks.test_web_golden -v
npm --prefix webui run build
git status --short
git log fork/master..HEAD --oneline
git diff --check
```
