# HANDOFF

**Updated:** 2026-10-20 · **Branch:** master · **Upstream:** 0d03b4a4 (after v8.8.2) · **Delivery target:** fork/master

## State
Merged 60 upstream commits from a575518a through 0d03b4a4 into master, preserving the fork fixes. Upstream is contained in HEAD; fork/master is the authorized publication target.
Source inspection: 254 Python files compile and both JavaScript files parse, before and after the merge. Tests and application startup were not run; this merge is not fully qualified.

## Done this session
- Adopted MOSS-Image Clean-end schedules, SFT-look previews, preview labels and preview/save schedules with their guides and release notes.
- Adopted resume/cache fixes, live-run history protection, folder controls, Royale sheet fixes and batched console replay.
- Merged without conflicts. Kept fork safeguards and the upstream-only `sync-v8.yml` condition.
- Removed one extra EOF blank line in `docs/NEWS.md`. Preserved the untracked audit document unchanged.
- No dependencies, models or runtime data were changed by the sync. The merge tip uses `[skip ci]`.

## Fork changes on top of upstream
- `.gitignore`: ignores both `AGENTS.md` and upstream's `.cursor/`.
- `checks/`: `isolate.py` must be imported before `fizgig.web`. It moves every `user_data/` path into a temp folder and turns off `user_data.migrate()`. Tests cover serving, access, every preset's plan, Start, prefs, captions, Studio, the page, the route contract, uploads and file routes, the queue, `st_meta` writes and Delete run / Remove.
- Fixes, one commit each: run notifications (Notify me), low-disk and resume-at-max-epochs warnings, no save over an unreadable `prefs.json`, caption jobs that can't run end with `DONE`, Studio Save refuses a swapped LoRA, Studio unloaded after its worker stops, Start waits for the Profiler, one Start at a time, a Fizgig restarted banner with Reload, Studio unload after 10 minutes unused, queue saves retried on Windows, a 16 MB cap on JSON bodies and caption files limited to caption extensions (`.txt .caption .cap .tags .tag .text`).

## Open
1. No tests were requested. Run the commands below only after explicit test authorization; the prior 98-test result is historical, not a baseline for this merge.
2. The venv still lacks `pywebview` and `soundfile`, confirmed through package metadata on 2026-10-20. The app window (`Launch Fizgig.bat`) needs `pywebview`.
3. Preserve the local leftovers: ignored `webui/`, the excluded pre-v8 preferences backup, and untracked `WEBUI_ADOPTION_AUDIT.md`.
4. The audit's slate theme (Tier 2 #11) remains unfinished.
5. Previously recorded: training Start while Studio loads can leave Studio on "loading". This was not rechecked during the sync.
6. A prior full checks run errored twice without retained output. It was not reproduced then and no checks ran now. Keep the output if it recurs.

## Decisions
- Upstream's app replaces the fork's. Keep fork patches to upstream files minimal so syncs merge cleanly.
- Never send anything upstream. No autostart of any kind.
- A queued run does not ask the start warnings. The queue holds with the warning as its reason.
- Upstream's new pytest checks coexist with the fork's isolated unittest checks. The unittest command does not discover the pytest-only checks.
- The commit watcher compares the published fork with upstream every five minutes; a local-only merge does not clear its behind count.
- Remote access: save a `web_password`, start with `--host 127.0.0.1`, then `tailscale serve --bg 8081`. The app window has no `--host`, so with a saved password it listens on `0.0.0.0`.

## Traps
- `origin` is upstream, fetch only. Push only to `fork` master, via the clean workflow in `AGENTS.md`.
- A test that imports `fizgig.web` before `isolate` writes the real `user_data/`. `test_isolation` fails if a web module holds a path in the Fizgig folder.
- `checks/test_plan_presets.py` fills in the Edit and Slider folders and the prompt slider's prompts. A new kind of run needs its inputs added there.
- A warning response from Start is not a successful resume. `_resumed()` must require `ok` before clearing a paused queue's hold.
- `FAMILY_PREVIEW_LOOK` can download its model through `/api/form/state`; do not exercise the live form as an incidental source check.

## Verify
Syntax and source inspection ran; tests and runtime checks did not. For an authorized test run:
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe -m pytest checks -q
git status --short
git log fork/master..HEAD --oneline --first-parent
git ls-remote fork refs/heads/master
git diff --check
```
