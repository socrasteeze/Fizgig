# HANDOFF

**Updated:** 2026-10-14 · **Branch:** master · **Upstream:** v8.0.7 (504ea916) merged

## State
The fork runs upstream's Fizgig 8 web app (`src/fizgig/web/`, stdlib `http.server` + vanilla JS). The fork's own FastAPI + React web UI, the desktop GUI and their checks are gone. The fork adds a few small fixes to upstream's code and a `checks/` suite, since upstream ships no tests.

## Fork changes on top of upstream
- `.gitignore`: also ignores `AGENTS.md`.
- `checks/`: tests against upstream's code. `isolate.py` must be imported before `fizgig.web`: it moves every `user_data/` path into a temp folder and turns off `user_data.migrate()`.
- Small fixes to upstream files, one commit each. List them with `git log --oneline` after the v8 merge commit.

## Open
1. Push to fork when asked.
2. Tier 2 items in the web UI adoption audit: stale tab after a restart (403 banner), idle unload of the Studio model, slate theme, queue save retries on Windows, a body-size cap and a caption extension allowlist.
3. More checks against upstream: route contract (`/api/...` in `app.js` vs `server.py`, `node --check`), upload and download file safety, queue holds, `st_meta` header writes, destructive ops.

## Decisions
- Upstream's app replaces the fork's. Keep fork patches to upstream files minimal so syncs merge cleanly.
- Never send anything upstream. No autostart of any kind.
- Remote access: save a `web_password`, start with `--host 127.0.0.1`, then `tailscale serve --bg 8081`. The app window (`Launch Fizgig.bat`) has no `--host`, so with a saved password it listens on `0.0.0.0`.

## Traps
- `origin` is upstream, fetch only. Push only to `fork` master, via the clean workflow in `AGENTS.md`.
- The first `fizgig.py` start moves the root `prefs.json`, `cache/`, `presets/`, `profiles/` and `dataset/` into `user_data/`.
- A test that imports `fizgig.web` before `isolate` writes the real `user_data/`. `test_isolation` fails if a web module holds a path in the Fizgig folder.

## Verify
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
git status --short
git log fork/master..HEAD --oneline
git diff --check
```
