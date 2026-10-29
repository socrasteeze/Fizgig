# HANDOFF

**Updated:** 2026-10-28 | **Branch:** master | **Upstream:** 15c84479 | **Delivery target:** fork/master

## State
Merged 30 upstream commits after 98de7a48 through 15c84479 onto 45c5eb3f. All adopted, with one Continue success guard adapted for the fork; no conflicts. Local merge only; the cached published fork remains 45c5eb3f. Nothing fetched or pushed.
Static verification: all 287 tracked Python files compile in memory; both JavaScript files parse; all 100 referenced theme tokens resolve across 30 UI files; no conflict markers, whitespace errors or unresolved merge-content scan findings. Tests, builds, imports and startup were not run by user choice; pyflakes is unavailable. Dependencies and CI are unchanged.

## Done this session
- Adopted Z-Image Base, Turbo previews, shared model-file paths, preview settings fixes and the timestep-LoRA render fix; Base workbench renders leave int8 attention off.
- Adopted the optional secondary captioning model, readable-build checks and layer streaming. Empty or invalid secondary paths fall back to the Krea 2 text encoder; no automatic secondary-model download.
- Adopted MOSS-Image rotation-based Clean-end schedules, distinct LoRA/fine-tune defaults and reduced learning rates on lower-share refresh epochs; adopted the MiniMax H3 picture-distillation shape fix.
- Adopted shared prompt sets, persistent training-folder hiding, up to three Royale likeness photos, Continue form loading and upstream release notes v8.9.94/v8.9.95.
- Sweep catch: `_continue_run` attaches its new form only when Start returns `ok`, as `_resumed` requires. A fork warning response must not load the form as a successful Continue.
- All existing fork-added lines survived the merge; 25 fork-only files are unchanged. New prompt-set routes retain token authentication and the capped JSON reader. The supplied prior token-check script was missing; an in-memory check covers literal, inline and dynamically assembled tokens.

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
