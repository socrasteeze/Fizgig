"""Desktop launch against launch.plan() for every built-in preset.

Off unless FIZGIG_GOLDEN=1. The class builds one withdrawn Tk window. It does not
load a model, start a training process, or keep the status-bar reader calling the GPU.

    $env:FIZGIG_GOLDEN='1'
    python -m unittest checks.test_web_golden -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))

_GOLDEN = os.environ.get("FIZGIG_GOLDEN") == "1"


def _norm(value, roots):
    if isinstance(value, list):
        return [_norm(item, roots) for item in value]
    if isinstance(value, tuple):
        return tuple(_norm(item, roots) for item in value)
    if not isinstance(value, str):
        return value
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    for root in roots:
        forward = root.replace("\\", "/")
        text = text.replace(root, "{tmp}").replace(forward, "{tmp}")
    return text


def _command_diff(left, right):
    if left == right:
        return ""
    lines = [f"desktop ({len(left)} commands) vs plan ({len(right)} commands)"]
    for index in range(max(len(left), len(right))):
        a = left[index] if index < len(left) else None
        b = right[index] if index < len(right) else None
        if a == b:
            continue
        if a is None or b is None or not isinstance(a, list) or not isinstance(b, list):
            lines.append(f"  [{index}] desktop={a!r}")
            lines.append(f"  [{index}] plan={b!r}")
            continue
        width = max(len(a), len(b))
        for token_i in range(width):
            ta = a[token_i] if token_i < len(a) else "<missing>"
            tb = b[token_i] if token_i < len(b) else "<missing>"
            if ta != tb:
                lines.append(f"  [{index}] token {token_i}: desktop {ta!r}")
                lines.append(f"  [{index}] token {token_i}: plan    {tb!r}")
    return "\n".join(lines)


@unittest.skipUnless(_GOLDEN, "set FIZGIG_GOLDEN=1")
class WebGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        cls._tmp = Path(tempfile.mkdtemp(prefix="fizgig-golden-"))
        os.environ["FIZGIG_PREFS_FILE"] = str(cls._tmp / "prefs.json")
        os.environ["FIZGIG_LAST_USED_FILE"] = str(cls._tmp / "last_used.json")

        from fizgig.families.registry import FAMILIES

        models = cls._tmp / "models"
        models.mkdir()
        prefs = {
            "cuda_device": "",
            "appearance": "dark-clam",
            "cache_dir": str(cls._tmp / "cache"),
            "lora_output_dir": str(cls._tmp / "output"),
            "profiles_dir": str(cls._tmp / "profiles"),
        }
        for desc in FAMILIES.values():
            for item in desc.model_files:
                path = models / item.pref_key
                path.write_bytes(b"")
                prefs[item.pref_key] = str(path)
            speed = desc.preview_speed()
            if speed and speed.pref_key and speed.pref_key not in prefs:
                path = models / speed.pref_key
                path.write_bytes(b"")
                prefs[speed.pref_key] = str(path)
        for folder in ("cache", "output", "profiles"):
            (cls._tmp / folder).mkdir()
        (cls._tmp / "prefs.json").write_text(json.dumps(prefs), encoding="utf-8")
        cls._images = cls._tmp / "images"
        cls._images.mkdir()
        png = b"\x89PNG\r\n\x1a\n"
        (cls._images / "photo.png").write_bytes(png)
        (cls._images / "photo.txt").write_text("a photo\n", encoding="utf-8")
        # The same file name as the training photo, so an edit or a slider has one pair.
        cls._originals = cls._tmp / "originals"
        cls._slider_minus = cls._tmp / "slider-minus"
        for folder in (cls._originals, cls._slider_minus):
            folder.mkdir()
            (folder / "photo.png").write_bytes(png)

        import tkinter as tk
        import lora_trainer_gui as gui_mod

        gui_mod.LoRATrainerGUI._read_vram = lambda self: None
        gui_mod.LoRATrainerGUI._family_ft_plan_refresh = lambda self: None
        cls._root = tk.Tk()
        cls._root.withdraw()
        cls.gui = gui_mod.LoRATrainerGUI(cls._root)
        cls.gui._status_stop = True

    @classmethod
    def tearDownClass(cls):
        gui = getattr(cls, "gui", None)
        if gui is not None:
            gui._status_stop = True
        root = getattr(cls, "_root", None)
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

    def _sync_settings(self, desc):
        """Copy Training-tab widgets into settings the way a launch does, without resolving Auto on the GPU."""
        gui = self.gui
        entries = gui.entries

        def read(key):
            return entries[key].get()

        try:
            learning_rate = float(read("LEARNING_RATE"))
        except ValueError:
            learning_rate = 1e-4
        gui.settings.update({
            "LEARNING_RATE": learning_rate,
            "LORA_LR_RATIO": int(float(read("LORA_LR_RATIO") or 1)),
            "NETWORK_DIM": int(float(read("NETWORK_DIM"))),
            "NETWORK_ALPHA": float(read("NETWORK_ALPHA")),
            "NETWORK_TYPE": read("NETWORK_TYPE"),
            "LOKR_FACTOR": int(float(read("LOKR_FACTOR") or 8)),
            "MAX_TRAIN_EPOCHS": int(float(read("MAX_TRAIN_EPOCHS"))),
            "SAVE_EVERY_N_EPOCHS": int(float(read("SAVE_EVERY_N_EPOCHS"))),
            "SEED": int(float(read("SEED"))),
            "BLOCKS_SWAP": read("BLOCKS_SWAP"),
            "LORA_OUTPUT_DIR": read("LORA_OUTPUT_DIR"),
            "LORA_NAME": read("LORA_NAME"),
            "RESUME_TRAINING": read("RESUME_TRAINING"),
            "OPTIMIZER_TYPE": read("OPTIMIZER_TYPE"),
            "OPTIMIZER_ARGS": read("OPTIMIZER_ARGS"),
            "LR_SCHEDULER": read("LR_SCHEDULER"),
            "LR_WARMUP_STEPS": read("LR_WARMUP_STEPS"),
            "GRADIENT_ACCUMULATION": read("GRADIENT_ACCUMULATION"),
            "MAX_GRAD_NORM": read("MAX_GRAD_NORM"),
            "CONTEXT_LORA_PATH": read("CONTEXT_LORA_PATH"),
            "CONTEXT_LORA_STRENGTH": read("CONTEXT_LORA_STRENGTH"),
            "MIN_TIMESTEP": read("MIN_TIMESTEP"),
            "MAX_TIMESTEP": read("MAX_TIMESTEP"),
            "ADAPTIVE_LR": bool(gui.adaptive_lr_var.get()),
            "ADAPTIVE_LR_MIN": read("ADAPTIVE_LR_MIN"),
            "ADAPTIVE_LR_MAX": read("ADAPTIVE_LR_MAX"),
            "COMPILE_BLOCKS": gui.compile_blocks_var.get(),
            "SAVE_STATE": bool(gui.save_state_var.get()),
            "SAVE_STATE_ON_TRAIN_END": bool(gui.save_state_on_train_end_var.get()),
            "KEEP_LAST_N_STATES": read("KEEP_LAST_N_STATES"),
            "FAMILY_EMA": read("FAMILY_EMA"),
            "FAMILY_PRECISION": read("FAMILY_PRECISION"),
            "FAMILY_TURBO_STRENGTH": read("FAMILY_TURBO_STRENGTH") if "FAMILY_TURBO_STRENGTH" in entries else "",
        })
        for key in ("METADATA_TITLE", "METADATA_AUTHOR", "METADATA_DESCRIPTION", "METADATA_LICENSE",
                    "METADATA_TAGS", "METADATA_TRIGGER_PHRASE", "METADATA_THUMBNAIL"):
            gui.settings[key] = read(key)
        if desc.samples_turbo_pace:
            gui.settings["FAMILY_TURBO_STEPS"] = read("FAMILY_TURBO_STEPS")
            gui.settings["FAMILY_TURBO_PACE"] = read("FAMILY_TURBO_PACE")

    def _context(self, desc, dataset_config):
        gui = self.gui
        samples = {
            "enabled": bool(gui.sample_enabled_var.get()),
            "every": gui.sample_every_n_epochs_var.get().strip(),
            "width": gui.sample_width_var.get().strip(),
            "height": gui.sample_height_var.get().strip(),
            "steps": gui.sample_steps_var.get().strip(),
            "cfg": gui.sample_cfg_scale_var.get().strip(),
            "negative": gui.sample_negative_var.get().strip() if getattr(gui, "sample_negative_var", None) else "",
            "seed": gui.sample_seed_var.get().strip(),
            "at_first": bool(getattr(gui, "sample_at_first_var", None) and gui.sample_at_first_var.get()),
            "prompts": gui.sample_prompt_text.get("1.0", "end").splitlines(),
            "reference": gui.sample_ref_image_var.get().strip() if getattr(gui, "sample_ref_image_var", None) else "",
        }
        if desc.train_preview_checkpoint:
            samples["checkpoint"] = bool(gui.use_distilled_samples_var.get())
            samples["checkpoint_cache"] = gui.cache_sample_model_var.get()
            samples["int8"] = bool(gui._get_inference_int8())
        live = gui._family_options_values(desc)
        option_values = {opt.key: live[opt.key] for opt in desc.options if opt.tab == "samples" and opt.key in live}
        return {
            "models": {key: gui._krea2_pref(key) for key in gui.prefs_vars},
            "cache_root": gui.prefs_vars["cache_dir"].get().strip() if "cache_dir" in gui.prefs_vars else "",
            "captioner": gui._qwen_captioner_path(),
            "caption_trigger": gui.caption_text_var.get().strip() if hasattr(gui, "caption_text_var") else "",
            "caption_overrides": gui._caption_overrides(),
            "samples": samples,
            "DATASET_CONFIG": dataset_config,
            "option_values": option_values,
            "FAMILY_TURBO_STRENGTH": gui.entries["FAMILY_TURBO_STRENGTH"].get()
            if "FAMILY_TURBO_STRENGTH" in gui.entries else "",
            "FAMILY_TURBO_STEPS": gui.entries["FAMILY_TURBO_STEPS"].get() if desc.samples_turbo_pace else "",
            "FAMILY_TURBO_PACE": gui.entries["FAMILY_TURBO_PACE"].get() if desc.samples_turbo_pace else "",
        }

    def _pair_slot(self, desc, preset):
        """The folder an edit or a photo-pair slider must have, or None."""
        if preset.get("FAMILY_EDIT") and desc.edit_training:
            return "FAMILY_EDIT_DIR", self._originals
        source = preset.get("FAMILY_SLIDER_SOURCE") or "pairs"
        if preset.get("FAMILY_SLIDER") and desc.slider_training and source != "prompts":
            return "FAMILY_SLIDER_DIR", self._slider_minus
        return None

    def _set_nondefault_samples(self):
        """Prompts, resolution, frequency, and seed away from the family's defaults."""
        gui = self.gui
        box = gui.sample_prompt_text
        box.delete("1.0", "end")
        box.insert("1.0", "a red chair in an empty room\na blue cup on a table")
        gui.sample_enabled_var.set(True)
        gui.sample_width_var.set("1280")
        gui.sample_height_var.set("640")
        gui.sample_every_n_epochs_var.set("3")
        gui.sample_seed_var.set("4242")
        gui.sample_at_first_var.set(False)
        gui.sample_steps_var.set("33")
        gui.sample_cfg_scale_var.set("2.5")
        if getattr(gui, "sample_negative_var", None) is not None:
            gui.sample_negative_var.set("blurry, watermark")

    def _compare(self, desc, name, preset, override_samples=False):
        from fizgig.families import launch
        from fizgig.web.form_spec import gui_preset, web_values
        from fizgig.web.inputs import build

        gui = self.gui
        gui.architecture_var.set(desc.gui_label)
        gui.update_ui_for_architecture()
        gui.update_samples_ui_for_architecture()
        # A fine-tune leaves the epoch boxes disabled, and a later preset's write is then dropped.
        # Enable them first so this preset's own numbers land.
        for key in ("MAX_TRAIN_EPOCHS", "SAVE_EVERY_N_EPOCHS", "LEARNING_RATE"):
            try:
                gui.entries[key].configure(state="normal")
            except Exception:
                pass
        gui._apply_preset_values(gui_preset(desc, dict(preset)))

        run = self._tmp / "runs" / desc.key / str(abs(hash(name)) % 10_000_000)
        run.mkdir(parents=True, exist_ok=True)
        output = run / "out"
        output.mkdir(exist_ok=True)
        dataset_config = str(run / "dataset.toml")
        gui.image_folder_var.set(str(self._images))
        box = gui.entries["LORA_OUTPUT_DIR"]
        box.delete(0, "end")
        box.insert(0, str(output))
        gui.settings["DATASET_CONFIG"] = dataset_config
        gui.settings["LORA_OUTPUT_DIR"] = str(output)
        gui._generic_samples_ui(desc)
        self._sync_settings(desc)
        if override_samples:
            self._set_nondefault_samples()
        if "FAMILY_TURBO_STRENGTH" in gui.entries:
            gui.settings["FAMILY_TURBO_STRENGTH"] = gui.entries["FAMILY_TURBO_STRENGTH"].get()

        values = web_values(desc, dict(preset))
        values["image_folder"] = str(self._images)
        values["LORA_OUTPUT_DIR"] = str(output)
        context = self._context(desc, dataset_config)
        parts = []
        slot = self._pair_slot(desc, preset)
        if slot:
            key, folder = slot
            # The preset leaves the pair folder empty. Both Start checks must refuse it the same way.
            desktop_problems = gui._generic_validate_paths(desc)
            web_problems = launch.problems(desc, build(desc, values, context))
            if list(desktop_problems) != list(web_problems):
                parts.append(
                    "empty pair folder:\n"
                    f"  _generic_validate_paths: {desktop_problems!r}\n"
                    f"  launch.problems: {web_problems!r}"
                )
            box = gui.entries[key]
            box.delete(0, "end")
            box.insert(0, str(folder))
            values[key] = str(folder)
        web = launch.plan(desc, build(desc, values, context))
        desktop_inputs = gui._family_launch_inputs(desc)
        try:
            desktop_toml = launch.dataset_toml(desc, desktop_inputs)
        except (TypeError, ValueError) as exc:
            desktop_toml = f"<raised {exc}>"
        ran_cache = launch.caches(desc, desktop_inputs)
        desktop_cmds = []
        if ran_cache:
            desktop_cmds.append(gui._generic_cache_command(desc, "latents"))
            desktop_cmds.append(gui._generic_cache_command(desc, "text"))
        desktop_cmds.append(gui._generic_train_command(desc))

        roots = [str(self._tmp)]
        desktop_cmds = _norm(desktop_cmds, roots)
        web_cmds = _norm([stage.cmd for stage in web.stages], roots)
        if web.problems:
            parts.append("plan problems:\n  " + "\n  ".join(web.problems))
        command_diff = _command_diff(desktop_cmds, web_cmds)
        if command_diff:
            parts.append(command_diff)
        web_toml = _norm(web.dataset_toml, roots)
        desk_toml = _norm(desktop_toml, roots)
        if web_toml != desk_toml:
            parts.append("dataset TOML differs")
            parts.append("--- desktop")
            parts.append(desk_toml)
            parts.append("--- plan")
            parts.append(web_toml)
        written = []
        for path, text in web.files:
            if os.path.normcase(path) == os.path.normcase(dataset_config):
                continue
            disk = Path(path)
            got = disk.read_text(encoding="utf-8") if disk.is_file() else "<not written>"
            if _norm(got, roots) != _norm(text, roots):
                written.append(f"{path}\n  desktop: {got!r}\n  plan: {text!r}")
        # Files the desktop wrote that plan did not list.
        sample_dir = Path(gui.get_samples_dir())
        planned = {os.path.normcase(path) for path, _text in web.files}
        if sample_dir.is_dir():
            for path in sample_dir.rglob("*"):
                if path.is_file() and os.path.normcase(str(path)) not in planned:
                    written.append(f"desktop wrote {path} and plan did not list it")
        if written:
            parts.append("files:\n" + "\n".join(written))
        if not parts:
            return ""
        return f"{desc.key} / {name}\n" + "\n".join(parts)

    def test_builtin_presets_match_desktop(self):
        from fizgig.families.registry import FAMILIES

        mismatches = []
        for desc in FAMILIES.values():
            for name, preset in desc.presets:
                diff = self._compare(desc, name, preset)
                if diff:
                    mismatches.append(diff)
        self.assertFalse(mismatches, "\n\n".join(mismatches))

    def test_preset_with_sample_overrides_matches_desktop(self):
        from fizgig.families.registry import FAMILIES

        mismatches = []
        for desc in FAMILIES.values():
            if not desc.presets:
                continue
            name, preset = desc.presets[0]
            diff = self._compare(desc, name + " samples", preset, override_samples=True)
            if diff:
                mismatches.append(diff)
        self.assertFalse(mismatches, "\n\n".join(mismatches))


if __name__ == "__main__":
    unittest.main()
