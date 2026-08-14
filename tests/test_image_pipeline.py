from PIL import Image
from app.services.image_pipeline import generate_all_variants, PLATFORM_SPECS
import tempfile, os

def test_variant_dimensions():
    # make a fake source image
    with tempfile.TemporaryDirectory() as tmp:
        source_path = os.path.join(tmp, "source.jpg")
        Image.new("RGB", (2000, 1500), color="red").save(source_path)

        out_dir = os.path.join(tmp, "out")
        paths = generate_all_variants(source_path, out_dir)

        for platform, path in paths.items():
            spec = PLATFORM_SPECS[platform]
            with Image.open(path) as img:
                assert img.size == (spec.width, spec.height), (
                    f"{platform} expected {spec.width}x{spec.height}, got {img.size}"
                )