# HANDOFF

**Updated:** 2026-10-08 · **Branch:** master · **Base:** e198fb8 (origin/master); fork/master at 0bc8d06 · **Tree:** clean

## State
883c09c and 0bc8d06 are pushed to fork/master. `dark-clam` matches the pre-change clam spacing; every main tab is checked at 100/125/150%, but dialogs are not.

## Done this session
- Restored `dark-clam` padding and mapped selected-tab padding per appearance — `lora_trainer_gui.py`.
- Stated the 883c09c correction in the fix commit. Did not amend.
- Shipped `checks/test_status_bar_layout.py` and `checks/test_appearance_launch.py`. Status bar re-measured at 100/125/150; both appearances fit.
- Isolated `--launch` twice: `compact-clam`, theme `clam`, 13 tabs. Repo preference files unchanged.
- Screenshotted all 13 tabs for both appearances at 100/125/150% (isolated prefs, `FIZGIG_NO_PERSIST`): no clipped widgets, no errors, live prefs unchanged.

## Open
1. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%; none were opened.
2. At 150% the fixed 1580x1124 window truncates tab labels ("1. Sta", "Repair Stu") in both appearances. This predates the appearance work (`lora_trainer_gui.py:1327`).

## Decisions
- Kept `dark-clam` as the pre-change spacing instead of adding a third appearance — the default must not add padding the old styles left unset.
- Selected-tab padding is now mapped. `dark-clam` keeps clam's `6 4 6 2`; `compact-clam` uses its own tab padding.
- Did not amend 883c09c. The fix commit corrects the "current spacing" claim. Amend was not requested.
- Shipped both review checks. `unittest discover -s checks -p test_*.py` is the verify command, and both pass.
- sv-ttk stays rejected — `docs/GUI_THEME.md`.
- A saved appearance still applies on the next start. `setup_styles` runs once.

## Traps
- Keep origin's fetch URL and its disabled push URL. Push only to fork, and only when asked. The default branch is master.
- "push" means: run the clean workflow with the repo overrides in local `AGENTS.md`, then `git push fork master`. The local `.git/hooks/pre-push` blocks other remotes, force pushes, and attribution or sensitive values in our own commits. Never `--no-verify`.
- Do not run `update_fizgig.bat`. It pulls, restores a launcher, and updates dependencies in the running install.
- This checkout is a development copy, not a running install (user confirmed 2026-10-08). Its venv, preferences, and output LoRAs are still real, so a test launch uses `FIZGIG_NO_PERSIST` and an isolated preference file.
- `--launch` builds the full GUI and may create a CUDA context. The unit checks do not launch Fizgig.
- Fizgig is not DPI-aware, so Windows scales its window. Screen captures must multiply Tk coordinates by the display scale, or they come out cropped.
- The splash screen, Gizmo, and the converter keep their own style setup.

## Verify
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe checks\check_appearance.py
git status --short
git log origin/master..HEAD --oneline
git diff --check
```
