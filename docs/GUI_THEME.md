# GUI theme

**sv-ttk: rejected.** The main window stays on the clam theme and the dark palette in `lora_trainer_gui.py`.

Trial used sv-ttk 2.6.1 loaded from a throwaway directory. Nothing was installed into the app environment. A withdrawn Tk window applied clam, then the button, notebook-tab, and treeview options that `setup_styles` sets.

Measured lookups:

- Clam with those options: theme `clam`, TButton padding `16 8`, TButton background `#252D38`, tab padding `12 6`, Treeview background `#252D38`, a classic Tk label background `#1E2530`.
- After `sv_ttk.set_theme("dark")`: theme `sun-valley-dark`, TButton padding `8 2 8 3`, TButton background empty, tab padding empty, Treeview background `#1c1c1c`. The Tk label stayed `#1E2530`.

`set_theme` leaves clam and drops the Fizgig padding and colors. Banners, cards, and previews are Tk and Canvas widgets on the Fizgig palette, so Sun Valley would paint the ttk controls and leave the rest of the window on the current colors. Writing the clam options again after `set_theme` stores the values, and the theme name stays `sun-valley-dark`.

`requirements.txt` and `THIRD_PARTY_NOTICES.md` are unchanged. Startup does not import sv-ttk.

The preference key `appearance` selects `dark-clam` or `compact-clam`. `resolve_appearance` maps an empty or unknown value to `dark-clam`. `setup_styles` applies that id once, after preferences load and before the notebook is built. Choosing the other appearance in Preferences saves it and leaves the open window on the spacing it started with until the next launch.

The bottom status bar sizes to its contents so the live sample controls fit at either spacing and at larger display scales.

Run `python -m unittest discover -s checks -p "test_*.py" -v` for the focused regression checks. The layout check uses withdrawn Tk windows at 100%, 125%, and 150% scaling without importing the trainer. The launch-check tests mock subprocesses; they do not launch Fizgig. The actual `check_appearance.py --launch <scratch-dir>` check exits nonzero when validation fails, including exit code 2 when the display or Tk runtime is unavailable. Diagnostic logs remain in the scratch directory.
