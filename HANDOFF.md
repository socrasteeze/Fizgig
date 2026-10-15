# HANDOFF

**Updated:** 2026-10-14 · **Branch:** master · **Upstream:** v8.0.7 (504ea916) merged · **Pushed:** fork/master

## State
The fork runs upstream's Fizgig 8 web app (`src/fizgig/web/`, stdlib `http.server` + vanilla JS). The fork's own FastAPI + React web UI, the desktop GUI and their checks are gone. On top of upstream the fork carries twelve small fixes and a `checks/` suite (upstream ships no tests). 98 tests pass. The first v8 start has run here: `prefs.json`, `.last_used.json`, `models/`, `presets/` and `cache/` now live in `user_data/`.

## Fork changes on top of upstream
- `.gitignore`: also ignores `AGENTS.md`.
- `checks/`: `isolate.py` must be imported before `fizgig.web`. It moves every `user_data/` path into a temp folder and turns off `user_data.migrate()`. Tests cover serving, access, every preset's plan, Start, prefs, captions, Studio, the page, the route contract, uploads and file routes, the queue, `st_meta` writes and Delete run / Remove.
- Fixes, one commit each: run notifications (Notify me), low-disk and resume-at-max-epochs warnings, no save over an unreadable `prefs.json`, caption jobs that can't run end with `DONE`, Studio Save refuses a swapped LoRA, Studio unloaded after its worker stops, Start waits for the Profiler, one Start at a time, a Fizgig restarted banner with Reload, Studio unload after 10 minutes unused, queue saves retried on Windows, a 16 MB cap on JSON bodies and caption files limited to caption extensions (`.txt .caption .cap .tags .tag .text`).

## Open
1. The venv lacks `pywebview` and `soundfile` (new in upstream's `requirements.txt`). The browser launcher works without them. The app window (`Launch Fizgig.bat`) needs `pywebview`.
2. Local leftovers, all untracked: `webui/` (86 MB of `node_modules` and `dist`), `prefs.json.pre-v8.bak` (in `.git/info/exclude`) and `WEBUI_ADOPTION_AUDIT.md`.
3. The audit's slate theme (Tier 2 #11) was not done.
4. A training start while Studio is still loading leaves Studio on "loading". This is upstream behavior and not fixed.
5. One full checks run errored twice (not saved, not reproduced in 55 runs since). If it recurs, keep the output.

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
