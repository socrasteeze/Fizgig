# HANDOFF

**Updated:** 2026-10-09 · **Branch:** master · **HEAD:** 004c2da · **Tree:** dirty

## State
The 82 review findings are fixed and uncommitted on 004c2da. None are disputed or left as won't-fix. Manual GPU and phone checks are still open.

## Done this session
- Engine events are a broadcast with a per-stream cursor. The host assigns render gens. Bake uses the loaded engine's `save_repaired`.
- A server thread advances a queue the user already built. GET does not. Blank model, cache, and caption fields come from Preferences.
- Client paths reject UNC before any stat. The desktop GPU lock uses the card that run will actually use.
- Advanced flags are read-only. The Docker entrypoint waits on `tailscale status --json` and sets the tailnet host.
- One row per finding is in `docs/WEBUI_REVIEW.md`.
- Suite 156 tests, 3 skipped, three times (205.785s, 208.874s, 206.484s). Golden 3 OK (11.591s). `npm --prefix webui run build` passed. `checks\check_appearance.py` passed.

## Open
1. Commit these fixes only when asked. Do not push.
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
