"""Image prep, mirrored from the desktop helpers.

``convert_images`` chooses the mode. ``_resize_only_images``, ``_face_crop_only_images``
and ``_auto_prep_images`` do the work, with ``_resize_image``, ``_prep_target_area`` and
``_get_face_selection_mode``. Face crops call ``face_utils.crop_to_face``. The Look
filter is not mirrored.
"""
from __future__ import annotations

import ast
import glob
import math
import os
import sys
from pathlib import Path

from PIL import Image

from fizgig.web.jobs import JobError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
MODES = ("Auto Prep (Face Crops)", "Resize Only", "Face Crop Only")
MEGAPIXELS = ("0.25", "0.37", "0.5", "0.75", "1.0", "1.5", "2.0", "2.4", "3.0", "4.2")
FACES = ("Largest Face", "Largest Male Face", "Largest Female Face")
_REPO = Path(__file__).resolve().parents[3]


class StubDetector:
    """One centred face. Used when ``FIZGIG_WEB_FAKE_FACE=1``. Does not load a model."""

    def detect_from_pil(self, image):
        width, height = image.size
        x1, y1 = width // 4, height // 4
        x2, y2 = max(x1 + 1, width * 3 // 4), max(y1 + 1, height * 3 // 4)
        face = type("Face", (), {})()
        face.bbox = (x1, y1, x2, y2)
        face.gender = "female"
        face.gender_score = 1.0
        face.area = (x2 - x1) * (y2 - y1)
        face.center = ((x1 + x2) // 2, (y1 + y2) // 2)
        return [face]

    def get_largest(self, faces):
        if not faces:
            return None
        return max(faces, key=lambda face: face.area)

    def get_largest_by_gender(self, faces, gender, fallback_to_any=True):
        gender = (gender or "").lower()
        matching = [face for face in faces if face.gender == gender]
        if matching:
            return max(matching, key=lambda face: face.area)
        if fallback_to_any and faces:
            return self.get_largest(faces)
        return None


def bucket_step() -> int:
    """``RESOLUTION_STEPS`` from the dataset module, read as source so torch stays unloaded."""
    path = _REPO / "src" / "fizgig" / "dataset" / "image_dataset.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "RESOLUTION_STEPS":
                return int(ast.literal_eval(node.value))
    return 16


def target_area(mp: float) -> int:
    """Mirrors ``_prep_target_area``."""
    step = bucket_step()
    side = max(step, int(math.sqrt(max(0.0, mp) * 1_000_000)) // step * step)
    return side * side


def face_mode_of(label: str) -> str:
    """Mirrors ``_get_face_selection_mode``."""
    if "Male" in (label or ""):
        return "largest_male"
    if "Female" in (label or ""):
        return "largest_female"
    return "largest_face"


def form() -> dict:
    return {
        "modes": list(MODES),
        "megapixels": list(MEGAPIXELS),
        "faces": list(FACES),
        "defaults": {
            "mode": "Auto Prep (Face Crops)",
            "megapixels": "1.0",
            "face": "Largest Face",
            "padding": "20",
            "replace_originals": False,
        },
        "gaps": ["Look filter"],
    }


def _log(write, text: str) -> None:
    if write is not None:
        write(text)


def _atomic_png_save(img, output_path: str) -> None:
    tmp = output_path + ".fizgig-tmp"
    try:
        img.save(tmp, "PNG")
        os.replace(tmp, output_path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _safe_output_path(filepath, output_path, write) -> str:
    if not os.path.exists(output_path):
        return output_path
    try:
        if os.path.samefile(filepath, output_path):
            return output_path
    except OSError:
        pass
    stem, ext = os.path.splitext(output_path)
    n = 2
    candidate = f"{stem}_{n}{ext}"
    while os.path.exists(candidate):
        n += 1
        candidate = f"{stem}_{n}{ext}"
    _log(write, f"Name collision: {os.path.basename(output_path)} already exists — "
         f"writing {os.path.basename(candidate)} instead\n")
    return candidate


def _originals_dir(output_folder: str, cache: dict) -> str:
    if output_folder in cache:
        return cache[output_folder]

    def has_images(candidate: str) -> bool:
        if not os.path.isdir(candidate):
            return False
        return any(
            os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS
            for name in os.listdir(candidate)
            if os.path.isfile(os.path.join(candidate, name))
        )

    candidate = os.path.join(output_folder, "originals")
    if not os.path.isdir(candidate) or not has_images(candidate):
        cache[output_folder] = candidate
        return candidate
    n = 2
    while True:
        candidate = os.path.join(output_folder, f"originals_{n}")
        if not os.path.isdir(candidate) or not has_images(candidate):
            cache[output_folder] = candidate
            return candidate
        n += 1


def _stash(filepath, output_path, output_folder, replace_originals, cache) -> None:
    if replace_originals or filepath != output_path or not os.path.exists(filepath):
        return
    originals = _originals_dir(output_folder, cache)
    os.makedirs(originals, exist_ok=True)
    import shutil
    shutil.copy2(filepath, os.path.join(originals, os.path.basename(filepath)))


def _handle_original(filepath, output_path, output_folder, replace_originals, cache) -> None:
    if filepath == output_path:
        return
    if replace_originals:
        os.remove(filepath)
        return
    originals = _originals_dir(output_folder, cache)
    os.makedirs(originals, exist_ok=True)
    import shutil
    shutil.move(filepath, os.path.join(originals, os.path.basename(filepath)))


def image_files(folder: str) -> list[str]:
    found = []
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if os.path.isfile(full) and os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
            found.append(full)
    return found


def load_image(filepath: str):
    img = Image.open(filepath)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        return img.convert("RGBA")
    return img.convert("RGB")


def resize_image(img, area: int):
    """Mirrors ``_resize_image``. Returns ``(img, resized)``."""
    width, height = img.size
    if width * height <= area:
        return img, False
    step = bucket_step()
    scale = math.sqrt(area / (width * height))
    new_width = max(step, int(width * scale) // step * step)
    new_height = max(step, int(height * scale) // step * step)
    if (new_width, new_height) == (width, height):
        return img, False
    return img.resize((new_width, new_height), Image.LANCZOS), True


def _select_face(detector, faces, mode: str, write):
    if not faces:
        return None
    if mode == "largest_male":
        selected = detector.get_largest_by_gender(faces, "male", fallback_to_any=True)
        if selected and selected.gender != "male":
            _log(write, "  Note: No male face, using largest face\n")
    elif mode == "largest_female":
        selected = detector.get_largest_by_gender(faces, "female", fallback_to_any=True)
        if selected and selected.gender != "female":
            _log(write, "  Note: No female face, using largest face\n")
    else:
        selected = detector.get_largest(faces)
    return selected


def _crop(img, face, padding: float):
    root = str(_REPO)
    if root not in sys.path:
        sys.path.insert(0, root)
    from face_utils import crop_to_face

    return crop_to_face(img, face, padding)


def _next_facecrop(folder: str) -> int:
    existing = glob.glob(os.path.join(glob.escape(folder), "FaceCrop_*.png"))
    max_idx = 0
    for path in existing:
        parts = os.path.splitext(os.path.basename(path))[0].split("_")
        if len(parts) >= 2:
            try:
                max_idx = max(max_idx, int(parts[1]))
            except ValueError:
                pass
    return max_idx + 1


def resize_only(source: str, output: str, area: int, replace: bool, write=None, cache=None) -> None:
    """Mirrors ``_resize_only_images``."""
    cache = {} if cache is None else cache
    _log(write, "Mode: Resize Only\n\n")
    converted = skipped = errors = 0
    for filepath in image_files(source):
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()
        try:
            img = load_image(filepath)
            original = img.size
            img, resized = resize_image(img, area)
            width, height = img.size
            output_path = os.path.join(output, os.path.splitext(filename)[0] + ".png")
            if filepath == output_path and ext == ".png" and not resized:
                _log(write, f"Skipped (no changes): {filename}\n")
                skipped += 1
                img.close()
                continue
            output_path = _safe_output_path(filepath, output_path, write)
            _stash(filepath, output_path, output, replace, cache)
            _atomic_png_save(img, output_path)
            size_info = f"{original[0]}x{original[1]} -> {width}x{height}" if resized else f"{width}x{height}"
            _log(write, f"Converted: {filename} [{size_info}]\n")
            converted += 1
            img.close()
            _handle_original(filepath, output_path, output, replace, cache)
        except Exception as exc:
            _log(write, f"Error ({filename}): {exc}\n")
            errors += 1
    _log(write, f"\n--- Summary ---\nConverted: {converted} | Skipped: {skipped} | Errors: {errors}\n")


def face_crop_only(source, output, area, mode, padding, replace, detector, write=None, cache=None) -> None:
    """Mirrors ``_face_crop_only_images``."""
    cache = {} if cache is None else cache
    _log(write, f"Mode: Face Crop Only ({mode}, padding {padding}%)\n\n")
    converted = skipped = errors = face_crops = no_face = 0
    for filepath in image_files(source):
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()
        try:
            img = load_image(filepath)
            original = img.size
            cropped = False
            crop_info = ""
            try:
                faces = detector.detect_from_pil(img)
                if faces:
                    selected = _select_face(detector, faces, mode, write)
                    if selected:
                        img = _crop(img, selected, padding)
                        cropped = True
                        face_crops += 1
                        crop_info = f" [face: {selected.gender}]"
                else:
                    _log(write, f"  No face in {filename}, skipping crop\n")
                    no_face += 1
            except Exception as exc:
                _log(write, f"  Face error ({filename}): {exc}\n")
            img, resized = resize_image(img, area)
            width, height = img.size
            output_path = os.path.join(output, os.path.splitext(filename)[0] + ".png")
            if filepath == output_path and ext == ".png" and not resized and not cropped:
                _log(write, f"Skipped (no changes): {filename}\n")
                skipped += 1
                img.close()
                continue
            output_path = _safe_output_path(filepath, output_path, write)
            _stash(filepath, output_path, output, replace, cache)
            _atomic_png_save(img, output_path)
            size_info = f"{original[0]}x{original[1]} -> {width}x{height}" if (resized or cropped) else f"{width}x{height}"
            _log(write, f"Converted: {filename} [{size_info}]{crop_info}\n")
            converted += 1
            img.close()
            _handle_original(filepath, output_path, output, replace, cache)
        except Exception as exc:
            _log(write, f"Error ({filename}): {exc}\n")
            errors += 1
    _log(write, f"\n--- Summary ---\nConverted: {converted} | Skipped: {skipped} | Errors: {errors}\n")
    _log(write, f"Face crops: {face_crops} | No face: {no_face}\n")


def auto_prep(source, output, area, mode, padding, replace, detector, write=None, cache=None) -> None:
    """Mirrors ``_auto_prep_images``."""
    cache = {} if cache is None else cache
    _log(write, "Mode: Auto Prep (Face Crops)\n")
    _log(write, f"Face target: {mode}, padding: {padding}%\n")
    _log(write, f"Output: {output}\n\n")
    converted = skipped = errors = face_crops = no_face = 0
    crop_index = _next_facecrop(output)
    for filepath in image_files(source):
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()
        base = os.path.splitext(filename)[0]
        if base.startswith("FaceCrop_"):
            _log(write, f"Skipped (derivative): {filename}\n")
            skipped += 1
            continue
        try:
            original_img = load_image(filepath)
            original = original_img.size
            try:
                faces = detector.detect_from_pil(original_img)
                if faces:
                    selected = _select_face(detector, faces, mode, write)
                    if selected:
                        cropped = _crop(original_img, selected, padding)
                        cropped, _resized = resize_image(cropped, area)
                        crop_name = f"FaceCrop_{crop_index:03d}.png"
                        cropped.save(os.path.join(output, crop_name), "PNG")
                        cw, ch = cropped.size
                        _log(write, f"Face crop: {crop_name} ({cw}x{ch}) from {filename} ({original[0]}x{original[1]}) [{selected.gender}]\n")
                        face_crops += 1
                        crop_index += 1
                        cropped.close()
                    else:
                        no_face += 1
                else:
                    _log(write, f"No face: {filename}\n")
                    no_face += 1
            except Exception as exc:
                _log(write, f"Face crop error ({filename}): {exc}\n")
            resized_img, resized = resize_image(original_img, area)
            width, height = resized_img.size
            output_path = os.path.join(output, base + ".png")
            if filepath == output_path and ext == ".png" and not resized:
                _log(write, f"OK (no changes): {filename}\n")
                skipped += 1
                resized_img.close()
                continue
            output_path = _safe_output_path(filepath, output_path, write)
            _stash(filepath, output_path, output, replace, cache)
            _atomic_png_save(resized_img, output_path)
            size_info = f"{original[0]}x{original[1]} -> {width}x{height}" if resized else f"{width}x{height}"
            _log(write, f"Converted: {filename} [{size_info}]\n")
            converted += 1
            resized_img.close()
            _handle_original(filepath, output_path, output, replace, cache)
        except Exception as exc:
            _log(write, f"Error ({filename}): {exc}\n")
            errors += 1
    _log(write, "\n--- Summary ---\n")
    _log(write, f"Originals converted: {converted} | Skipped: {skipped} | Errors: {errors}\n")
    _log(write, f"Face crops created: {face_crops} | No face: {no_face}\n")
    _log(write, f"Total files in output: {len(image_files(output))}\n")


def _detector():
    if os.environ.get("FIZGIG_WEB_FAKE_FACE", "").strip() == "1":
        return StubDetector()
    root = str(_REPO)
    if root not in sys.path:
        sys.path.insert(0, root)
    from face_utils import FaceDetector

    return FaceDetector()


def prepare(settings: dict, write=None, detector=None) -> None:
    """Run one prep the way ``convert_images`` does, on the training folder."""
    folder = str(settings.get("folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        raise JobError(422, {"problems": ["The training image folder does not exist."]})
    mode = str(settings.get("mode") or "Resize Only")
    if mode not in MODES:
        raise JobError(422, {"problems": [f"unknown prep mode: {mode}"]})
    try:
        area = target_area(float(settings.get("megapixels") if settings.get("megapixels") not in (None, "") else 1.0))
    except (TypeError, ValueError):
        area = target_area(1.0)
    replace = bool(settings.get("replace_originals"))
    face = face_mode_of(str(settings.get("face") or "Largest Face"))
    try:
        padding = float(settings.get("padding") if settings.get("padding") not in (None, "") else 20)
    except (TypeError, ValueError):
        padding = 20.0
    os.makedirs(folder, exist_ok=True)
    if mode == "Resize Only":
        resize_only(folder, folder, area, replace, write)
        return
    if detector is None:
        detector = _detector()
    if mode == "Face Crop Only":
        face_crop_only(folder, folder, area, face, padding, replace, detector, write)
    else:
        auto_prep(folder, folder, area, face, padding, replace, detector, write)


def launch(body: dict) -> dict:
    from fizgig.web import jobs
    from fizgig.web.start import require_folder

    folder = require_folder(str(body.get("folder") or ""))
    settings = {
        "folder": folder,
        "mode": body.get("mode") or "Auto Prep (Face Crops)",
        "megapixels": str(body.get("megapixels") if body.get("megapixels") not in (None, "") else "1.0"),
        "face": body.get("face") or "Largest Face",
        "padding": str(body.get("padding") if body.get("padding") not in (None, "") else "20"),
        "replace_originals": bool(body.get("replace_originals")),
    }
    if settings["mode"] not in MODES:
        raise JobError(422, {"problems": [f"unknown prep mode: {settings['mode']}"]})
    if settings["megapixels"] not in MEGAPIXELS:
        raise JobError(422, {"problems": ["unknown megapixel target"]})
    if settings["face"] not in FACES:
        raise JobError(422, {"problems": ["unknown face target"]})
    return jobs.start_task("prep", "prep", settings, folder, None)
