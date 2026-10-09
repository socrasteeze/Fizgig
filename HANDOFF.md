# HANDOFF

**Updated:** 2026-10-09 · **Branch:** master · **HEAD:** 38e7d67 · **Tree:** dirty (Phase 3b-i uncommitted)

## State
Phase 3b-i is uncommitted on 38e7d67. The page has an engine host, Repair Studio, and Profiler Quick and Thorough. Checks use a fake engine. A real load and render are still manual (`docs/WEBUI_PHASE3.md`).
The next step is Phase 3b-ii: RefMod Studio, LoRA the Explorer, and LoRA Royale. They register on the same host.

## Done this session
- One worker process, JSON lines, one engine. A higher render gen cancels the one in flight. Early frames stream on the SSE `engine` event. Images sit under the jobs root and are served from there.
- The worker holds the GPU lock while an engine is loaded. A job blocks a load, and a loaded engine blocks a job. Both return 409.
- Idle unload (10 minutes, `FIZGIG_WEB_ENGINE_IDLE`), explicit unload, and shutdown. A dead worker restarts on the next request.
- Repair Studio: family, DiT choice, primary and donor, sliders, presets in the desktop `SliderState` shape, baseline against repaired, metrics, bake through `save_repaired_lora`, and a `<video>` clip when ffmpeg can make one.
- Profiler Quick (seed 1234) and Thorough (1234 and 5678). Open in Repair Studio hands over the LoRA and the suggested sliders.
- Default suite: 51 tests, 49 passed, 2 skipped. Three runs (188.344s, 188.381s, 184.070s). Golden: 2 passed (8.805s). `npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Open
1. Phase 3b-ii: RefMod Studio, LoRA the Explorer, LoRA Royale, on this host.
2. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
3. At 150% the fixed 1580x1124 window truncates tab labels in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).
4. A real GPU run from the page: load an engine, compare slider latency with the desktop, run Quick, and play a video clip. Phone access through `tailscale serve` is still open.

## Decisions
- Fork-only, nothing offered upstream (user, 2026-10-08). New files only, no imports of `lora_trainer_gui.py`. GUI logic is mirrored and pinned.
- One worker, one engine. RefMod, Explorer and Royale are names on the protocol and are not built yet.
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
