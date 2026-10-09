# HANDOFF

**Updated:** 2026-10-08 · **Branch:** master · **HEAD:** 70573c0 · **Tree:** dirty (Phase 1a uncommitted)

## State
Phase 1a is uncommitted on 70573c0. The training form is served. The golden test matches all 39 built-in presets. The 8 edit and slider presets match once the pair folder has one PNG. With that folder left empty, `_generic_validate_paths` and `launch.problems()` return the same list (`docs/WEBUI_PHASE1.md`).
Phase 1b has not started.

## Done this session
- Training form and `GET /api/form` — `src/fizgig/web/form_spec.py`, `src/fizgig/web/app.py`.
- Mirror pins for the desktop functions the form follows — `src/fizgig/web/mirrors.py`, `checks/test_web_mirrors.py`.
- Form values to `launch.plan()` inputs — `src/fizgig/web/inputs.py`.
- Golden test, one window for every built-in preset — `checks/test_web_golden.py`. 39 presets match. The 8 edit and slider presets get a pair folder with one PNG. An empty pair folder is the same problem list on both sides.
- Default suite: 15 tests, 14 passed, 1 skipped. Golden suite: 1 passed. `npm --prefix webui run build` passed.

## Open
1. Phase 1b: job folders, supervisor, GPU lock, streaming.
2. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
3. At 150% the fixed 1580x1124 window truncates tab labels in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).

## Decisions
- Fork-only, nothing offered upstream (user, 2026-10-08). The scope's "Keeping the fork mergeable" rules follow from it: new files only, no imports of `lora_trainer_gui.py`, GUI logic mirrored and pinned by a hash test rather than moved.
- Recommended jobs on disk (job folder, detached run, reattach by pid) over an in-memory queue, so runs survive a server restart (ai-toolkit's model; ComfyUI loses its queue).
- Web stack (user, 2026-10-08): Python FastAPI server, React + TypeScript page built by Vite, forms generated from `/api/schema`, because the trainer, schema and engines are Python and hand-written forms drift (upstream closed PR #164). The spike reads `families/train.py`'s parser from source so a schema request does not import torch.
- No login (user): the server listens on 127.0.0.1 only, with no listen option, and Tailscale Serve is the only way in. Every request checks Host; state-changing requests check Origin when that header is present. `POST /api/ping` exists only so that check has a route.
- The pre-push gate scans only commits not on `origin/*`, because upstream's commits carry AI-session trailers and would block every push after a sync.
- No `CHANGELOG.md` in the fork: release notes are upstream's `docs/RELEASE_NOTES_*.md`. The user can still overrule this.
- Kept `dark-clam` as the pre-change spacing instead of adding a third appearance — the default must not add padding the old styles left unset.
- sv-ttk stays rejected — `docs/GUI_THEME.md`. A saved appearance applies on the next start because `setup_styles` runs once.

## Traps
- `origin` is upstream: fetch only, push disabled. Push only to fork, on master, when asked, via the clean workflow. `AGENTS.md`, the agent notes file, and `.git/hooks/pre-push` exist only in this checkout.
- The golden test fills the edit Originals folder and the slider -1 end folder before it compares commands. An empty pair folder is refused by both `_generic_validate_paths` and `launch.problems`. The three command builders still return a launch in that state. Do not change `launch.py` or the GUI to hide a difference (`docs/WEBUI_PHASE1.md`).
- Never post on upstream issues or PRs, and never open one. If a sync brings in `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- This checkout's venv, prefs and output LoRAs are real. Test launches use `FIZGIG_NO_PERSIST` and an isolated prefs file. `--launch` may create a CUDA context. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` from the web server (that import loads torch). The Host check rejects a test client's default host, so tests use 127.0.0.1. Build `webui/` before starting the server. Starlette 1.7 warns that TestClient wants httpx2; `requirements-web.txt` stays on httpx.
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
