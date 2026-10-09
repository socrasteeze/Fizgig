# HANDOFF

**Updated:** 2026-10-09 · **Branch:** master · **HEAD:** 9b92794 · **Tree:** dirty (Phase 5 uncommitted)

## State
Phase 5 is uncommitted on 9b92794. The five build phases are complete. Checks use fakes. Real GPU, phone, and two-GPU runs are still manual (`docs/WEBUI_PHASE5.md`).
The next step is those manual checks.

## Done this session
- Linux launcher `run_webui.sh`. Docker web image under `docker/webui/` (Tailscale userspace, `serve --bg 8081`, loopback only).
- One queue per GPU: `src/fizgig/web/devices.py`, job and queue `device`, training-form picker, per-device queue view.
- No autostart. Decision is row 7 in `docs/WEBUI_SCOPE.md`. User guide is `docs/WEBUI.md`.
- Default suite: 103 tests, 101 passed, 2 skipped. Three runs (163.468s, 158.956s, 157.624s). Golden: 2 passed (10.013s). `npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Open
1. Manual checks in `docs/WEBUI_PHASE5.md`: a real training run, `tailscale serve` from a phone, a phone recording, Whisper, a clip, and a checkpoint diff.
2. Two real GPUs at once: one job on each, and no overlap on one GPU. Not run.
3. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
4. At 150% the fixed 1580x1124 window truncates tab labels in both appearances (`lora_trainer_gui.py:1327`).
5. Page gaps that stay desktop-only are listed in `docs/WEBUI.md`.

## Decisions
- Fork-only, nothing offered upstream. New files only. Do not import `lora_trainer_gui.py`, `gizmo.py`, or `diff_to_lora_gui.py`. GUI logic is mirrored and pinned.
- One worker, one engine, on one chosen device. Training is one job per GPU. RefMod, Explorer, and Royale register on the worker. The epoch crossfade stays in the browser.
- The page bakes with `save_repaired_lora`. The desktop's live `save_repaired` path stays on the desktop.
- Quick and Thorough run on the host, not as queue jobs. Weights stays on `profile_lora.py`.
- Likeness and bleed scores stay on the desktop. The page's profile measures picture change.
- Preference values for API access are never sent and never overwritten by a web save.
- No login and no autostart (user, 2026-10-09). The server listens on loopback only. Tailscale Serve is the only way in. It runs only from `run_webui.bat`, `run_webui.sh`, or the container.
- Whisper on the page holds the GPU lock and still runs on CPU, as the desktop pipeline does.

## Traps
- `origin` is upstream: fetch only, push disabled. Push only to fork, on master, when asked, via the clean workflow. This checkout's venv, prefs, and output LoRAs are real. Tests use `FIZGIG_NO_PERSIST` and an isolated prefs file. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` (that import loads torch). A real engine load imports the workbench, which imports torch. Tests set `FIZGIG_WEB_FAKE_ENGINE=1` and must not. Do not import `gizmo.py`; it loads Tk.
- The golden test fills the edit Originals folder and the slider -1 end folder before it compares commands. Do not change `launch.py` or the GUI to hide a difference.
- Never post on upstream issues or PRs, and never open one. If a sync brings in `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- `plan()` does not point `--dit` at a fine-tune checkpoint. A fine-tune resume from the page is not the desktop's continuation.
- The engine worker holds `cache/gpu/<index>.lock` while loaded. Unload it before a job on that GPU. Do not add a scheduled task, service, or unit. Deleting a job record removes only the job folder.

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
