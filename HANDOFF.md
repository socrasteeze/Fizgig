# HANDOFF

**Updated:** 2026-10-09 · **Branch:** master · **HEAD:** 78705e1 · **Tree:** dirty (Phase 4 uncommitted)

## State
Phase 4 is uncommitted on 78705e1. Gizmo and the checkpoint-to-LoRA converter run as web jobs. Checks use fakes. A real cut, Whisper, and a phone recording are still manual (`docs/WEBUI_PHASE4.md`).
The next step is Phase 5: running as a service.

## Done this session
- Gizmo: pick or upload inside the roots, Range playback, the desktop cut argv, scene chop, voice names, a recording upload, and Whisper as a lock-holding job. `gizmo.py` is not imported.
- Converter: desktop ranks and name, output in the LoRA folder, fake script in tests, real call is `extract_diff_loras`.
- `docs/WEBUI_PHASE1.md` now describes the hidden-console runner launch.
- Default suite: 93 tests, 91 passed, 2 skipped. Three runs (222.647s, 219.261s, 221.160s). Golden: 2 passed (12.692s). `npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Open
1. Phase 5: running as a service.
2. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
3. At 150% the fixed 1580x1124 window truncates tab labels in both appearances (`lora_trainer_gui.py:1327`).
4. A real GPU run from the page: cut a clip, run Whisper, record from a phone, and diff two checkpoints. Phone access through `tailscale serve` is still open.

## Decisions
- Fork-only, nothing offered upstream. New files only. Do not import `lora_trainer_gui.py`, `gizmo.py`, or `diff_to_lora_gui.py`. GUI logic is mirrored and pinned.
- One worker, one engine. RefMod, Explorer, and Royale register on it. The epoch crossfade stays in the browser.
- The page bakes with `save_repaired_lora`. The desktop's live `save_repaired` path stays on the desktop.
- Quick and Thorough run on the host, not as queue jobs. Weights stays on `profile_lora.py`.
- Likeness and bleed scores stay on the desktop. The page's profile measures picture change.
- Preference values for API access are never sent and never overwritten by a web save.
- No login (user): the server listens on loopback only. Tailscale Serve is the only way in.
- Whisper on the page holds the GPU lock and still runs on CPU, as the desktop pipeline does.

## Traps
- `origin` is upstream: fetch only, push disabled. Push only to fork, on master, when asked, via the clean workflow. This checkout's venv, prefs, and output LoRAs are real. Tests use `FIZGIG_NO_PERSIST` and an isolated prefs file. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` (that import loads torch). A real engine load imports the workbench, which imports torch. Tests set `FIZGIG_WEB_FAKE_ENGINE=1` and must not. Do not import `gizmo.py`; it loads Tk.
- The golden test fills the edit Originals folder and the slider -1 end folder before it compares commands. Do not change `launch.py` or the GUI to hide a difference.
- Never post on upstream issues or PRs, and never open one. If a sync brings in `src/fizgig/web` (#165 is open), stop and ask the user whether to switch to it.
- `plan()` does not point `--dit` at a fine-tune checkpoint. A fine-tune resume from the page is not the desktop's continuation.
- The engine worker holds `cache/gpu/<index>.lock` while loaded. Unload it before a training, Gizmo, Whisper, or convert job. Deleting a job record removes only the job folder.

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
