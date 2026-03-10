from PIL import Image
from pillow_heif import register_heif_opener
import os

# This line is critical! It enables HEIC support globally for Pillow
register_heif_opener()


def convert_to_jpeg(input_path: str) -> str:
    """Converts any image (including HEIC/PNG/WebP) to JPEG."""
    output_path = input_path.rsplit('.', 1)[0] + "_converted.jpg"

    # Now Image.open() will work for .heic files automatically
    with Image.open(input_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=90)

    return output_path