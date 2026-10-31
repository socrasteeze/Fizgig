# HANDOFF

**Updated:** 2026-10-31 | **Branch:** master | **Upstream:** b211ed10 | **Delivery target:** fork/master

## State
Merged 66 upstream commits after 15c84479 through b211ed10 (release notes v9.0.1) onto 03b774da. All adopted; 2 files conflicted (`server.py`, `app.js`), resolved below. Local merge only; the published fork remains 03b774da. Nothing pushed.
Static verification: all 292 tracked Python files compile in memory; both JavaScript files parse; an isolated import of `fizgig.web.server`, `gallery_style`, `captions` and the detail-crop modules succeeded; no conflict markers or whitespace errors. Tests, builds and startup were not run by user choice; pyflakes is unavailable. Dependencies and CI files are unchanged.

## Done this session
- Adopted Detail crops (Image Prep, captions, "Train on the crops only"), the Style score in the Samples gallery, Start checks (warnings with Start anyway), Start that downloads a missing model first, the Run summary card, the sidebar meters, Table view and Add-to-captions, caption dropout, Start at a smaller size, concept caption tasks, Pods tab (Delete pod, auto-joined Helpers, found passwords), move-home fetching, the Krea 2 ComfyUI int8 builds, the auto-recaption fix, CLI docs and release notes v8.9.96 to v9.0.1.
- Conflict 1, `_start_one`: kept the fork's version (claim/`_unclaim`, `prev`, its own Profiler refusal that already existed). Upstream's matching Profiler check is the same behaviour with different wording; the fork wording is kept and `checks/test_start.py` only asserts "Profiler".
- Conflict 2, `/api/start` and the UI: both warning systems coexist. Upstream's Start checks (`launch.start_checks`, strings, `anyway: true`, `showWarnings`) run first; the fork's `{code, message}` warnings (low disk, resume at max epochs, `confirm` codes, `startAnyway`) are asked on the request that would start the run. `start()` in `app.js` tells them apart by `typeof warnings[0] === "string"`; `/api/start` passes `confirm` into `_start`. `_fetch_then_start` still launches `_start(*then)` with no `confirm`: if a fork warning stops that run after a download, the log now prints the warning text instead of "?".
- Conflict 3, `pollRun`: kept `runNotify(...)` and upstream's `resumeMarks()`, `runSummary()` and Studio-button refresh.
- Auto-merged files that both sides touched (`form.py`, `captions.py`, `index.html`) keep every fork-added line (script check: 0 missing). New routes `/api/style` and `/api/captions/add` sit in the authenticated handlers; `add` uses `caption_ext`. `gallery_style` writes `style.json` with a plain `open` in the samples folder (same shape as upstream's likeness scorer; not hardened).

## Fork changes on top of upstream
- `.gitignore` ignores `AGENTS.md` and upstream's `.cursor/`. Upstream release notes remain in `docs/RELEASE_NOTES_vX.Y.Z.md`; do not create CHANGELOG.md.
- `checks/isolate.py` redirects data paths to temporary storage and disables migration before web imports. Both unittest and pytest are required: unittest alone misses upstream's function-based checks.
- Keep run notifications, low-disk and resume-at-max-epochs warnings, unreadable-preferences refusal, caption-job termination, Studio save/load/unload safety, the restart banner, Windows queue-save retries, 16 MB JSON/helper body caps and caption-extension limits.

## Open
1. Prior recovery note: preferences, run history, queue, presets and logs were lost on 2026-10-25 after a broad ignored-file cache cleanup. The environment and model paths were rebuilt; set the web password and RunPod key again if still needed. This session did not inspect credentials or rerun recovery.
2. Helpers' move-in/move-back callers read only `ok`/`error`/`problems` from Start. Fork warning responses can fail a move or leave it paused. The Continue card also lacks a warning display/retry path; this sync only guards its new form data. Decide how these callers should handle Start warnings.
3. Move-back accepts helper-listed filenames after path checks without extension limits. Decide whether lead-side writes should accept only media and caption extensions.
4. `local_start` writes the disposable second-GPU preferences with `_write`, outside the main preferences guard. The main preferences file is not affected.
5. The former slate-theme audit remains unfinished; upstream's theme system adopted on 2026-10-27 may supersede it; `webui/`, the preferences backup and the audit document were deleted in the prior recovery. Training Start while Studio loads was previously reported to leave Studio on loading; not rechecked here.
6. Whole-tree pyflakes has inherited findings, including deferred type names, closures whose resources are deleted after use, unused imports and a delayed exception callback in Gizmo. It was unavailable this session; no lint comparison was made. Do not claim whole-tree lint is clean.
7. Windows socket tests can fail with WinError 10053 and pass on rerun. In the 2026-10-27 sync, `test_files.Uploads.test_bad_names_refused` aborted in the baseline and both post-merge unittest runs, and `test_access` aborted once in the first; three reruns of `test_access.py` passed and two of three of `test_files.py` passed. Both pytest runs passed then. No tests ran in this sync. CI runs on Linux. An existing upstream extra blank line in `checks/test_face_backends.py` can appear in broad historical whitespace checks.
8. A pod asked to run this computer's Fizgig fetches the commit from its own `origin` (shootthesound/Fizgig). This fork's merge commits are not there, so a pod on another build answers that the version isn't on GitHub, keeps the build note, and Move refuses with that text; the Pods list asks again every 90 s. Upstream handles this as an error, not a crash. Decide whether that is acceptable or pods should run from the fork. Not exercised against a pod.

## Decisions
- Keep upstream's app and minimal fork patches. Never send changes upstream. No autostart.
- `origin` is upstream fetch-only, with its push URL disabled. Publish only with `git push fork master`; never force or bypass hooks.
- A queued run does not confirm Start warnings; its warning remains the queue hold reason.
- The commit watcher compares the published fork every five minutes; a local merge alone does not clear its behind count.
- Remote access uses a saved `web_password`, `--host 127.0.0.1` and `tailscale serve --bg 8081`. The desktop app without `--host` binds all interfaces when a password is saved.
- Prior recovery's model setup uses bf16 Klein DiTs with `flux2-vae.safetensors`, not FLUX.1 `ae.safetensors` or an NVFP4 Qwen3-8B encoder. Recovered models include Krea 2, Klein 9B, MiniMax H3, Anima and SDXL; the prior note records the missing captioner, full Qwen3-8B and MiniMax adapters as downloaded.

## Traps
- Never run broad `git clean -X` commands with cache pathspecs: ignored live data and environments can match whole directories. If cache removal is required, limit explicit inspection to source and checks. This session compiles Python in memory.
- Import `isolate` before `fizgig.web`; do not inherit `FIZGIG_USER_DATA`. `fizgig.face_utils.PREFS_FILE` also needs an explicit temporary path in tests because web-module isolation does not inspect it. Run Python `-c` outside the repo root or insert source/check paths first: `fizgig.py` shadows the package.
- `_start` takes `models=` and `confirm=` by keyword. Any exception between claim and launch must release the claim via `_unclaim`. `_resumed()` must require `ok` before releasing a queue hold; `_open_run_log` must remain non-raising after the starting state is set.
- New raw-body routes must use `_raw()`, not direct `rfile.read(n)`. Helper routes must retain authentication and guarded preference writes.
- `/api/form/state` can download `FAMILY_PREVIEW_LOOK`; `/api/masks/sam_fetch` downloads a large model. Do not exercise either against live preferences as an incidental smoke test.
- `pod_version.busy()` reads server `_lock`, `_run`, `_fetch` and helpers' `_out`, `_sw`, `_mvin` internals; a fork patch that renames them breaks pod switching only on a pod.
- `checks/test_plan_presets.py` supplies Edit/Slider folders and prompt-slider inputs; extend these for new run modes. The pre-push hook excludes upstream commits and merge commits; inspect the authored working-tree changes as well.

## Verify
This sync permits static checks only. Tests, builds, installs, application imports and startup were not run by user choice. Gate 6 (suites) and the build gate are NOT RUN; runtime behavior is unverified.
```powershell
git ls-files '*.py' | .\venv\Scripts\python.exe -B -c "import pathlib, sys; paths = sys.stdin.read().splitlines(); [compile(pathlib.Path(p).read_bytes(), p, 'exec') for p in paths]; print(len(paths), 'Python files compiled')"
node --check src/fizgig/web/static/app.js
node --check src/fizgig/web/static/qrcode.js
git grep -n -E '^(<<<<<<< |=======$|>>>>>>> )' -- .
git diff --check
git diff --cached --check
```
For a later authorized suite run, use temporary `TEMP`/`TMP`, set `PYTHONDONTWRITEBYTECODE=1` and `CUDA_VISIBLE_DEVICES=-1`, and remove inherited `FIZGIG_USER_DATA`. Both unittest and pytest are required; missing tools require separate authorization to install.
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe -m pytest checks -q -p no:cacheprovider
.\venv\Scripts\python.exe -m pyflakes src checks
node --check src/fizgig/web/static/app.js
node --check src/fizgig/web/static/qrcode.js
git status --short
git log fork/master..HEAD --oneline --first-parent
git rev-parse fork/master
git diff --check
```
