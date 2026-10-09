# HANDOFF

**Updated:** 2026-10-08 · **Branch:** master · **Base:** e198fb8 (origin/master); fork/master at 549e0f8 · **Tree:** dirty (uncommitted `.gitignore` line)

## State
The appearance fix is local, on top of 883c09c, and not pushed. `dark-clam` again matches the pre-change clam spacing.

## Done this session
- Restored `dark-clam` padding and mapped selected-tab padding per appearance — `lora_trainer_gui.py`.
- Stated the 883c09c correction in the fix commit. Did not amend.
- Shipped `checks/test_status_bar_layout.py` and `checks/test_appearance_launch.py`. Status bar re-measured at 100/125/150; both appearances fit.
- Isolated `--launch` twice: `compact-clam`, theme `clam`, 13 tabs. Repo preference files unchanged.

## Open
1. Confirm this checkout is not a running install, then review all 13 tabs and their dialogs at 100%, 125%, and 150%. The structural launch is done; that dialog walk is not.
2. Push to fork/master only after that confirmation.
3. The uncommitted `.gitignore` line for `AGENTS.md` is still unstaged.

## Decisions
- Kept `dark-clam` as the pre-change spacing instead of adding a third appearance — the default must not add padding the old styles left unset.
- Selected-tab padding is now mapped. `dark-clam` keeps clam's `6 4 6 2`; `compact-clam` uses its own tab padding.
- Did not amend 883c09c. The fix commit corrects the "current spacing" claim. Amend was not requested.
- Shipped both review checks. `unittest discover -s checks -p test_*.py` is the verify command, and both pass.
- sv-ttk stays rejected — `docs/GUI_THEME.md`.
- A saved appearance still applies on the next start. `setup_styles` runs once.

## Traps
- Keep origin's fetch URL and its disabled push URL. Push only to fork, and only when asked. The default branch is master.
- Do not run `update_fizgig.bat`. It pulls, restores a launcher, and updates dependencies in the running install.
- This checkout holds a venv, preferences, and output LoRAs, so it may be a live install. A launch needs `FIZGIG_NO_PERSIST` and an isolated preference file.
- `--launch` builds the full GUI and may create a CUDA context. The unit checks do not launch Fizgig.
- The splash screen, Gizmo, and the converter keep their own style setup.

## Verify
```powershell
.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v
.\venv\Scripts\python.exe checks\check_appearance.py
git status --short
git log origin/master..HEAD --oneline
git diff --check
```
