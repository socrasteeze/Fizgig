"""Training-tab form for one described family.

The family descriptions and ``train.py`` argparse do not cover the Training tab.
This module lists the settings ``LoRATrainerGUI.create_training_settings`` shows,
in desktop order, and merges them with the controls a ``FamilyDescription`` already
declares. Visibility follows ``_apply_training_arch_visibility``,
``_generic_training_visibility`` and ``_family_edit_rows``.

``lora_trainer_gui.py`` is not imported. A hash of each mirrored function lives in
``mirrors.py``.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from fizgig.families.launch import FT_WINDOW_SIZES, PRECISION_LABELS


KIND_CHOICES = (
    ("standard", "Standard LoRA"),
    ("edit", "Edit (original + edited photo pairs)"),
    ("slider", "Slider (a dial between two looks)"),
    ("finetune", "Fine-tune the whole model"),
)
_EMA_CHOICES = ("Off", "0.98 (recommended)", "0.99 (stronger)", "0.995 (long runs only)")
_EMA_SHORT = "Short run (window = ¼ of the run)"
_EMA_HELP = ("Checkpoints and previews come from a running average of the adapter's recent steps instead "
             "of whichever step the epoch ended on. 0.98 measured best on MiniMax H3 and Krea 2; Off is "
             "there for an A/B.")
_PRECISION_HELP = ("Auto (recommended) picks at launch from your FREE VRAM: bf16 if it fits, else INT8 (8-bit, about "
                   "half the size and the fastest), else 4-bit NF4 (smallest, slower). Only when none of those fit does "
                   "it stream blocks between CPU and GPU (Blocks Swap), which is much slower. Blocks Swap on Auto sizes "
                   "the swap for whatever precision runs; NF4 never swaps.")
_NETWORK_LABELS = {"lora": "LoRA (standard)", "lokr": "LoKR (Kronecker)"}
_MP = ("0.25", "0.37", "0.5", "0.75", "1.0", "1.5", "2.0", "2.4", "3.0", "4.2")
_LOSS_HELP = ("Tracks each image's loss (normalized for the random noise level) across epochs. Detection "
              "flags images that stay hard without improving — usually mislabeled/off-concept data — in the "
              "console, the Problem Images window, and loss_log/problem_images.json. Per-image LR also "
              "throttles them (suspects ×0.7 from ~epoch 3, confirmed stuck ×0.5 from ~epoch 5 escalating "
              "to ×0.1), eases off mined-out images (×0.6) and gives healthy learned ones a gentle boost (×1.1). Auto-recaption goes "
              "further: when an image is confirmed stuck, the Qwen3-VL text encoder looks at it and rewrites "
              "its caption from what's actually visible (appending your Captions-tab trigger word, if set), "
              "re-encodes it, and gives the image a fresh start (a 2nd attempt goes extra-detailed; still "
              "stuck after that = excluded from training entirely — edit its caption to re-admit it). "
              "Warm-up: images the Image Prep Look Filter scored as look-outliers (tight angles, "
              "profiles — real but unusual) start at ×0.4 LR and ramp to ×1.0 over the first ~4 epochs, "
              "so they refine the identity instead of fighting it while it forms; released early the "
              "moment they start improving. Run the Look Filter (scan with 3 baselines) first — it saves "
              "the scores with your dataset. Batch size 1.")
_MULTICONCEPT_HELP = ("Each folder needs its OWN trigger word, in every caption — that is the only thing "
                      "telling the subjects apart. Caption and prep every folder yourself first; this box is "
                      "training-only.")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    help: str
    kind: str
    default: object
    section: str
    order: int
    when: str = "always"
    show: str = "always"
    choices: tuple = ()
    plan: str = ""
    flag: str = ""
    toml: str = ""
    covers: tuple = ()
    source: str = "spec"
    preset_key: str = ""
    windows: dict | None = None

    def to_json(self):
        body = {
            "key": self.key,
            "label": self.label,
            "help": self.help,
            "kind": self.kind,
            "default": self.default,
            "choices": list(self.choices) or None,
            "section": self.section,
            "when": self.when,
            "plan": self.plan or None,
            "flag": self.flag or None,
            "toml": self.toml or None,
            "source": self.source,
        }
        if self.windows is not None:
            body["windows"] = self.windows
        return body


def _f(key, label, help, kind, default, section, order, **kw):
    return Field(key, label, help, kind, default, section, order, **kw)


# Desktop order: Base Model, Output, Training Parameters, Memory & Precision,
# Timestep & Noise Schedule, Optimizer, Other Options, Run.
_STATIC = (
    _f("LORA_OUTPUT_DIR", "Output Directory",
       "Remembered per model family. Default: output_loras inside Fizgig.",
       "folder", "", "Output", 20, plan="LORA_OUTPUT_DIR", flag="--output_dir"),
    _f("LORA_NAME", "LoRA Name", "", "text", "", "Output", 21,
       plan="LORA_NAME", flag="--output_name"),
    _f("LEARNING_RATE", "Learning Rate", "", "float", 4e-4, "Training Parameters", 100,
       plan="LEARNING_RATE", flag="--learning_rate"),
    _f("ADAPTIVE_LR", "Adaptive LR (auto-adjust based on loss, gradient clipping & weight-norm growth)",
       "When on, the Learning Rate box is ignored. The run starts at the geometric midpoint of Min/Max "
       "and the watcher owns the learning rate from there.",
       "bool", False, "Training Parameters", 101, show="adaptive", plan="ADAPTIVE_LR", flag="--adaptive_lr"),
    _f("ADAPTIVE_LR_MIN", "Min LR", "", "choice", "1e-5", "Training Parameters", 102, show="adaptive",
       when="Adaptive LR is on",
       choices=("1e-5", "5e-5", "1e-4", "2e-4 - rank 4/8 only", "3e-4 - low-rank only"),
       plan="ADAPTIVE_LR_MIN", flag="--adaptive_lr_min"),
    _f("ADAPTIVE_LR_MAX", "Max LR", "", "choice", "4e-4", "Training Parameters", 103, show="adaptive",
       when="Adaptive LR is on", choices=("1e-4", "2e-4", "3e-4", "4e-4"),
       plan="ADAPTIVE_LR_MAX", flag="--adaptive_lr_max"),
    _f("NETWORK_DIM", "Network Dim (Rank)", "", "int", 4, "Training Parameters", 104,
       when="Network Type is LoRA", plan="NETWORK_DIM", flag="--network_dim"),
    _f("NETWORK_ALPHA", "Network Alpha", "", "float", 4, "Training Parameters", 105,
       when="Network Type is LoRA", plan="NETWORK_ALPHA", flag="--network_alpha"),
    _f("MAX_TRAIN_EPOCHS", "Max Epochs", "", "int", 12, "Training Parameters", 106,
       when="Kind of training is not Fine-tune", plan="MAX_TRAIN_EPOCHS", flag="--max_train_epochs"),
    _f("SAVE_EVERY_N_EPOCHS", "Save Every N Epochs", "", "int", 1, "Training Parameters", 107,
       when="Kind of training is not Fine-tune", plan="SAVE_EVERY_N_EPOCHS", flag="--save_every_n_epochs"),
    _f("SEED", "Seed", "", "int", 42, "Training Parameters", 108, plan="SEED", flag="--seed"),
    _f("CONTEXT_LORA_PATH", "Context LoRA",
       "Trains with an existing LoRA active on the base. Use the same LoRA and strength at inference.",
       "path", "", "Training Parameters", 112, when="Kind of training is not Fine-tune",
       plan="CONTEXT_LORA_PATH", flag="--context_lora_path"),
    _f("CONTEXT_LORA_STRENGTH", "Context LoRA strength", "", "float", "1.0", "Training Parameters", 113,
       when="Kind of training is not Fine-tune", plan="CONTEXT_LORA_STRENGTH", flag="--context_lora_strength"),
    _f("megapixels", "Target Megapixels",
       "Images are resized to this area. Any aspect ratio, no additional prep needed beyond the Image Prep tab. "
       "Higher = more detail, more VRAM per step; 4.2 MP wants 24-32 GB.",
       "choice", "0.25", "Training Parameters", 114, choices=_MP, plan="megapixels", toml="resolution",
       preset_key="DATASET_MEGAPIXELS", covers=("--slider_bank_res",)),
    _f("clip_megapixels", "Clip Target Megapixels",
       "The size your video clips are cached and trained at; photos keep the Target Megapixels above. "
       "A clip takes far more memory and time than a photo of the same size.",
       "choice", "0.25", "Training Parameters", 115, show="clips",
       when="the dataset contains a clip", choices=_MP, plan="clip_megapixels", toml="clip_megapixels",
       preset_key="CLIP_MEGAPIXELS"),
    _f("LOKR_FACTOR", "LoKR Factor",
       "8 is the sweet spot. 4 = four times the parameters: stronger, a bigger file, and more VRAM with adamw. "
       "Above 8: use LoRA.",
       "int", 8, "Training Parameters", 117, show="lokr", when="Network Type is LoKR",
       plan="LOKR_FACTOR", flag="--lokr_factor"),
    _f("KREA2_LOSS_WATCH", "Detect problem images (per-image loss tracking)", _LOSS_HELP,
       "bool", False, "Training Parameters", 118, show="loss", plan="loss_watch.detect",
       flag="--log_per_image_loss"),
    _f("KREA2_PER_IMAGE_LR",
       "Per-image adaptive LR (throttle stuck images, boost healthy learned ones) — experimental", "",
       "bool", False, "Training Parameters", 119, show="loss",
       when="Batch Size is 1, and the optimizer is not automagic3",
       plan="loss_watch.per_image_lr", flag="--per_image_lr"),
    _f("KREA2_AUTO_RECAPTION",
       "Auto-recaption stuck images (Qwen3-VL rewrites the caption between epochs) — experimental", "",
       "bool", False, "Training Parameters", 120, show="loss",
       when="the captioner file is set in Preferences, and Batch Size is 1",
       plan="loss_watch.recaption", flag="--auto_recaption", covers=("--captioner", "--trigger_word",
                                                                      "--recaption_instruction",
                                                                      "--recaption_instruction_detailed")),
    _f("KREA2_WARMUP_LOOK",
       "Warm up look outliers (unusual angles ease in at low LR — needs a Look Filter scan) — experimental", "",
       "bool", False, "Training Parameters", 121, show="loss",
       when="Batch Size is 1, and the optimizer is not automagic3",
       plan="loss_watch.warmup", flag="--warmup_look_outliers"),
    _f("FAMILY_TRAINING_ADAPTER", "Training adapter (recommended)", "",
       "bool", True, "Training Parameters", 148, show="adapter",
       plan="FAMILY_TRAINING_ADAPTER", flag="--training_adapter"),
    _f("FAMILY_MULTICONCEPT", "Multi Concept — a second subject in its own folder", _MULTICONCEPT_HELP,
       "bool", False, "Training Parameters", 149, show="multi", plan="FAMILY_MULTICONCEPT"),
    _f("MINIMAX_CONCEPT_DIRS", "Subject 2 folder", "", "folder", "", "Training Parameters", 150, show="multi",
       when="Multi Concept is on", plan="extra_folders"),
    _f("FAMILY_EMA", "Weight averaging (EMA)", "", "choice", "", "Training Parameters", 151, show="ema",
       plan="FAMILY_EMA", flag="--ema_decay"),
    _f("kind", "Kind of training",
       "A normal LoRA: a person, a style or a concept, learned from your captioned photos.",
       "choice", "Standard LoRA", "Training Parameters", 152, show="kinds",
       plan="FAMILY_EDIT / FAMILY_SLIDER / FAMILY_FT"),
    _f("FAMILY_FAST_ID", "Fast Identity Mode", "", "bool", False, "Training Parameters", 200, show="fastid",
       when="Kind of training is Standard LoRA", plan="FAMILY_FAST_ID", covers=("--train_blocks",)),
    _f("image_folder", "Training image folder",
       "The Start tab's folder. The Edit card shows it as the edited folder, and a photo-pair Slider shows it "
       "as the +1 end.",
       "folder", "", "Training Parameters", 161, show="edit_or_slider",
       when="Kind of training is Edit, or Slider with photo pairs", plan="image_folder", toml="image_directory"),
    _f("FAMILY_EDIT_DIR", "Originals folder (before editing)",
       "Your original, unedited photos. No captions needed. An original and its edited version must have the same crop and shape.",
       "folder", "", "Training Parameters", 162, show="edit", when="Kind of training is Edit",
       plan="FAMILY_EDIT_DIR", toml="control_directory"),
    _f("FAMILY_EDIT_CAPTION", "Captions for the edited photos",
       "Type what the edit is, for example \"Apply my concert grade.\" Write captions saves that text as the "
       "caption of every photo in the edited folder.",
       "text", "", "Training Parameters", 163, show="edit", when="Kind of training is Edit", plan="edit_caption"),
    _f("FAMILY_EDIT_REF", "Test photo for previews (optional)",
       "An original photo that is in neither folder. The previews during training show the edit applied to it. "
       "Leave empty to use the first original.",
       "path", "", "Training Parameters", 164, show="edit", when="Kind of training is Edit", plan="FAMILY_EDIT_REF"),
    _f("FAMILY_SLIDER_SOURCE", "Where the two ends come from",
       "Photo pairs: two folders of the same shots, one folder for each end of the dial. "
       "Prompts: no photos — you describe the picture and what each end adds.",
       "choice", "Photo pairs", "Training Parameters", 170, show="slider", when="Kind of training is Slider",
       choices=("Photo pairs", "Prompts"), plan="FAMILY_SLIDER_SOURCE",
       covers=("--slider_pairs", "--slider_prompts")),
    _f("FAMILY_SLIDER_DIR", "-1 end folder",
       "The same shots showing the -1 end, each with the same file name as its +1 photo. No captions in this folder.",
       "folder", "", "Training Parameters", 171, show="slider",
       when="Kind of training is Slider and the source is Photo pairs",
       plan="FAMILY_SLIDER_DIR", toml="control_directory"),
    _f("FAMILY_SLIDER_CAPTION", "Captions (one line, used for every pair)",
       "Describe what the two photos of a pair have in common, and leave out the difference.",
       "text", "", "Training Parameters", 172, show="slider",
       when="Kind of training is Slider and the source is Photo pairs", plan="FAMILY_SLIDER_CAPTION"),
    _f("FAMILY_SLIDER_BASE", "What the picture is",
       "The start of the prompt. Each end's words are added after it.",
       "text", "", "Training Parameters", 173, show="slider",
       when="Kind of training is Slider and the source is Prompts", plan="FAMILY_SLIDER_BASE"),
    _f("FAMILY_SLIDER_POS", "The +1 end adds", "", "text", "", "Training Parameters", 174, show="slider",
       when="Kind of training is Slider and the source is Prompts", plan="FAMILY_SLIDER_POS"),
    _f("FAMILY_SLIDER_NEG", "The -1 end adds", "", "text", "", "Training Parameters", 175, show="slider",
       when="Kind of training is Slider and the source is Prompts", plan="FAMILY_SLIDER_NEG"),
    _f("FAMILY_SLIDER_GUIDANCE", "Push strength",
       "How hard the ends are pushed apart. Higher gives a stronger dial but changes more than the one thing you asked for.",
       "float", "2", "Training Parameters", 176, show="slider",
       when="Kind of training is Slider and the source is Prompts",
       plan="FAMILY_SLIDER_GUIDANCE", flag="--slider_guidance"),
    _f("FAMILY_SLIDER_ULTRA", "Ultra mode",
       "Allows use at a much higher range of strengths. Affects fine detail less than a regular slider LoRA. "
       "Best for sliders from prompts; with photo pairs, best when the change is compositional.",
       "bool", False, "Training Parameters", 177, show="ultra", when="Kind of training is Slider",
       plan="FAMILY_SLIDER_ULTRA", covers=("--train_blocks",)),
    _f("FAMILY_FT_ROTATIONS", "Train for (rotations)",
       "The model's own weights train, not a LoRA. One pass through every part is a rotation.",
       "int", "10", "Training Parameters", 190, show="ft", when="Kind of training is Fine-tune",
       plan="FAMILY_FT_ROTATIONS", flag="--ft_rotations"),
    _f("FAMILY_FT_SAVE_EVERY", "Checkpoint + preview every (rotations)", "",
       "int", "1", "Training Parameters", 191, show="ft", when="Kind of training is Fine-tune",
       plan="FAMILY_FT_SAVE_EVERY", flag="--ft_save_every_rotations"),
    _f("FAMILY_FT_ROTATE_EVERY", "Each part trains for (epochs)", "",
       "int", "1", "Training Parameters", 192, show="ft", when="Kind of training is Fine-tune",
       plan="FAMILY_FT_ROTATE_EVERY", flag="--ft_rotate_every"),
    _f("FAMILY_FT_MAX_PARTS", "Window size",
       "How many parts train together in a window. Auto packs as many as the card holds.",
       "choice", FT_WINDOW_SIZES[0][0], "Training Parameters", 193, show="ft",
       when="Kind of training is Fine-tune", choices=tuple(lab for lab, _n in FT_WINDOW_SIZES),
       plan="FAMILY_FT_MAX_PARTS", flag="--ft_max_parts"),
    _f("FAMILY_FT_FUSED", "Free each gradient as soon as it's used (less memory - recommended)", "",
       "bool", True, "Training Parameters", 194, show="ft", when="Kind of training is Fine-tune",
       plan="FAMILY_FT_FUSED", flag="--ft_fused_backward"),
    _f("FAMILY_FT_REG_DIR", "Regularisation images (optional)",
       "A folder of ordinary photos of the broader class, with normal detailed captions. They train at a reduced "
       "learning rate so they hold the model's sense of that class in place. Leave empty to train without one.",
       "folder", "", "Training Parameters", 196, show="ft", when="Kind of training is Fine-tune",
       plan="FAMILY_FT_REG_DIR", toml="image_directory"),
    _f("FAMILY_FT_REG_MULT", "Regularisation LR multiplier", "",
       "choice", "0.2", "Training Parameters", 197, show="ft", when="Kind of training is Fine-tune",
       choices=("0.05", "0.1", "0.2", "0.3", "0.5", "0.75", "1.0"),
       plan="FAMILY_FT_REG_MULT", flag="--reg_lr_multiplier"),
    _f("blocks_swap", "Blocks Swap", "", "choice", "Auto (detect from GPU)", "Memory & Precision", 300,
       choices=("Auto (detect from GPU)",
                "0  (No swap — 16GB fp8 / 24GB bf16)",
                "4  (Light — 14GB fp8 / 20GB bf16)",
                "8  (Moderate — 12GB fp8 / 16GB bf16)",
                "12 (Aggressive — 10GB fp8 / 12GB bf16)",
                "16 (Max — 8GB fp8 / 10GB bf16)",
                "1", "2", "3", "5", "6", "7", "9", "10", "11", "13", "14", "15"),
       plan="blocks_swap", flag="--blocks_to_swap", preset_key="BLOCKS_SWAP"),
    _f("RESUME_TRAINING", "Resume Training",
       "Empty for a normal run. Browse to a state folder to continue with optimizer, learning rate and seed intact. "
       "Pause and Resume fill this in.",
       "folder", "", "Memory & Precision", 301, plan="RESUME_TRAINING", flag="--resume"),
    _f("COMPILE_BLOCKS", "Compile Blocks", "", "choice", "Auto", "Memory & Precision", 303, show="compiles",
       choices=("Auto", "On", "Off"), plan="COMPILE_BLOCKS", flag="--compile_blocks"),
    _f("SAVE_STATE", "Save State at each checkpoint",
       "A state holds the LoRA plus optimizer, so a run can resume exactly. At each checkpoint follows Save Every N Epochs. Pause always saves one.",
       "bool", True, "Memory & Precision", 304, plan="SAVE_STATE", flag="--save_state"),
    _f("SAVE_STATE_ON_TRAIN_END", "Save State at end of training", "",
       "bool", True, "Memory & Precision", 305, plan="SAVE_STATE_ON_TRAIN_END", flag="--save_state_on_train_end"),
    _f("KEEP_LAST_N_STATES", "Keep Last",
       "States are big, so older ones are deleted. Only this LoRA's states are touched; the newest is always kept.",
       "int", 2, "Memory & Precision", 306, plan="KEEP_LAST_N_STATES", flag="--keep_last_n_states"),
    _f("MIN_TIMESTEP", "Timestep min", "", "int", "", "Timestep & Noise Schedule", 400, show="areas",
       plan="MIN_TIMESTEP", flag="--min_timestep"),
    _f("MAX_TIMESTEP", "Timestep max", "", "int", "", "Timestep & Noise Schedule", 401, show="areas",
       plan="MAX_TIMESTEP", flag="--max_timestep"),
    _f("OPTIMIZER_ARGS", "Optimizer Args", "", "text", "", "Optimizer", 501,
       plan="OPTIMIZER_ARGS", flag="--optimizer_args"),
    _f("GRADIENT_ACCUMULATION", "Gradient Accumulation", "", "int", 1, "Optimizer", 502,
       plan="GRADIENT_ACCUMULATION", flag="--gradient_accumulation_steps"),
    _f("MAX_GRAD_NORM", "Max Grad Norm", "", "float", 1.0, "Optimizer", 503,
       plan="MAX_GRAD_NORM", flag="--max_grad_norm"),
    _f("caption_ext", "Caption Extension", "(default .txt)", "text", ".txt", "Other Options", 520,
       plan="caption_ext", toml="caption_extension", preset_key="DATASET_CAPTION_EXT"),
    _f("batch_size", "Batch Size", "(recommended: 1 — higher values need more VRAM)", "int", "1", "Other Options", 521,
       plan="batch_size", toml="batch_size", preset_key="DATASET_BATCH_SIZE"),
    _f("enable_bucket", "Enable Bucket", "", "bool", True, "Other Options", 522,
       plan="enable_bucket", toml="enable_bucket", preset_key="ENABLE_BUCKET"),
    _f("no_upscale", "No Upscale (keep small images at native size)", "", "bool", True, "Other Options", 523,
       plan="no_upscale", toml="bucket_no_upscale", preset_key="BUCKET_NO_UPSCALE"),
    _f("LR_SCHEDULER", "LR Scheduler", "", "choice", "constant", "Other Options", 524,
       choices=("constant", "constant_with_warmup", "cosine", "cosine_with_restarts", "linear", "polynomial"),
       plan="LR_SCHEDULER", flag="--lr_scheduler"),
    _f("LR_WARMUP_STEPS", "Warmup steps", "", "int", "", "Other Options", 525,
       plan="LR_WARMUP_STEPS", flag="--lr_warmup_steps"),
    _f("ATTENTION_MECHANISM", "Attention Mechanism",
       "sdpa runs on any GPU. flash3 needs flash-attn and a Hopper or Blackwell card (H100, RTX 5090).",
       "choice", "sdpa", "Other Options", 526, choices=("sdpa", "flash3")),
    _f("LOGGING_DIR", "Logging Directory", "", "folder", "", "Other Options", 527),
    _f("LOG_WITH", "Log With", "", "choice", "none", "Other Options", 528,
       choices=("none", "tensorboard", "wandb", "all")),
    _f("LOG_PREFIX", "Log Prefix", "", "text", "", "Other Options", 529),
    _f("METADATA_TITLE", "Metadata Title", "", "text", "", "Other Options", 530,
       plan="METADATA_TITLE", flag="--metadata_title"),
    _f("METADATA_AUTHOR", "Metadata Author", "", "text", "", "Other Options", 531,
       plan="METADATA_AUTHOR", flag="--metadata_author"),
    _f("METADATA_DESCRIPTION", "Metadata Description", "", "text", "", "Other Options", 532,
       plan="METADATA_DESCRIPTION", flag="--metadata_description"),
    _f("METADATA_LICENSE", "Metadata License", "", "text", "", "Other Options", 533,
       plan="METADATA_LICENSE", flag="--metadata_license"),
    _f("METADATA_TAGS", "Metadata Tags", "", "text", "", "Other Options", 534,
       plan="METADATA_TAGS", flag="--metadata_tags"),
    _f("METADATA_TRIGGER_PHRASE", "Metadata Trigger Phrase",
       "Blank uses the Captions tab's trigger word.", "text", "", "Other Options", 535,
       plan="METADATA_TRIGGER_PHRASE", flag="--metadata_trigger_phrase"),
    _f("METADATA_THUMBNAIL", "Metadata Thumbnail",
       "Blank auto-embeds the latest sample preview; type 'off' to disable.",
       "path", "", "Other Options", 536, plan="METADATA_THUMBNAIL", flag="--metadata_thumbnail"),
    _f("enable_cache", "Enable Cache Preparation", "", "bool", True, "Run", 600,
       plan="enable_cache", preset_key="ENABLE_CACHE"),
)


def _show(desc, name):
    if name == "always":
        return True
    if name == "adaptive":
        return bool(desc.adaptive_lr)
    if name == "loss":
        return bool(desc.loss_watch)
    if name == "areas":
        return bool(desc.train_areas)
    if name == "lokr":
        return "lokr" in desc.network_types and len(desc.network_types) > 1
    if name == "adapter":
        return bool(desc.training_adapter)
    if name == "ema":
        return bool(desc.ema_default)
    if name == "compiles":
        return bool(desc.compiles)
    if name == "multi":
        return bool(desc.multi_concept)
    if name == "kinds":
        return bool(desc.edit_training or desc.slider_training or desc.finetune)
    if name == "edit":
        return bool(desc.edit_training)
    if name == "slider":
        return bool(desc.slider_training)
    if name == "ultra":
        return bool(desc.slider_training and desc.slider_ultra_blocks)
    if name == "ft":
        return bool(desc.finetune)
    if name == "fastid":
        return bool(desc.identity_blocks)
    if name == "clips":
        return "clip" in desc.media
    if name == "edit_or_slider":
        return bool(desc.edit_training or desc.slider_training)
    raise KeyError(name)


def _replace(field, **kw):
    data = {name: getattr(field, name) for name in field.__dataclass_fields__}
    data.update(kw)
    return Field(**data)


def _kind_labels(desc):
    labels = []
    for key, label in KIND_CHOICES:
        if key == "standard" or (key == "edit" and desc.edit_training) or (
                key == "slider" and desc.slider_training) or (key == "finetune" and desc.finetune):
            labels.append(label)
    return tuple(labels)


def _ema_choices(desc):
    choices = list(_EMA_CHOICES)
    if desc.ema_short_run:
        choices.append(_EMA_SHORT)
    return tuple(choices)


def _ema_default(desc):
    raw = str(desc.ema_default or "")
    for choice in _ema_choices(desc):
        if choice == raw or choice.split(" ")[0] == raw:
            return choice
    return _ema_choices(desc)[0]


def _precision_labels(desc):
    labels = {**PRECISION_LABELS, **desc.precision_labels}
    order = ["auto"] + [p for p in ("bf16", "int8", "nf4", "hqq") if p in desc.precisions]
    return labels, tuple(labels[p] for p in order)


def _specialize(desc, field):
    if field.key == "LORA_NAME":
        return _replace(field, default=f"LoraName_TokenName_{desc.lora_name_suffix}")
    if field.key == "FAMILY_EMA":
        section = "Other Options" if desc.ema_section == "other" else "Training Parameters"
        order = 537 if desc.ema_section == "other" else 151
        return _replace(field, default=_ema_default(desc), choices=_ema_choices(desc),
                        help=desc.ema_hint or _EMA_HELP, section=section, order=order)
    if field.key == "FAMILY_MULTICONCEPT":
        extra = desc.multi_concept_hint or ""
        help = " ".join(part for part in (_MULTICONCEPT_HELP, extra) if part)
        return _replace(field, help=help)
    if field.key == "kind":
        return _replace(field, choices=_kind_labels(desc))
    if field.key == "FAMILY_FAST_ID" and desc.identity_blocks:
        nums = [b.split("_")[-1] for b in desc.identity_blocks]
        return _replace(field, help=(
            f"Trains only the identity blocks ({nums[0]}-{nums[-1]}): about 1.5x faster, with very close to "
            "full-model likeness. The base model's composition and styling stay more intact."))
    if field.key == "FAMILY_SLIDER_GUIDANCE":
        return _replace(field, default=f"{desc.slider_guidance:g}",
                        help=field.help + f" Start on {desc.slider_guidance:g} (values 2 to 9 tested).")
    if field.key == "FAMILY_EDIT_DIR":
        note = desc.edit_note or "An original and its edited version must have the same crop and shape."
        return _replace(field, help=note + " Your original, unedited photos. No captions needed.")
    if field.key == "COMPILE_BLOCKS":
        return _replace(field, help=desc.compile_hint or "")
    if field.key == "FAMILY_TRAINING_ADAPTER":
        return _replace(field, help=desc.training_adapter_note or "")
    return field


def _option_default(opt):
    if opt.kind == "check":
        return str(opt.default) in ("1", "True", "true")
    if opt.kind == "choice":
        if opt.default:
            return opt.pick(opt.default)
        labels = opt.choice_labels()
        return labels[0] if labels else ""
    return opt.default


_OPTIMIZER_NAMES: tuple[str, ...] | None = None


def optimizer_names() -> tuple[str, ...]:
    """``_CATALOG`` keys from ``fizgig.training.optimizers``, without importing that module."""
    global _OPTIMIZER_NAMES
    if _OPTIMIZER_NAMES is not None:
        return _OPTIMIZER_NAMES
    path = Path(__file__).resolve().parents[1] / "training" / "optimizers.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id != "_CATALOG":
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    found.append(key.value)
    if not found:
        found = ["adamw8bit"]
    _OPTIMIZER_NAMES = tuple(found)
    return _OPTIMIZER_NAMES


def _area_windows(desc) -> dict:
    """Model Area name -> timestep box text. The window is the area's third member times 1000."""
    windows = {}
    for area in desc.train_areas:
        name = area[0]
        span = area[2] if len(area) > 2 else None
        if span:
            windows[name] = [str(round(span[0] * 1000)), str(round(span[1] * 1000))]
        else:
            windows[name] = ["", ""]
    return windows


def _option_flags(opt):
    found = []
    tokens = [tok for _label, text in opt.choices for tok in text.split()] + opt.tokens.split()
    for tok in tokens:
        if tok.startswith("--"):
            found.append(tok.split("=", 1)[0])
    return tuple(dict.fromkeys(found))


def _option_when(opt):
    parts = []
    if opt.mode == "finetune":
        parts.append("Kind of training is Fine-tune")
    elif opt.mode == "lora":
        parts.append("Kind of training is not Fine-tune")
    if opt.show_if_media:
        parts.append(f"the dataset contains {opt.show_if_media}")
    if opt.mixed_only:
        parts.append("the dataset mixes voice with photos or clips")
    if opt.requires:
        parts.append(f"while {opt.requires}")
    if opt.always_shown and opt.requires:
        parts = [f"shown even when it is not sent; sent {parts[-1]}"] + parts[:-1]
    return "; ".join(parts) if parts else "always"


def _option_included(desc, opt):
    if opt.kind == "fixed" or opt.tab not in ("training", "model"):
        return False
    if opt.mode == "finetune" and not desc.finetune:
        return False
    if opt.show_if_media and opt.show_if_media not in desc.media:
        return False
    if opt.mixed_only and not ("voice" in desc.media and ({"photo", "clip"} & set(desc.media))):
        return False
    return True


def _description_fields(desc):
    out = []
    if len(desc.network_types) > 1:
        labels = tuple(_NETWORK_LABELS.get(name, name) for name in desc.network_types)
        out.append(Field(
            "NETWORK_TYPE", "Network Type",
            desc.network_hint or "LoKR: potentially higher quality. LoRA: about 20% faster training.",
            "choice", labels[0] if labels else "LoRA (standard)", "Training Parameters", 116,
            choices=labels, plan="NETWORK_TYPE", flag="--network_type", source="description"))
    if desc.train_areas:
        names = tuple(area[0] for area in desc.train_areas) + ("Custom",)
        blocks = []
        for _name, ids, _ts in desc.train_areas:
            for block in ids:
                if block not in blocks:
                    blocks.append(block)
        out.append(Field(
            "FAMILY_TRAIN_AREA", "Model Area to Train",
            "Chooses which blocks train. Custom uses the block list.",
            "choice", names[0], "Training Parameters", 110, choices=names,
            plan="FAMILY_TRAIN_AREA", covers=("--train_blocks",), source="description",
            preset_key="TARGET_LAYERS", windows=_area_windows(desc)))
        out.append(Field(
            "FAMILY_TRAIN_BLOCKS", "Custom blocks",
            "The block ids ticked while Model Area to Train is Custom.",
            "text", "", "Training Parameters", 111, when="Model Area to Train is Custom",
            choices=tuple(blocks), plan="FAMILY_TRAIN_BLOCKS", covers=("--train_blocks",),
            source="description", preset_key="TRAINING_BLOCKS"))
    if len(desc.precisions) > 1:
        labels, choices = _precision_labels(desc)
        late = bool(desc.precision_after_states)
        out.append(Field(
            "FAMILY_PRECISION", desc.precision_label or "Base precision",
            desc.precision_hint or _PRECISION_HELP, "choice", labels["auto"],
            "Memory & Precision", 307 if late else 302, choices=choices,
            plan="FAMILY_PRECISION", flag="--precision", source="description"))
    if desc.optimizers:
        names = optimizer_names()
        default = "adamw8bit" if "adamw8bit" in names else names[0]
        out.append(Field(
            "OPTIMIZER_TYPE", "Optimizer Type", "", "choice", default, "Optimizer", 500,
            choices=names, plan="OPTIMIZER_TYPE", flag="--optimizer_type",
            source="description"))
    counts = {"": 0, "after": 0, "other": 0, "ft": 0, "model": 0}
    base = {"": 130, "after": 140, "other": 540, "ft": 195, "model": 10}
    for opt in desc.options:
        if not _option_included(desc, opt):
            continue
        if opt.tab == "model":
            bucket = "model"
            section = "Base Model"
        elif opt.mode == "finetune":
            bucket = "ft"
            section = "Training Parameters"
        elif opt.section == "after":
            bucket = "after"
            section = "Training Parameters"
        elif opt.section == "other":
            bucket = "other"
            section = "Other Options"
        else:
            bucket = ""
            section = "Training Parameters"
        kind = {"choice": "choice", "check": "bool", "entry": "text"}.get(opt.kind, "text")
        choices = tuple(opt.choice_labels()) if opt.kind == "choice" else tuple(
            item.split("·")[0].strip() for item in opt.suggestions)
        flags = _option_flags(opt)
        out.append(Field(
            opt.key, opt.label or opt.key, opt.hint, kind, _option_default(opt), section,
            base[bucket] + counts[bucket], when=_option_when(opt), choices=choices,
            plan=f"FAMILY_OPTIONS.{opt.key}",
            flag=flags[0] if len(flags) == 1 else "", covers=flags, source="description"))
        counts[bucket] += 1
    return out


def fields_for(desc):
    """The fields this family shows, in desktop order."""
    out = [_specialize(desc, field) for field in _STATIC if _show(desc, field.show)]
    out.extend(_description_fields(desc))
    out.sort(key=lambda field: (field.order, field.key))
    return out


def _covered_flags(fields):
    covered = set()
    for field in fields:
        if field.flag:
            covered.add(field.flag)
        covered.update(field.covers)
    return covered


def form_for(desc, advanced):
    """The merged form: description fields and spec fields, then argparse flags not already covered."""
    fields = fields_for(desc)
    covered = _covered_flags(fields)
    remaining = []
    for option in advanced:
        flags = set(option.get("flags") or [])
        if flags & covered:
            continue
        remaining.append(option)
    return {"family": desc.key, "fields": [field.to_json() for field in fields], "advanced": remaining}


_PRESET_ALIAS = {field.preset_key: field.key for field in _STATIC if field.preset_key}
_PRESET_ALIAS.update({
    "TARGET_LAYERS": "FAMILY_TRAIN_AREA",
    "TRAINING_BLOCKS": "FAMILY_TRAIN_BLOCKS",
})


def _kind_label(desc, key):
    return dict(KIND_CHOICES)[key]


def web_values(desc, preset):
    """The preset's own keys, plus kind. A chip merges this onto the current form.

    Keys the preset does not carry (output folder, LoRA name, metadata, context LoRA,
    resume) stay as the page left them. The first visit still merges this onto defaults.
    """
    fields = {field.key: field for field in fields_for(desc)}
    values = {}
    for key, value in preset.items():
        canon = _PRESET_ALIAS.get(key, key)
        if canon in fields:
            values[canon] = value
        else:
            values[key] = value
    if any(key in preset for key in ("FAMILY_EDIT", "FAMILY_SLIDER", "FAMILY_FT")):
        if preset.get("FAMILY_FT"):
            picked = "finetune"
        elif preset.get("FAMILY_SLIDER"):
            picked = "slider"
        elif preset.get("FAMILY_EDIT"):
            picked = "edit"
        else:
            picked = "standard"
        if "kind" in fields:
            values["kind"] = _kind_label(desc, picked)
    return values


def gui_preset(desc, preset):
    """The same preset as the keys ``_apply_preset_values`` writes onto widgets."""
    out = {}
    for field in fields_for(desc):
        key = field.preset_key or field.key
        if field.key == "kind":
            out["FAMILY_EDIT"] = False
            out["FAMILY_SLIDER"] = False
            out["FAMILY_FT"] = False
            continue
        if field.key == "FAMILY_TRAIN_BLOCKS":
            # The desktop reads this only when the preset carries a {block: bool} map.
            continue
        if field.key == "FAMILY_SLIDER_SOURCE":
            # The radio stores "pairs" / "prompts". The form shows the desktop's wording.
            out[field.key] = "prompts" if field.default == "Prompts" else "pairs"
            continue
        if field.source == "description" and field.key not in ("NETWORK_TYPE", "FAMILY_PRECISION",
                                                               "OPTIMIZER_TYPE", "FAMILY_TRAIN_AREA",
                                                               "FAMILY_TRAIN_BLOCKS"):
            # Option rows read settings inside _apply_preset_values. Include the default so a
            # previous family's value does not linger, then let the preset override it.
            out[field.key] = field.default
            continue
        out[key] = field.default
    out.update(preset)
    return out


_UNMAPPED_REASON = {
    "ATTENTION_MECHANISM": "The Training tab shows it. families/train.py has no attention flag, and plan() does not read it.",
    "LOGGING_DIR": "The Training tab shows it. families/train.py has no logging-directory flag, and plan() does not read it.",
    "LOG_WITH": "The Training tab shows it. families/train.py has no log-with flag, and plan() does not read it.",
    "LOG_PREFIX": "The Training tab shows it. families/train.py has no log-prefix flag, and plan() does not read it.",
}


def unmapped(desc):
    """Settings on this family's form that reach neither plan(), a train.py flag, nor the dataset TOML."""
    rows = []
    for field in fields_for(desc):
        if field.plan or field.flag or field.toml or field.covers:
            continue
        rows.append((field.key, field.label, _UNMAPPED_REASON.get(
            field.key, "No plan() key, train.py flag, or dataset TOML field.")))
    return rows


def hidden_not_served():
    """Controls create_training_settings builds that the form does not serve, and why."""
    return (
        ("MODEL_TYPE", "Created on the Training tab and hidden for every described family."),
        ("LORA_LR_RATIO", "The widget is created and never placed. The launch still sends 1."),
        ("IMG_IN_TXT_IN_OFFLOADING", "A BooleanVar is stored and no row is placed."),
        ("RefMod card", "Shown only for the RefMod base-model entry, which is not a described family."),
    )
