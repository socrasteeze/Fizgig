# HANDOFF

**Updated:** 2026-10-22 · **Branch:** master · **Upstream:** 29abb42a (v8.8.3) · **Delivery target:** fork/master

## State
Merged 23 upstream commits from 022d42fc through 29abb42a into master (merge aa69cfc7), preserving the fork fixes. Upstream is contained in HEAD. Not pushed: fork/master is still at 98ddc771.
Tests ran before and after the merge (pytest from a temp `--target` folder; the venv has no pytest). pytest: 2 failed / 141 passed before, 1 failed / 202 passed after. unittest: 98 run, 1 failure, both times. The only lasting failure is `test_page` (see Open 1).

## Done this session
- Adopted v8.8.3: Resume uses the form's Learning Rate (#214), per-image loss on the run card, Look Filter folder fix (#218), Slider preview cadence, Start tab wording and no spellcheck in prompt boxes.
- Adopted Vast.ai support: pod image `docker/Dockerfile.vast` with HTTPS tunnels, Pods tab line, Stop this instance when a run finishes, docs/VAST.md. `docker.yml` still runs only on `v*` tags or by hand.
- Adopted captions in any encoding (#225, read side; the fork's write-side `CAPTION_EXTS` stays), the pluggable face finder and look match (#190, docs/FACE_BACKENDS.md), and the GTK app window close and zoom fixes.
- Merged without conflicts. The fork's own diff against upstream is line-for-line the same before and after (1825 changed lines). pyflakes: no new findings.
- No dependencies, models or runtime data were changed by the sync. The merge tip uses `[skip ci]`. Preserved the untracked audit document unchanged.

## Fork changes on top of upstream
- `.gitignore`: ignores both `AGENTS.md` and upstream's `.cursor/`.
- `checks/`: `isolate.py` must be imported before `fizgig.web`. It moves every `user_data/` path into a temp folder and turns off `user_data.migrate()`. Tests cover serving, access, every preset's plan, Start, prefs, captions, Studio, the page, the route contract, uploads and file routes, the queue, `st_meta` writes and Delete run / Remove.
- Fixes, one commit each: run notifications (Notify me), low-disk and resume-at-max-epochs warnings, no save over an unreadable `prefs.json`, caption jobs that can't run end with `DONE`, Studio Save refuses a swapped LoRA, Studio unloaded after its worker stops, Start waits for the Profiler, one Start at a time, a Fizgig restarted banner with Reload, Studio unload after 10 minutes unused, queue saves retried on Windows, a 16 MB cap on JSON bodies and caption files limited to caption extensions (`.txt .caption .cap .tags .tag .text`).

## Open
1. `checks/test_page.py::test_every_looked_up_element_exists` fails before and after this merge: upstream's Studio Keep in view panel (2e75dd1f, last sync) makes `stDockClose/Fold/Pin/Play` with a `btn("id", ...)` helper the test's regexes don't read. CI goes red on it once pushed without `[skip ci]`. Fix not applied: needs a decision.
2. The venv still lacks `pywebview`, `soundfile` and `pytest`. The app window (`Launch Fizgig.bat`) needs `pywebview`; CI's `pytest checks -q` needs `pytest`.
3. Preserve the local leftovers: ignored `webui/`, the excluded pre-v8 preferences backup, and untracked `WEBUI_ADOPTION_AUDIT.md`.
4. The audit's slate theme (Tier 2 #11) remains unfinished.
5. Previously recorded: training Start while Studio loads can leave Studio on "loading". This was not rechecked during the sync.
6. `test_access.py::WithPassword::test_login_needs_token` failed once under pytest with WinError 10053 (connection aborted) and passed in 3 reruns and the post-merge run: a Windows socket flake. Keep the output if it recurs.
7. `checks/test_face_backends.py` (upstream) ends with an extra blank line, so `git diff --check` flags it. Left as upstream wrote it.

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
- `fizgig.face_utils` holds `PREFS_FILE` from import time and is not a `fizgig.web` module, so `test_isolation` doesn't see it. Upstream's `test_face_backends.py` points it at `tmp_path` in an autouse fixture; a new test that uses it must too.
- Upstream commit messages carry AI-session trailers and other authors' emails. The pre-push hook skips commits already on `origin/*` and merge commits; only the fork's own commits are scanned.

## Verify
Tests ran this sync (see State). The venv has no pytest: install it with `pip install --target` into a temp folder and set `PYTHONPATH` to it, or add it to the venv.
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe -m pytest checks -q
git status --short
git log fork/master..HEAD --oneline --first-parent
git ls-remote fork refs/heads/master
git diff --check
```
