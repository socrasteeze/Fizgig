# HANDOFF

**Updated:** 2026-10-14 · **Branch:** master · **Upstream:** v8.0.7 (504ea916) merged · **Not pushed**

## State
The fork runs upstream's Fizgig 8 web app (`src/fizgig/web/`, stdlib `http.server` + vanilla JS). The fork's own FastAPI + React web UI, the desktop GUI and their checks are gone. On top of upstream the fork carries eight small fixes and a `checks/` suite (upstream ships no tests). 51 tests pass. The first v8 start has run here: `prefs.json`, `.last_used.json`, `models/`, `presets/` and `cache/` now live in `user_data/`.

## Fork changes on top of upstream
- `.gitignore`: also ignores `AGENTS.md`.
- `checks/`: `isolate.py` must be imported before `fizgig.web`. It moves every `user_data/` path into a temp folder and turns off `user_data.migrate()`. Tests cover serving, access, every preset's plan, Start, prefs, captions, Studio and the page.
- Fixes, one commit each: run notifications (Notify me), low-disk and resume-at-max-epochs warnings, no save over an unreadable `prefs.json`, caption jobs that can't run end with `DONE`, Studio Save refuses a swapped LoRA, Studio unloaded after its worker stops, Start waits for the Profiler, and one Start at a time.

## Open
1. Push to fork when asked.
2. The venv lacks `pywebview` and `soundfile` (new in upstream's `requirements.txt`). The browser launcher works without them. The app window (`Launch Fizgig.bat`) needs `pywebview`.
3. Local leftovers, all untracked: `webui/` (86 MB of `node_modules` and `dist`), `prefs.json.pre-v8.bak` (in `.git/info/exclude`) and `WEBUI_ADOPTION_AUDIT.md`.
4. Tier 2 items in the audit: stale tab after a restart (403 banner), idle unload of the Studio model, slate theme, queue save retries on Windows, a body-size cap and a caption extension allowlist.
5. More checks: route contract (`/api/...` in `app.js` vs `server.py`, which dispatches `/api/studio/`, `/api/refmod/` and `/api/pods/` by suffix), upload and download file safety, queue holds, `st_meta` header writes, destructive ops.
6. A training start while Studio is still loading leaves Studio on "loading". This is upstream behavior and not fixed.

## Decisions
- Upstream's app replaces the fork's. Keep fork patches to upstream files minimal so syncs merge cleanly.
- Never send anything upstream. No autostart of any kind.
- A queued run does not ask the start warnings. The queue holds with the warning as its reason.
- Remote access: save a `web_password`, start with `--host 127.0.0.1`, then `tailscale serve --bg 8081`. The app window has no `--host`, so with a saved password it listens on `0.0.0.0`.

## Traps
- `origin` is upstream, fetch only. Push only to `fork` master, via the clean workflow in `AGENTS.md`.
- A test that imports `fizgig.web` before `isolate` writes the real `user_data/`. `test_isolation` fails if a web module holds a path in the Fizgig folder.
- `checks/test_plan_presets.py` fills in the Edit and Slider folders and the prompt slider's prompts. A new kind of run needs its inputs added there.

## Verify
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
git status --short
git log fork/master..HEAD --oneline --first-parent
git diff --check
```
