# HANDOFF

**Updated:** 2026-10-08 · **Branch:** master · **Base:** e198fb8 (origin/master); fork/master at 0bc8d06, HEAD e677fbc unpushed · **Tree:** dirty (`docs/WEBUI_SCOPE.md` new, this file)

## State
The web UI conversion is scoped in `docs/WEBUI_SCOPE.md` with all six decisions made; nothing is built. Next is Phase 0. The appearance work is on fork; dialogs are not reviewed.

## Done this session
- Scoped the browser-based web UI against upstream #164/#165, ai-toolkit, ComfyUI and kohya_ss — `docs/WEBUI_SCOPE.md`.
- Added the local push gate: `.git/hooks/pre-push`, plus a "Pushing" section in the ignored `AGENTS.md` (also imported by an ignored one-line agent notes file). Tested against 6 cases without pushing.
- Committed e677fbc; the hook passes it.

## Open
1. Phase 0 from the scope: confirm upstream has no `src/fizgig/web`, install Node.js and scaffold `webui/` (Vite + React + TypeScript), check `tailscale serve 8081` works on this Windows machine, measure schema coverage per family, spike `/api/schema` for one family.
2. Phase 1 per the scope's acceptance checks; automate each check in `checks/`.
3. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
4. At 150% the fixed 1580x1124 window truncates tab labels in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).

## Decisions
- Fork-only, nothing offered upstream (user, 2026-10-08). The scope's "Keeping the fork mergeable" rules follow from it: new files only, no imports of `lora_trainer_gui.py`, GUI logic mirrored and pinned by a hash test rather than moved.
- Recommended jobs on disk (job folder, detached run, reattach by pid) over an in-memory queue, so runs survive a server restart (ai-toolkit's model; ComfyUI loses its queue).
- Web stack (user, 2026-10-08): Python FastAPI server, React + TypeScript page built by Vite, forms generated from `/api/schema`. Not a Node server, because the trainer, schema and engines are Python. Generated forms rather than hand-written ones, because each upstream sync adds families and options (upstream closed PR #164 for that drift).
- No login (user): the server listens on 127.0.0.1 only and Tailscale Serve is the only way in. Host/Origin checks stay, because they're what stops browser-borne requests.
- The pre-push gate scans only commits not on `origin/*`, because upstream's commits carry AI-session trailers and would block every push after a sync.
- No `CHANGELOG.md` in the fork: release notes are upstream's `docs/RELEASE_NOTES_*.md`. The user can still overrule this.
- Kept `dark-clam` as the pre-change spacing instead of adding a third appearance — the default must not add padding the old styles left unset.
- sv-ttk stays rejected — `docs/GUI_THEME.md`. A saved appearance applies on the next start because `setup_styles` runs once.

## Traps
- `origin` is upstream: fetch only, push disabled. Push only to fork, on master, when asked. "push" means: run the clean workflow with the overrides in local `AGENTS.md`, then `git push fork master`. Never `--no-verify`.
- `AGENTS.md`, the agent notes file that imports it, and `.git/hooks/pre-push` exist only in this checkout. A fresh clone has no push gate.
- `launch.plan()` has no callers: the desktop builds commands from the shared builders itself. Don't trust plan()'s byte-identical claim until the golden test in the scope passes.
- Never post on upstream issues or PRs, and never open one. If a sync brings in an upstream `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- This checkout is a development copy, but its venv, prefs and output LoRAs are real. Test launches use `FIZGIG_NO_PERSIST` and an isolated prefs file, and `--launch` may create a CUDA context. Don't run `update_fizgig.bat`.
- Fizgig is not DPI-aware: screen captures must scale Tk coordinates by the display scale. The splash screen, Gizmo and the converter keep their own style setup.

## Verify
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe checks\check_appearance.py
git status --short
git log fork/master..HEAD --oneline
git diff --check
```
