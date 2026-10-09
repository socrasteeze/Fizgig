# HANDOFF

**Updated:** 2026-10-08 · **Branch:** master · **HEAD:** 6c0f49a · **Tree:** dirty (Phase 1b and 1c uncommitted)

## State
Phase 1b and 1c are uncommitted on 6c0f49a. The training page can create a job, watch it, and pause, resume, stop, or override the next sample. A stand-in trainer covers the checks. A real GPU run and phone access through `tailscale serve` are still manual (`docs/WEBUI_PHASE1.md`).
The next step is Phase 2.

## Done this session
- Jobs on disk, a detached runner, and the routes in `docs/WEBUI_PHASE1.md` — `src/fizgig/web/jobs.py`, `runner.py`, `app.py`.
- GPU lock shared with the desktop — `src/fizgig/gpu_lock.py`. The desktop diff is 19 added lines in `start_training`, `_start_training_launch`, and `_on_training_subprocess_exited`.
- Training page, job monitor, top bar — `webui/src/App.tsx`. API types from `app.openapi()`, checked by `npm run build`.
- `run_webui.bat`. It rebuilds `webui/` when a source file is newer than `webui/dist`, then listens on 127.0.0.1 only.
- Default suite: 22 tests, 21 passed, 1 skipped. Golden suite: 1 passed. `npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Open
1. Phase 2: persistent queue, job history, folder browser and upload, Start tab, Captions, Image Prep.
2. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
3. At 150% the fixed 1580x1124 window truncates tab labels in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).
4. A real GPU run from the page, and phone access through `tailscale serve`.

## Decisions
- Fork-only, nothing offered upstream (user, 2026-10-08). The scope's "Keeping the fork mergeable" rules follow from it: new files only, no imports of `lora_trainer_gui.py`, GUI logic mirrored and pinned by a hash test rather than moved.
- Recommended jobs on disk (job folder, detached run, reattach by pid) over an in-memory queue, so runs survive a server restart (ai-toolkit's model; ComfyUI loses its queue).
- Web stack (user, 2026-10-08): Python FastAPI server, React + TypeScript page built by Vite, forms generated from `/api/schema`, because the trainer, schema and engines are Python and hand-written forms drift (upstream closed PR #164). The spike reads `families/train.py`'s parser from source so a schema request does not import torch.
- No login (user): the server listens on 127.0.0.1 only, with no listen option, and Tailscale Serve is the only way in. Every request checks Host; state-changing requests check Origin when that header is present. `POST /api/ping` exists only so that check has a route.
- The pre-push gate scans only commits not on `origin/*`, because upstream's commits carry AI-session trailers and would block every push after a sync.
- No `CHANGELOG.md` in the fork: release notes are upstream's `docs/RELEASE_NOTES_*.md`. The user can still overrule this.
- Kept `dark-clam` as the pre-change spacing instead of adding a third appearance — the default must not add padding the old styles left unset.
- sv-ttk stays rejected — `docs/GUI_THEME.md`. A saved appearance applies on the next start because `setup_styles` runs once.
- Low disk and a resume already at max epochs are warnings. The page sends the codes back in `confirm` to start anyway. That is the desktop's Yes on those dialogs.

## Traps
- `origin` is upstream: fetch only, push disabled. Push only to fork, on master, when asked, via the clean workflow. `AGENTS.md`, the agent notes file, and `.git/hooks/pre-push` exist only in this checkout.
- The golden test fills the edit Originals folder and the slider -1 end folder before it compares commands. An empty pair folder is refused by both `_generic_validate_paths` and `launch.problems`. The three command builders still return a launch in that state. Do not change `launch.py` or the GUI to hide a difference (`docs/WEBUI_PHASE1.md`).
- Never post on upstream issues or PRs, and never open one. If a sync brings in `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- This checkout's venv, prefs and output LoRAs are real. Test launches use `FIZGIG_NO_PERSIST` and an isolated prefs file. `--launch` may create a CUDA context. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` from the web server (that import loads torch). The Host check rejects a test client's default host, so tests use 127.0.0.1. Build `webui/` before starting the server. Starlette 1.7 warns that TestClient wants httpx2; `requirements-web.txt` stays on httpx.
- `FIZGIG_WEB_FAKE_TRAINER` replaces plan stages after `plan()` succeeds. Unset, the runner executes the real commands. Do not set it in a real launch.
- `plan()` does not point `--dit` at a fine-tune checkpoint. A fine-tune resume from the page is not the desktop's continuation.
- Fizgig is not DPI-aware: screen captures must scale Tk coordinates by the display scale. The splash screen, Gizmo and the converter keep their own style setup.

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
