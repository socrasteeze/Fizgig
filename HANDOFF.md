# HANDOFF

**Updated:** 2026-10-08 | **Branch:** master | **Base:** e198fb8 (origin/master and fork/master at assessment) | **Tree:** clean before this handoff

## State
GUI modernization is scoped only. Implementation needs explicit approval; do not modify either running installation.
Delivery is authorized for this handoff-only commit to fork/master; do not create a branch or push to upstream.

## Done this session
- Assessed installed commit e198fb897717ce86e08aae1b527029235a5b65a5 with static source inspection and release-history comparison; no GUI or training was launched.
- Counted direct widget constructor sites: main GUI 788 ttk / 714 tk; Gizmo 15 / 118; converter 7 / 18; splash 1 / 8. Total 811 ttk / 858 tk (48.6% / 51.4%); excludes nine custom-wrapper calls and runtime loop expansion.
- Confirmed 13 main tabs, including Start, Samples, RefMod Studio and Metadata; lora_trainer_gui.py has 30,766 lines at the assessed commit.
- Main GUI changed in 18 of the last 20 tag intervals (v6.1.0 through v7.1.0); AST structure of COLORS and setup_styles stayed unchanged in all 20.
- Verified public fork https://github.com/socrasteeze/Fizgig; origin fetch stays upstream, origin push is disabled://upstream-push-disabled, and fork is the separate delivery remote.

## Open
1. Obtain approval for a 3-5 engineering-day theme/spacing pass; another 1-3 days covers auxiliary tools. Implementation must use a separate checkout of the fork with isolated settings and outputs.
2. Trial sv-ttk against current clam styles before adopting it. Keep current appearance as fallback; prefer a saved, restart-required appearance choice.
3. Proposed files: lora_trainer_gui.py, new fizgig_theme.py and docs/GUI_THEME.md; requirements.txt and THIRD_PARTY_NOTICES.md only if adding the theme dependency.
4. Cover all 13 main tabs through shared styles; edit Preferences for the selector and touch individual tabs only for exceptions. Optional follow-on: gizmo.py, diff_to_lora_gui.py and fizgig_splash.py.
5. Before deployment, check all tabs/dialogs at 100/125/150% scaling, focus/disabled states, scrolling, text selection, slider callbacks, image/video previews and galleries; compare launch settings/commands and run bounded training/workbench smoke checks in isolation.
6. Before any web work, review the current state of upstream issue #165 and its contributor implementation; do not assume reported progress is shipped functionality.

## Decisions
- Recommend theme/spacing changes with existing widget types and callbacks; central style code has lower upstream overlap than a tab rewrite.
- Existing dark palette: lora_trainer_gui.py:63; ttk styles: setup_styles at :2533. A ttk theme alone cannot restyle ordinary Tk widgets or custom Canvas drawings.
- CustomTkinter estimate: 5-8 engineering-weeks for a hybrid main app (6-10 files), 8-12 weeks for auxiliary-tool parity (8-14 files); all 13 tabs and dialogs require review.
- Web estimate: 5-8 engineering-weeks for a training launcher/monitor; 16-28 weeks for full 13-tab parity, approximately 50-90 new files plus 4-8 existing integration files. One engineer-week means five working days; GPU runtime and upstream review are additional.
- Conflict planning ranges, not measured merge results: central theme usually none or 1-2 regions; widget rewrite several to dozens per feature release; separate web files reduce textual conflicts but retain behavior drift.
- Reuse src/fizgig/families/launch.py and family workbench engines. Desktop calls shared command builders, not the complete launch.plan(); queue/process/GPU-session ownership remains GUI-bound.
- Upstream rejected a duplicated Next.js UI for maintenance drift: https://github.com/shootthesound/Fizgig/pull/164#issuecomment-5892572398 . Preferred schema-driven direction: https://github.com/shootthesound/Fizgig/issues/165 .
- CONTRIBUTING.md welcomes focused PRs and shared COLORS/helpers; acceptance of a theme dependency is unconfirmed. No upstream issue, comment or PR was posted.

## Traps
- Preserve origin fetch and its disabled push URL. Remote settings are local Git configuration and are not carried by this commit. Push only to the user's fork when authorized.
- The default branch is master, not main. The user explicitly requested this handoff on master without creating a branch.
- Do not run update_fizgig.bat during this work: it pulls Git changes, restores a launcher and updates dependencies in the running install.
- A separate checkout must use separate preferences, caches and training outputs; shared model weights alone do not make a test launch isolated.
- Splash has a copied palette and must remain lightweight; Gizmo and the converter have independent style setup. Preserve semantic workbench colors and custom preview behavior.
- No tracked automated tests or documented local test/lint command were found; tests/ is ignored. CONTRIBUTING.md refers to an absent CLAUDE.md and has stale model coverage. Runtime checks were not run.

## Verify
No documented local application test/lint command applies to this documentation-only change. Use these Git checks; runtime validation remains an implementation gate.

```powershell
git branch --show-current
git remote -v
git status --short
git diff --check
git diff --cached --check
git log -1 --oneline
git rev-list --left-right --count HEAD...fork/master
git show --stat --oneline HEAD
```
