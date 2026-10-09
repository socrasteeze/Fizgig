# HANDOFF

**Updated:** 2026-10-09 · **Branch:** master · **HEAD:** d299c78 · **Tree:** clean

## State
The web UI build is complete: phases 0-5 plus three review rounds are committed. Remaining work is manual checks on real hardware.

## Done this session
- Phases 0-5 built, each verified and committed; 82 review findings fixed (fdcea8b).
- Round 2 (427e604) and round 3 (d299c78) fixed regressions and partial fixes found by re-checks; test isolation via `checks/runner_guard.py`; the runner waits up to 15 s for the GPU lock and logs startup errors to `runner.err`.
- Final state: suite 200 tests, 197 passed, 3 skipped, twice; golden OK; `npm --prefix webui run build` and `checks\check_appearance.py` pass.
- A last read-only sweep of the round-3 diff was stopped early at the user's request; round 3 is covered by its tests only.

## Open
1. Push to fork when asked (7 commits ahead of fork/master).
2. Manual checks in `docs/WEBUI_PHASE5.md`: a real training run, `tailscale serve` from a phone, a phone recording, Whisper, a clip, and a checkpoint diff.
3. Two real GPUs at once: one job on each, and no overlap on one GPU. Not run.
4. Review the dialogs (Queue, Gallery, Browse, preset windows) at 100%, 125%, and 150%. None were opened.
5. At 150% the fixed 1580x1124 window truncates tab labels in both appearances (`lora_trainer_gui.py:1327`).

## Decisions
- Bake through the loaded engine's `save_repaired`. The file baker is only the fallback, and a family it cannot map is refused.
- Queue advance is a thread inside the running server. It is not autostart, and a failed run does not start the next job.
- Blank launch fields are filled from Preferences. Secret values are still not sent and not cleared by a web save.
- Advanced train.py flags are shown read-only. They are not passed through.
- Engine events use `events_since` and a cursor. A stream must not call `drain()`.
- The desktop GPU lock takes the index of the card the subprocess environment will use.
- No login and no autostart. The server listens on loopback. Tailscale Serve is the only way in.
- Fork-only. New web files only. The server does not import the desktop GUI module.

## Traps
- `origin` is upstream, fetch only. Push only to `fork` master when asked, via the clean workflow. Tests need `FIZGIG_NO_PERSIST` and an isolated prefs file. Don't run `update_fizgig.bat`.
- Do not import `families/train.py` or `gizmo.py`. A real engine load imports torch. Tests set `FIZGIG_WEB_FAKE_ENGINE=1`.
- GET `/api/jobs` and the event round must not call `queue.observe`. The lifespan thread does, about every 2 seconds.
- Do not drain engine events from a stream. Pass that stream's cursor to `events_since`.
- The golden test compares with the desktop. Do not change `launch.py` or the GUI to hide a difference.
- If a sync brings in `src/fizgig/web`, stop and ask. Never post on upstream issues or PRs.

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
