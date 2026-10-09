# Web UI phase 1

**Status:** 1a built, uncommitted. Written 2026-10-08 on commit 70573c0 plus this uncommitted tree.

**1a result:** the Training tab is a declarative form. `GET /api/form?family=<id>` returns that family's fields in desktop order, then the `train.py` flags the form does not already cover. `launch.plan()` matches the desktop command builders for all 39 built-in presets. The 8 edit and slider presets match once the pair folder has one PNG. With that folder left empty, `_generic_validate_paths` and `launch.problems()` return the same list. `launch.py` and the desktop app were not changed.

## 1a

### Fields served

Description-driven controls (network type, optimizer, base precision, model area, and each family's own options) come from the `FamilyDescription`. Everything else `create_training_settings` shows is in `src/fizgig/web/form_spec.py`. A field is included when that family can show it. `when` says when it is hidden inside the family (Adaptive LR off, LoKR, Edit, Slider, Fine-tune, a clip in the dataset, the captioner file set).

Auto-recaption is on the form for every family with the loss watch, and only while the captioner path is set. Clip Target Megapixels is on the form for a family whose media include clips, and only while the dataset contains a clip. The Samples tab is not part of this form. The golden comparison feeds the desktop Samples tab's current values into both launches, including MiniMax's sample-length option (the Samples tab starts at 56 frames with sound; that option's first choice is Still).

| Family | Fields | Advanced | Unmapped |
|---|---:|---:|---|
| Klein 9B | 73 | 33 | Attention Mechanism, Logging Directory, Log With, Log Prefix |
| MiniMax H3 | 82 | 45 | the same four |
| Krea 2 | 67 | 35 | the same four |
| Qwen Image 2.1 | 71 | 34 | the same four |
| SDXL | 65 | 39 | the same four |
| Anima | 66 | 36 | the same four |
| Z-Image Turbo | 67 | 35 | the same four |

Those four are on the Training tab. `families/train.py` has no flag for them, and `plan()` does not read them, so a value set there does not change the launch.

Not served, and why:

- Model Type is created and hidden for every described family.
- LoRA LR ratio is created and never placed. The launch still sends 1.
- The img/txt offload switch is stored and never placed.
- The RefMod card is a separate base-model entry, not one of the seven families.

### Tests and build

`.\venv\Scripts\python.exe -m unittest discover -s checks -p "test_*.py" -v`

15 tests, 14 passed, 1 skipped, 0 failed. The skipped test is the golden test. It stays off unless `FIZGIG_GOLDEN` is `1`, so the default suite does not build the desktop window.

`FIZGIG_GOLDEN=1` and `python -m unittest checks.test_web_golden -v`

1 test, passed. 39 built-in presets. The cache commands, the train command, the dataset TOML, and the written files were the same after temp paths and line endings were normalised.

`npm --prefix webui run build` passed. `tsc --noEmit` and Vite both ran.

### Edit and slider presets

These 8 are in the 39. The comparison sets the folder a user must fill, on the desktop widget and the web form, with one PNG named like the training photo.

Slider presets, the -1 end folder:

- MiniMax H3, `✨ MiniMax H3 Slider (rank 8, 2e-4)`
- Krea 2, `✨ Krea 2 Slider (rank 8, 2e-4)`
- Qwen Image 2.1, `✨ Qwen 2.1 Slider (rank 8, 2e-4)`
- SDXL, `✨ SDXL Slider (rank 32, alpha 16, 5e-5)`
- Anima, `✨ Anima Slider (rank 8, 2e-4)`
- Z-Image Turbo, `✨ Z-Image Turbo Slider (rank 8, 2e-4)`

Edit presets, the Originals folder:

- Qwen Image 2.1, `✨ Qwen 2.1 Edit (rank 8, adaptive LR)`
- Qwen Image 2.1, `✨ Qwen 2.1 Edit Strong (rank 16, adaptive LR) - trickier edits`

With that folder left empty, `_generic_validate_paths(desc)` and `launch.problems()` on the web inputs return the same list. The desktop Start button refuses the run there too. `_generic_cache_command`, `_generic_train_command`, and `dataset_toml` still build a launch for an empty folder. The golden test does not compare them in that state.
