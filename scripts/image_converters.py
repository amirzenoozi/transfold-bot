from PIL import Image, ImageDraw, ImageFont
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


def add_mosaic_watermark(image_path, text):
    output_path = image_path.replace(".png", "_mosaic.png")

    with Image.open(image_path).convert("RGBA") as base:
        # 1. Create a transparent overlay
        txt_layer = Image.new("RGBA", base.size, (255, 255, 255, 0))
        d = ImageDraw.Draw(txt_layer)

        # 2. Robust Font Selection for Docker/Linux
        font = None
        # List of potential font paths in common Docker Linux distros
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "Arial.ttf"
        ]

        fontsize = int(base.width * 0.04)
        print(fontsize)
        for path in font_paths:
            if os.path.exists(path):
                font = ImageFont.truetype(path, fontsize)
                break

        if not font:
            font = ImageFont.load_default()

        # 3. Dynamic Mosaic Spacing
        # We want roughly 4-5 repeats horizontally
        w, h = base.size
        step_x = int(w / 3)
        step_y = int(h / 3)

        # 4. Draw the Grid
        # fill=(255,255,255,51) -> White with ~20% opacity (51/255)
        for x in range(0, w, step_x):
            for y in range(0, h, step_y):
                # Offset every other row for a better "mosaic" look
                current_x = x + (step_x // 2 if (y // step_y) % 2 == 1 else 0)
                d.text((current_x, y), text, font=font, fill=(255, 255, 255, 51), anchor="mm")

        # 5. Rotate the overlay
        # center=None defaults to center of image
        rotated_txt = txt_layer.rotate(45, resample=Image.BICUBIC)

        # 6. Merge and Save
        # We use alpha_composite to keep the 20% transparency clean
        combined = Image.alpha_composite(base, rotated_txt)
        combined.convert("RGB").save(output_path, "JPEG", quality=95)

    return output_path

