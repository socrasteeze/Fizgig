# HANDOFF

**Updated:** 2026-10-26 | **Branch:** master | **Upstream:** e8f89bcf | **Delivery target:** fork/master

## State
Merged five upstream commits after 13db3b3b through e8f89bcf onto the prior local merge e52cff51. All adopted; no conflicts or new dependencies. CPU verification: pytest 272 passed with 63 subtests; unittest 99 passed with one inherited Windows socket abort. All 282 Python files compile; both JavaScript files parse; no new pyflakes diagnostics.
The prior merge includes v8.9.9-v8.9.92: mask editing, subfolder training, Continue, queue editing, cache progress and the retired v8 workflow removal. The published fork was 3cc3a981 before this delivery.

## Done this session
- Adopted MOSS-Image Fast as the first/default preset, prompt-slider anchors and live editing, the SDXL practice-picture negative-prompt device fix, and matching model/CLI guidance.
- Corrected `checks/test_page.py` to recognise the dock's ID-forwarding button factory. Missing-ID and broken-factory mutations still fail the check.
- Retained Start confirmation warnings, the Profiler guard, immediate duplicate-Start refusal, claim cleanup and successful-resume-only queue release.
- Preserved and sanitised the existing recovery notes. No live service restart, model download, cache deletion or change to the live environment was performed.
- Delivery scrub: zero unresolved findings, no untracked candidate files or key files. Existing upstream metadata is retained under the repository rules.
- QA tools were installed into a scratch folder with `pip install --target`; the live environment still lacks pytest and pyflakes.

## Fork changes on top of upstream
- `.gitignore` ignores `AGENTS.md` and upstream's `.cursor/`. Upstream release notes remain in `docs/RELEASE_NOTES_vX.Y.Z.md`; do not create CHANGELOG.md.
- `checks/isolate.py` redirects data paths to temporary storage and disables migration before web imports. Both unittest and pytest are required: unittest alone misses upstream's function-based checks.
- Keep run notifications, low-disk and resume-at-max-epochs warnings, unreadable-preferences refusal, caption-job termination, Studio save/load/unload safety, the restart banner, Windows queue-save retries, 16 MB JSON/helper body caps and caption-extension limits.

## Open
1. Prior recovery note: preferences, run history, queue, presets and logs were lost on 2026-10-25 after a broad ignored-file cache cleanup. The environment and model paths were rebuilt; set the web password and RunPod key again if still needed. This session did not inspect credentials or rerun recovery.
2. Helpers' move-in/move-back callers read only `ok`/`error`/`problems` from Start. Fork warning responses can fail a move or leave it paused. Decide whether to display the warning or bypass it for moves.
3. Move-back accepts helper-listed filenames after path checks without extension limits. Decide whether lead-side writes should accept only media and caption extensions.
4. `local_start` writes the disposable second-GPU preferences with `_write`, outside the main preferences guard. The main preferences file is not affected.
5. The former slate-theme audit remains unfinished; `webui/`, the preferences backup and the audit document were deleted in the prior recovery. Training Start while Studio loads was previously reported to leave Studio on loading; not rechecked here.
6. Whole-tree pyflakes has inherited findings, including deferred type names, closures whose resources are deleted after use, unused imports and a delayed exception callback in Gizmo. Compare against the pre-merge report; do not claim whole-tree lint is clean.
7. Windows socket tests can fail with WinError 10053 and pass on rerun. The baseline upload test did so this session; the final unittest run still hit one abort, while the full pytest run passed all tests. This Windows-only failure is an environment exception; CI runs on Linux. An existing upstream extra blank line in `checks/test_face_backends.py` can appear in broad historical whitespace checks.

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
