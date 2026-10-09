# HANDOFF

**Updated:** 2026-10-09 · **Branch:** master · **HEAD:** 99e472a · **Tree:** dirty (Phase 3b-ii uncommitted)

## State
Phase 3b-i is committed (99e472a). Phase 3b-ii is uncommitted on that commit. RefMod Studio, LoRA the Explorer, and LoRA Royale register on the same engine host. Checks use fake engines. A real load and render are still manual (`docs/WEBUI_PHASE3.md`).
The next step is Phase 4: Gizmo and the checkpoint-to-LoRA converter.

## Done this session
- `register_engine` is consulted before the generic fake. The worker imports the three tool modules. A render may return a JSON `records` object on the `done` event.
- RefMod Studio: H3 setup, mod scan, load, render with early look and a 60 ms redraw wait, presets in `presets/refmod_studio/` as `_rms_state`.
- LoRA the Explorer: `roll_variants` mirrors the desktop mutation loop. Baseline, four variants, pick, freeze, undo, reset, and save through `save_repaired_lora`. Intensity and structure wait 750 ms.
- LoRA Royale: epoch scan, one-seed render, browser crossfade (two images and a slider), seed, strength, and prompt travel scrubbers, and an ffmpeg export job whose argv matches `write_mp4`.
- Default suite: 65 tests, 63 passed, 2 skipped. Three runs (236.676s, 236.24s, 246.29s). Golden: 2 passed (9.759s). `npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Open
1. Phase 4: Gizmo and the checkpoint-to-LoRA converter.
2. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
3. At 150% the fixed 1580x1124 window truncates tab labels in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).
4. A real GPU run from the page: load an engine, compare slider latency with the desktop, run Quick, and play a video clip. Phone access through `tailscale serve` is still open.

## Decisions
- Fork-only, nothing offered upstream (user, 2026-10-08). New files only, no imports of `lora_trainer_gui.py`. GUI logic is mirrored and pinned.
- One worker, one engine. RefMod, Explorer, and Royale register on it. The epoch crossfade stays in the browser.
- The page bakes with `save_repaired_lora`. The desktop's live `save_repaired` path stays on the desktop.
- Quick and Thorough run on the host, not as queue jobs. Weights stays on `profile_lora.py`.
- Likeness and bleed scores stay on the desktop. The page's profile measures picture change.
- Preference values for API access are never sent and never overwritten by a web save.
- No login (user): the server listens on loopback only. Tailscale Serve is the only way in.

## Traps
- `origin` is upstream: fetch only, push disabled. Push only to fork, on master, when asked, via the clean workflow. This checkout's venv, prefs, and output LoRAs are real. Tests use `FIZGIG_NO_PERSIST` and an isolated prefs file. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` (that import loads torch). A real engine load imports the workbench, which imports torch. Tests set `FIZGIG_WEB_FAKE_ENGINE=1` and must not.
- The golden test fills the edit Originals folder and the slider -1 end folder before it compares commands. Do not change `launch.py` or the GUI to hide a difference.
- Never post on upstream issues or PRs, and never open one. If a sync brings in `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- `plan()` does not point `--dit` at a fine-tune checkpoint. A fine-tune resume from the page is not the desktop's continuation.
- Deleting a job record removes only the job folder. It must not delete the output directory or the dataset.
- The engine worker holds `cache/gpu/<index>.lock` while loaded. Unload it before a training job, and do not start a second worker.

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
