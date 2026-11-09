# HANDOFF

**Updated:** 2026-11-08 | **Branch:** master | **Upstream:** 82fdeb26 | **Delivery target:** fork/master

## State
2026-11-08: merged 174 upstream commits after a4966e37 through 82fdeb26 (past release notes v9.2.5). All adopted, no conflicts; every fork-added line in the 7 files both sides touched is still present. One new fork patch on top: `src/fizgig/training/optimizers.py` imports torch lazily (see Fork changes). Gates, CPU-only with temporary `TEMP`: compile of 328 files and `node --check` pass; pytest 453 passed (baseline 374); unittest's only errors are import failures of the function-based modules because pytest was not on its path, the same 14 as baseline plus new `test_adaptive_lr_ceiling`. A ruff F821/F811 pass reports 10 findings, none in files this fork patched. **Upstream now requires PyTorch 2.15 with CUDA 13.4, bitsandbytes 0.50.2 and triton-windows 3.7.0.post26 (Python 3.11+, NVIDIA driver 580+); `venv` is still on torch 2.10.0+cu128 and was not updated.** No GPU work, app startup or pods were exercised.

## Earlier: 2026-11-02 sync
2026-11-02: merged 12 upstream commits after b211ed10 through 11ce8672 (release notes v9.0.2) onto 75349b44. All adopted, no conflicts (the fork's added lines in every file it touches are still present). One fork patch on top: `src/fizgig/utils/image.py` imports torch lazily (see Fork changes).
Gates run on the merged tree with `CUDA_VISIBLE_DEVICES=-1`, temporary `TEMP`, and pytest taken from the system Python via `PYTHONPATH` (not installed in `venv`): compile of `src` and `node --check` pass; pytest 319 passed; unittest 100 tests OK. The pre-merge baseline was the same except one `WinError 10053` socket error in unittest (`test_access.WithPassword.test_login_needs_token`, the known flake). A ruff pass for undefined names and unused imports (F821/F401/F841/F811) was clean of new findings. No GPU work, builds, app startup or pods were exercised, and the RunPod REST v2 calls (Pods tab, auto-stop, passwords, Start, Stop, Delete pod) have not been run against RunPod.

## Earlier: 2026-10-31 sync
Merged 66 upstream commits after 15c84479 through b211ed10 (release notes v9.0.1) onto 03b774da. All adopted; 2 files conflicted (`server.py`, `app.js`), resolved below. Static verification only at that time; tests were not run by user choice.

## Done in the 2026-10-31 sync
- Adopted Detail crops (Image Prep, captions, "Train on the crops only"), the Style score in the Samples gallery, Start checks (warnings with Start anyway), Start that downloads a missing model first, the Run summary card, the sidebar meters, Table view and Add-to-captions, caption dropout, Start at a smaller size, concept caption tasks, Pods tab (Delete pod, auto-joined Helpers, found passwords), move-home fetching, the Krea 2 ComfyUI int8 builds, the auto-recaption fix, CLI docs and release notes v8.9.96 to v9.0.1.
- Conflict 1, `_start_one`: kept the fork's version (claim/`_unclaim`, `prev`, its own Profiler refusal that already existed). Upstream's matching Profiler check is the same behaviour with different wording; the fork wording is kept and `checks/test_start.py` only asserts "Profiler".
- Conflict 2, `/api/start` and the UI: both warning systems coexist. Upstream's Start checks (`launch.start_checks`, strings, `anyway: true`, `showWarnings`) run first; the fork's `{code, message}` warnings (low disk, resume at max epochs, `confirm` codes, `startAnyway`) are asked on the request that would start the run. `start()` in `app.js` tells them apart by `typeof warnings[0] === "string"`; `/api/start` passes `confirm` into `_start`. `_fetch_then_start` still launches `_start(*then)` with no `confirm`: if a fork warning stops that run after a download, the log now prints the warning text instead of "?".
- Conflict 3, `pollRun`: kept `runNotify(...)` and upstream's `resumeMarks()`, `runSummary()` and Studio-button refresh.
- Auto-merged files that both sides touched (`form.py`, `captions.py`, `index.html`) keep every fork-added line (script check: 0 missing). New routes `/api/style` and `/api/captions/add` sit in the authenticated handlers; `add` uses `caption_ext`. `gallery_style` writes `style.json` with a plain `open` in the samples folder (same shape as upstream's likeness scorer; not hardened).

## Fork changes on top of upstream
- `src/fizgig/utils/image.py`: `torch` is imported inside `preprocess_image` (and under `TYPE_CHECKING` for the annotation), with `from __future__ import annotations`. Upstream 11ce8672 added `flatten()` to this module and imported it at the top of `web/prep_jobs.py` and `web/royale.py`, so importing the web server pulled in torch and `checks/test_serve.py::NoTorch` failed. Drop this patch once upstream fixes it.
- `src/fizgig/training/optimizers.py`: `torch` is imported inside `create_optimizer`. Upstream's family modules import `MUON_DEFAULT_ARGS` from it at the top since 4a091d65, so importing the web server pulled in torch and `checks/test_serve.py::NoTorch` failed. Drop this patch once upstream fixes it.
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
7. Windows socket tests can fail with WinError 10053 and pass on rerun. In the 2026-10-27 sync, `test_files.Uploads.test_bad_names_refused` aborted in the baseline and both post-merge unittest runs, and `test_access` aborted once in the first; three reruns of `test_access.py` passed and two of three of `test_files.py` passed. Both pytest runs passed then. In the 2026-11-02 sync the pre-merge unittest baseline hit one (`test_login_needs_token`) and the later runs did not. CI runs on Linux. An existing upstream extra blank line in `checks/test_face_backends.py` can appear in broad historical whitespace checks.
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
The 2026-11-02 sync ran the CPU-only suites (see State). `pytest` is not in `venv`; to run it without installing, put the system Python's `pytest`, `_pytest`, `pluggy`, `iniconfig`, `packaging`, `colorama`, `pygments` and `py.py` in a scratch folder and set `PYTHONPATH` to it for the `venv` Python. Without pytest, `unittest discover` errors on the ten function-based modules at import.
The 2026-10-31 sync permitted static checks only; the block below is the static set.
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
