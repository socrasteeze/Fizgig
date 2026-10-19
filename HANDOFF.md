# HANDOFF

**Updated:** 2026-10-19 · **Branch:** master · **Upstream:** 27a9e380 (after v8.7.0) · **Publication:** local merge only

## State
Merged 253 upstream commits from 504ea916 through 27a9e380 into master, preserving the fork fixes. The published fork remains at 3f43565b until a push is authorized.
Source inspection: 252 Python files compile and both JavaScript files parse. Tests and application startup were not run; this merge is not fully qualified.

## Done this session
- Adopted Flux 3, MOSS-Image, LoRA Isolation, Studio improvements, upstream checks and documentation.
- Resolved `.gitignore` and the server's resume conflicts; resume confirmations remain, and only a successful start releases a paused queue.
- Restricted `.github/workflows/sync-v8.yml` to the upstream repository; it cannot push a branch in the fork.
- Removed two incoming trailing-whitespace errors. Preserved the untracked audit document unchanged.

## Fork changes on top of upstream
- `.gitignore`: ignores both `AGENTS.md` and upstream's `.cursor/`.
- `checks/`: `isolate.py` must be imported before `fizgig.web`. It moves every `user_data/` path into a temp folder and turns off `user_data.migrate()`. Tests cover serving, access, every preset's plan, Start, prefs, captions, Studio, the page, the route contract, uploads and file routes, the queue, `st_meta` writes and Delete run / Remove.
- Fixes, one commit each: run notifications (Notify me), low-disk and resume-at-max-epochs warnings, no save over an unreadable `prefs.json`, caption jobs that can't run end with `DONE`, Studio Save refuses a swapped LoRA, Studio unloaded after its worker stops, Start waits for the Profiler, one Start at a time, a Fizgig restarted banner with Reload, Studio unload after 10 minutes unused, queue saves retried on Windows, a 16 MB cap on JSON bodies and caption files limited to caption extensions (`.txt .caption .cap .tags .tag .text`).

## Open
1. No tests were requested. Run the commands below only after explicit test authorization; the prior 98-test result is historical, not a baseline for this merge.
2. Push only when authorized. The commit watcher compares the published fork with upstream, so a local merge does not clear its behind count.
3. The venv still lacks `pywebview` and `soundfile`, confirmed through package metadata. The app window (`Launch Fizgig.bat`) needs `pywebview`. No dependencies were installed.
4. Preserve the local leftovers: ignored `webui/`, the excluded pre-v8 preferences backup, and untracked `WEBUI_ADOPTION_AUDIT.md`.
5. The audit's slate theme (Tier 2 #11) remains unfinished.
6. Previously recorded: training Start while Studio loads can leave Studio on "loading". This was not rechecked during the sync.
7. A prior full checks run errored twice without retained output. It was not reproduced then and no checks ran now. Keep the output if it recurs.

## Decisions
- Upstream's app replaces the fork's. Keep fork patches to upstream files minimal so syncs merge cleanly.
- Never send anything upstream. No autostart of any kind.
- A queued run does not ask the start warnings. The queue holds with the warning as its reason.
- Upstream's new pytest checks coexist with the fork's isolated unittest checks. The unittest command does not discover the pytest-only checks.
- Remote access: save a `web_password`, start with `--host 127.0.0.1`, then `tailscale serve --bg 8081`. The app window has no `--host`, so with a saved password it listens on `0.0.0.0`.

## Traps
- `origin` is upstream, fetch only. Push only to `fork` master, via the clean workflow in `AGENTS.md`.
- A test that imports `fizgig.web` before `isolate` writes the real `user_data/`. `test_isolation` fails if a web module holds a path in the Fizgig folder.
- `checks/test_plan_presets.py` fills in the Edit and Slider folders and the prompt slider's prompts. A new kind of run needs its inputs added there.
- A warning response from Start is not a successful resume. `_resumed()` must require `ok` before clearing a paused queue's hold.

## Verify
Syntax and source inspection ran; tests and runtime checks did not. For an authorized test run:
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe -m pytest checks -q
git status --short
git log fork/master..HEAD --oneline --first-parent
git diff --check
```
