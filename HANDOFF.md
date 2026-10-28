# HANDOFF

**Updated:** 2026-10-27 | **Branch:** master | **Upstream:** 98de7a48 | **Delivery target:** fork/master

## State
Merged 21 upstream commits after ee45a6aa through 98de7a48 onto the prior merge 649d93f8. All adopted. Two conflicts, both resolved by keeping both sides. `requirements.txt` is unchanged (a test comment and its revert); `checks/requirements.txt` adds CI pins only. CPU verification: pytest 308 passed with 63 subtests (272 before; the 36 new tests are upstream's three new check files); unittest 99 passed with the same inherited Windows socket abort as the baseline. All 287 tracked Python files compile; both JavaScript files parse; pyflakes reports the same findings as the baseline, only line numbers moved.
The published fork was 649d93f8 before this delivery.

## Done this session
- Adopted pods running this computer's Fizgig: `web/pod_version.py`, `/api/pod/match` and `/api/pod/newest`, the app window's switch cover, the Pods list asking a free pod on another build to switch, the pod About box's Use the newest Fizgig, Move's version-mismatch text, and the pod guide, README and Vast.ai notes.
- Adopted PR #259: sub-folder runs leave out Fizgig's own folders (`originals_2`..., `removed`, any case) and name them in the run log; the app window ignores a minimized window's off-screen position (#205); public Hugging Face downloads retry once without an expired login (`utils/hf_public.py`).
- Adopted the masked-training prior-preservation help text, release notes v8.9.93 with theme screenshots, and the checks' CI pins (tqdm, toml, voluptuous, einops, accelerate, transformers, OpenCV). CI's `checks.yml` installs them; nothing was installed locally.
- Conflicts: `app_window._remember` runs upstream's off-screen check before the fork's strict preferences read; `run_server` keeps the fork's guarded `web_port` write, then upstream's `_SRV[0] = srv`.
- `pod_version.busy()` sees a claimed Start because the fork's claim sets `_run["state"]` to `starting`. The new pod routes sit after the token check and read the capped `_body()`. Every server, captions, studio, helpers and prep_jobs name it reads exists in the fork.

## Fork changes on top of upstream
- `.gitignore` ignores `AGENTS.md` and upstream's `.cursor/`. Upstream release notes remain in `docs/RELEASE_NOTES_vX.Y.Z.md`; do not create CHANGELOG.md.
- `checks/isolate.py` redirects data paths to temporary storage and disables migration before web imports. Both unittest and pytest are required: unittest alone misses upstream's function-based checks.
- Keep run notifications, low-disk and resume-at-max-epochs warnings, unreadable-preferences refusal, caption-job termination, Studio save/load/unload safety, the restart banner, Windows queue-save retries, 16 MB JSON/helper body caps and caption-extension limits.

## Open
1. Prior recovery note: preferences, run history, queue, presets and logs were lost on 2026-10-25 after a broad ignored-file cache cleanup. The environment and model paths were rebuilt; set the web password and RunPod key again if still needed. This session did not inspect credentials or rerun recovery.
2. Helpers' move-in/move-back callers read only `ok`/`error`/`problems` from Start. Fork warning responses can fail a move or leave it paused. Decide whether to display the warning or bypass it for moves.
3. Move-back accepts helper-listed filenames after path checks without extension limits. Decide whether lead-side writes should accept only media and caption extensions.
4. `local_start` writes the disposable second-GPU preferences with `_write`, outside the main preferences guard. The main preferences file is not affected.
5. The former slate-theme audit remains unfinished; upstream's theme system (this sync) may supersede it; `webui/`, the preferences backup and the audit document were deleted in the prior recovery. Training Start while Studio loads was previously reported to leave Studio on loading; not rechecked here.
6. Whole-tree pyflakes has inherited findings, including deferred type names, closures whose resources are deleted after use, unused imports and a delayed exception callback in Gizmo. Compare against the pre-merge report; do not claim whole-tree lint is clean.
7. Windows socket tests can fail with WinError 10053 and pass on rerun. This session `test_files.Uploads.test_bad_names_refused` aborted in the baseline and both post-merge unittest runs, and `test_access` aborted once in the first; three reruns of `test_access.py` passed and two of three of `test_files.py` passed. Both pytest runs passed. This Windows-only failure is an environment exception; CI runs on Linux. An existing upstream extra blank line in `checks/test_face_backends.py` can appear in broad historical whitespace checks.
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
Install pytest and pyflakes into a scratch folder with `pip install --target`, then set `PYTHONPATH` to it. Use temporary `TEMP`/`TMP`, set `PYTHONDONTWRITEBYTECODE=1` and `CUDA_VISIBLE_DEVICES=-1`, and remove inherited `FIZGIG_USER_DATA`.
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe -m pytest checks -q -p no:cacheprovider
.\venv\Scripts\python.exe -m pyflakes src checks
node --check src/fizgig/web/static/app.js
node --check src/fizgig/web/static/qrcode.js
git status --short
git log fork/master..HEAD --oneline --first-parent
git ls-remote fork refs/heads/master
git diff --check
```
