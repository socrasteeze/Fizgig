# HANDOFF

**Updated:** 2026-10-08 · **Branch:** master · **Base:** e198fb8 (origin/master); fork/master at 0bc8d06, HEAD a0a2ef6 unpushed · **Tree:** dirty (Phase 0 files uncommitted: `webui/`, `src/fizgig/web/`, `requirements-web.txt`, `checks/test_web_schema.py`, `docs/WEBUI_PHASE0.md`, this file)

## State
Phase 0 is uncommitted on master. `/api/schema` round-trips to the Vite page; Phase 1 has not started.
origin/master (e198fb8) still has no `src/fizgig/web`.

## Done this session
- Confirmed upstream has no web server; issue 165 is still open — `docs/WEBUI_PHASE0.md`.
- Scaffolded the Vite page and the FastAPI spike — `webui/`, `src/fizgig/web/`, `requirements-web.txt`.
- Added schema, Host/Origin, and bind tests — `checks/test_web_schema.py` (suite: 11 passed, 0 failed).
- Measured Training-tab coverage per family — `docs/WEBUI_PHASE0.md`.

## Open
1. Phase 1 from `docs/WEBUI_SCOPE.md`: generated training form with preset chips, Advanced argparse flags, and the settings `docs/WEBUI_PHASE0.md` lists as undeclared; then job folders and the supervisor.
2. Phase 1 per the scope's acceptance checks; automate each check in `checks/`.
3. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
4. At 150% the fixed 1580x1124 window truncates tab labels in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).

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
- `launch.plan()` has no callers. Don't trust its byte-identical claim until the golden test in the scope passes.
- Never post on upstream issues or PRs, and never open one. If a sync brings in `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- This checkout's venv, prefs and output LoRAs are real. Test launches use `FIZGIG_NO_PERSIST` and an isolated prefs file. `--launch` may create a CUDA context. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` from the web server (that import loads torch). The Host check rejects a test client's default host, so tests use 127.0.0.1. Build `webui/` before starting the server. Starlette 1.7 warns that TestClient wants httpx2; `requirements-web.txt` stays on httpx.
- Fizgig is not DPI-aware: screen captures must scale Tk coordinates by the display scale. The splash screen, Gizmo and the converter keep their own style setup.

## Verify
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe checks\check_appearance.py
npm --prefix webui run build
git status --short
git log fork/master..HEAD --oneline
git diff --check
```
