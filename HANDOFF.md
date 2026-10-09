# HANDOFF

**Updated:** 2026-10-09 · **Branch:** master · **HEAD:** 753b289 · **Tree:** dirty (Phase 3a uncommitted)

## State
Phase 3a is uncommitted on 753b289. The page has Samples, a weights Profiler, Extract, and Metadata. Checks use fake scripts. A real profile, extract, and metadata edit are still manual (`docs/WEBUI_PHASE3.md`).
The next step is Phase 3b: the engine host and the interactive workbench.

## Done this session
- Samples form, wired into job create and the queue. Golden also compares one preset per family with non-default samples.
- Profiler and Extract jobs on the detached runner, through `profile_lora.py` and `extract_lora.py`. Reports are listed from `profiles_dir`.
- Metadata read/save inside the roots: atomic replace, a `.bak`, tensor bytes unchanged.
- API in `docs/WEBUI_PHASE3.md`. No new dependency.
- Default suite: 41 tests, 39 passed, 2 skipped. Three runs (143.985s, 145.006s, 144.241s). Golden: 2 passed (8.458s). `npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Open
1. Phase 3b: engine host, then Repair, RefMod, Explorer, and Royale.
2. Quick and Thorough profiling, and Open in Repair Studio, wait on that host.
3. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
4. At 150% the fixed 1580x1124 window truncates tab labels in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).
5. A real GPU run from the page, phone access through `tailscale serve`, a real caption model, a real face detector, a real weights profile, a real extract, and a metadata edit on a real file.

## Decisions
- Fork-only, nothing offered upstream (user, 2026-10-08). New files only, no imports of `lora_trainer_gui.py`. GUI logic is mirrored and pinned.
- Profiler runs `profile_lora.py` (weights only). Quick and Thorough need the workbench engine, so they return 422. The form still lists them and defaults to weights.
- Extract runs `extract_lora.py`. Output name, preset or Custom blocks, rank, and the `_2` collision suffix follow the desktop. The file lands in the LoRA output folder.
- Metadata copies the tensor bytes and rewrites the header. It also writes `<file>.bak`, which the desktop save does not.
- Samples use the dict `launch.plan` already accepts. When Klein's checkpoint tick is on and `int8` is omitted, it is filled from the `inference_int8` preference.
- The queue advances only after a training job this process watched finishes cleanly. Profile and extract do not advance it.
- Preference values for API access are never sent and never overwritten by a web save.
- No login (user): the server listens on loopback only. Tailscale Serve is the only way in.

## Traps
- `origin` is upstream: fetch only, push disabled. Push only to fork, on master, when asked, via the clean workflow. This checkout's venv, prefs, and output LoRAs are real. Tests use `FIZGIG_NO_PERSIST` and an isolated prefs file. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` (that import loads torch). The Extract form calls `load_driver()` for the block map, which imports that family's driver and does not load a model.
- The golden test fills the edit Originals folder and the slider -1 end folder before it compares commands. Do not change `launch.py` or the GUI to hide a difference.
- Never post on upstream issues or PRs, and never open one. If a sync brings in `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- `plan()` does not point `--dit` at a fine-tune checkpoint. A fine-tune resume from the page is not the desktop's continuation.
- Deleting a job record removes only the job folder. It must not delete the output directory or the dataset.

## Verify
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe checks\check_appearance.py
$env:FIZGIG_GOLDEN='1'; .\venv\Scripts\python.exe -m unittest checks.test_web_golden -v
npm --prefix webui run build
git status --short
git log fork/master..HEAD --oneline
git diff --check
```
