# HANDOFF

**Updated:** 2026-10-27 | **Branch:** master | **Upstream:** ee45a6aa | **Delivery target:** fork/master

## State
Merged 17 upstream commits after e8f89bcf through ee45a6aa onto the prior merge d760f486. All adopted; no conflicts, no new dependencies, no fork divergence work needed. CPU verification: pytest 272 passed with 63 subtests and unittest 100 passed, both identical to the pre-merge baseline. All 282 tracked Python files compile; both JavaScript files parse; pyflakes output is unchanged from the baseline.
The published fork was d760f486 before this delivery.

## Done this session
- Adopted the Web UI colour-token refactor: every `style.css` rule and the `app.js` canvases and inline styles read `:root` tokens, the app window's bars use them with the old colours as fallbacks, and Studio's block colours are `--data-*` tokens.
- Adopted the themes (Fizgig, Light n' Orange, Seventies, Synthwave, Graphite, Colour-blind safe, High contrast, Dim) with the Theme card at the top of Preferences. Each device keeps its choice in browser storage.
- Adopted the loading-screen tips, the masked-training "(prior preservation)" label and the GPU out-of-memory guidance appended to a failed run's log (#258).
- The fork had no colour or `style.css` changes, so nothing needed re-expressing as tokens. Every `var(--...)` and `themeColor()` name in the web files resolves to a `style.css` definition or a value set at runtime. The restart banner's `.warning-card` and the Notify button's `.btn-sm` rules remain.
- The themes were not checked visually.

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
7. Windows socket tests can fail with WinError 10053 and pass on rerun. This session the first post-merge pytest run hit one abort in `test_files.py`; three reruns of that file and a second full run passed. This Windows-only failure is an environment exception; CI runs on Linux. An existing upstream extra blank line in `checks/test_face_backends.py` can appear in broad historical whitespace checks.

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
