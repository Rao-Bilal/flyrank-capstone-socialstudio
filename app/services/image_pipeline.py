"""
Image variant pipeline.
Takes one source image and produces platform-correct crops:
- Instagram: 1080x1080 (1:1)
- X: 1600x900 (16:9)

Strategy: center-crop to target aspect ratio first (keeps subject in the
safe zone assuming subject is roughly centered), then resize to exact px.
"""

from PIL import Image
from dataclasses import dataclass
from pathlib import Path

@dataclass
class VariantSpec:
    platform: str
    width: int
    height: int

PLATFORM_SPECS = {
    "instagram": VariantSpec("instagram", 1080, 1080),
    "x": VariantSpec("x", 1600, 900),
}


def _center_crop_to_ratio(img: Image.Image, target_ratio: float) -> Image.Image:
    """Crop the image to target_ratio (width/height) around its center."""
    w, h = img.size
    current_ratio = w / h

    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)

    return img.crop(box)


def generate_variant(source_path: str, platform: str, output_dir: str) -> str:
    """
    Generate a single platform variant from source_path.
    Returns the output file path.
    Raises ValueError for unknown platform.
    """
    if platform not in PLATFORM_SPECS:
        raise ValueError(f"Unknown platform: {platform}")

    spec = PLATFORM_SPECS[platform]
    target_ratio = spec.width / spec.height

    with Image.open(source_path) as img:
        img = img.convert("RGB")
        cropped = _center_crop_to_ratio(img, target_ratio)
        resized = cropped.resize((spec.width, spec.height), Image.LANCZOS)

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = str(Path(output_dir) / f"{platform}.jpg")
        resized.save(out_path, "JPEG", quality=90)

    return out_path


def generate_all_variants(source_path: str, output_dir: str) -> dict[str, str]:
    """Generate variants for every configured platform. Returns {platform: path}."""
    return {
        platform: generate_variant(source_path, platform, output_dir)
        for platform in PLATFORM_SPECS
    }