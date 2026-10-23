# HANDOFF

**Updated:** 2026-10-22 · **Branch:** master · **Upstream:** 70757c5f (v8.9.3) · **Delivery target:** fork/master

## State
Merged 16 upstream commits from 29abb42a through 70757c5f into master (merge a5c7857f), then capped the helpers' raw-body routes (6bafc99f). Upstream is contained in HEAD. Not pushed: fork/master is at dd087af1.
Tests ran before and after (pytest from a temp `--target` folder; the venv has no pytest). pytest: 2 failed / 201 passed before (test_page and a WinError 10053 flake), 1 failed / 214 passed after. unittest: 98 run, 1 failure before; 100 run, 1 failure after. The only lasting failure is `test_page` (see Open 1), same four ids.

## Done this session
- Adopted v8.9.0-v8.9.3: helpers (a second PC, a second GPU, a RunPod pod or Vast.ai instance renders previews, trains a share of each epoch, or takes over a run with Move to...; a pod's checkpoints come home), Move a run for every LoRA kind with clips and songs, MOSS-Image workbench Render with choice, release notes and docs (HELPERS, MOVE_RUN, TRAINING_SHARE, HELPER_PREVIEWS).
- One conflict, `server.py` `_start`: kept the fork's Profiler guard, `confirm` warnings and one-Start claim; upstream's `models=`, `share_stop_all()`, `_plan(..., models)` and the look fetch now sit inside the claim's `_unclaim`-on-error path. The fork's own diff against upstream is otherwise line-for-line the same.
- New fork fix: `/api/helpers/deliver`, `/api/helpers/share_deliver`, `/api/helper/speed` and `/api/helper/put` read Content-Length straight into memory, past the 16 MB cap. They read through `Handler._raw()` now, capped the same way; `checks/test_limits.py` RawCap covers it.
- Checked: every helper route sits after `_api_ok()` (token + login); helpers write prefs only through `update_prefs` (the unreadable-prefs refusal holds). pyflakes: one new upstream finding (unused `pods` import in helpers.py).
- Preserved the untracked audit document unchanged.

## Fork changes on top of upstream
- `.gitignore`: ignores both `AGENTS.md` and upstream's `.cursor/`.
- `checks/`: `isolate.py` must be imported before `fizgig.web`. It moves every `user_data/` path into a temp folder and turns off `user_data.migrate()`. Tests cover serving, access, every preset's plan, Start, prefs, captions, Studio, the page, the route contract, uploads and file routes, the queue, `st_meta` writes, Delete run / Remove, and the body caps.
- Fixes, one commit each: run notifications (Notify me), low-disk and resume-at-max-epochs warnings, no save over an unreadable `prefs.json`, caption jobs that can't run end with `DONE`, Studio Save refuses a swapped LoRA, Studio unloaded after its worker stops, Start waits for the Profiler, one Start at a time, a Fizgig restarted banner with Reload, Studio unload after 10 minutes unused, queue saves retried on Windows, a 16 MB cap on JSON bodies and on helpers' raw pieces, and caption files limited to caption extensions (`.txt .caption .cap .tags .tag .text`).

## Open
1. `checks/test_page.py::test_every_looked_up_element_exists` fails before and after: `stDockClose/Fold/Pin/Play` are made by a `btn("id", ...)` helper the test's regexes don't read. CI goes red on it once pushed without `[skip ci]`. Needs a decision.
2. Moves and the fork's Start warnings: helpers' `move_in` and move-back call `_start` and read only `ok`/`error`/`problems`. A low-disk or resume-at-max-epochs warning there fails the move with "it couldn't start" (move back: stays paused, Resume asks). Decide: show the warning text, or let moves skip it.
3. Move back writes the file names a helper lists into the dataset and output folders; `_SAFE_FILE` blocks paths, not extensions. The helper is one the user added with its password. Decide whether to limit the lead side to media + caption extensions.
4. `local_start` writes `user_data/other_gpu_N/prefs.json` (the second Fizgig's own, rebuilt each start) with `_write`, not the guard; the main `prefs.json` is untouched.
5. The venv still lacks `pywebview`, `soundfile` and `pytest`.
6. Preserve the local leftovers: ignored `webui/`, the excluded pre-v8 preferences backup, and untracked `WEBUI_ADOPTION_AUDIT.md`.
7. The audit's slate theme (Tier 2 #11) remains unfinished.
8. Previously recorded: training Start while Studio loads can leave Studio on "loading". Not rechecked.
9. `test_files.py` and `test_access.py` socket tests fail now and then with WinError 10053 (connection aborted) and pass on rerun: a Windows flake. This sync: `test_only_training_kinds` before, `test_bad_names_refused` once after; both clean on rerun / the final run.
10. `checks/test_face_backends.py` (upstream) ends with an extra blank line, so `git diff --check` flags it.

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
- `_start` takes `models=` (helpers) and `confirm=` (fork) by keyword; anything that can raise between its claim and launch must go through `_unclaim`, or every later Start says "A run is already going".
- New raw-body routes must read through `_raw()`, never `self.rfile.read(n)`.
- `FAMILY_PREVIEW_LOOK` can download its model through `/api/form/state`; do not exercise the live form as an incidental source check.
- `fizgig.face_utils` holds `PREFS_FILE` from import time and is not a `fizgig.web` module, so `test_isolation` doesn't see it. Upstream's `test_face_backends.py` points it at `tmp_path` in an autouse fixture; a new test that uses it must too.
- `FIZGIG_USER_DATA` (set for a second Fizgig on another GPU) moves `user_data.USER_DATA`; tests must not inherit it.
- Upstream commit messages carry AI-session trailers and other authors' emails. The pre-push hook skips commits already on `origin/*` and merge commits; only the fork's own commits are scanned.

## Verify
The venv has no pytest: install it with `pip install --target` into a temp folder and set `PYTHONPATH` to it, or add it to the venv.
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe -m pytest checks -q
git status --short
git log fork/master..HEAD --oneline --first-parent
git ls-remote fork refs/heads/master
git diff --check
```
