from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from app.config import settings


def add_text_to_thumbnail(
    input_path: str,
    output_path: str,
    text: str,
    position: str = "bottom"
) -> str:
    """
    Add text overlay to a thumbnail image.

    Args:
        input_path: Path to source image
        output_path: Path to save result
        text: Text to overlay (should be short, 2-4 words)
        position: "top", "center", or "bottom"
    """
    img = Image.open(input_path)
    draw = ImageDraw.Draw(img)

    # Font paths to try (bold fonts for clickbait style)
    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSans-Black.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-ExtraBold.ttf",
        "/var/www/shortgen/assets/fonts/Bangers-Regular.ttf",  # Custom clickbait font
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]

    # Use width-based sizing for vertical images to prevent text overflow
    font_size = int(min(img.width / 6, img.height / 12))

    # Try to load a bold font
    font = None
    try:
        for fp in font_paths:
            if Path(fp).exists():
                font = ImageFont.truetype(fp, font_size)
                break
        if not font:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # Get text bounding box
    text = text.upper()

    # Reduce font size if text is too wide
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    while text_width > img.width * 0.9 and font_size > 20:
        font_size = int(font_size * 0.85)
        for fp in font_paths:
            if Path(fp).exists():
                font = ImageFont.truetype(fp, font_size)
                break
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]

    text_height = bbox[3] - bbox[1]

    # Calculate position
    x = (img.width - text_width) // 2

    if position == "top":
        y = int(img.height * 0.1)
    elif position == "center":
        y = (img.height - text_height) // 2
    else:  # bottom
        y = int(img.height * 0.85) - text_height  # Position near bottom

    # Draw thick black outline for clickbait look
    outline_size = max(3, font_size // 12)

    # Draw black outline (multiple passes for thickness)
    for dx in range(-outline_size, outline_size + 1):
        for dy in range(-outline_size, outline_size + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))

    # Draw green text (brand color)
    draw.text((x, y), text, font=font, fill=(76, 175, 80))  # Green (#4CAF50)

    # Save
    img.save(output_path, quality=95)
    return output_path


def make_vertical_thumbnail(input_path: str, output_path: str, target_width: int = 1080, target_height: int = 1920) -> str:
    """
    Convert image to vertical 9:16 format for YouTube Shorts.
    Crops center if needed.
    """
    img = Image.open(input_path)
    orig_width, orig_height = img.size

    target_ratio = target_width / target_height  # 0.5625 for 9:16
    orig_ratio = orig_width / orig_height

    if orig_ratio > target_ratio:
        # Image is too wide - crop sides
        new_width = int(orig_height * target_ratio)
        left = (orig_width - new_width) // 2
        img = img.crop((left, 0, left + new_width, orig_height))
    elif orig_ratio < target_ratio:
        # Image is too tall - crop top/bottom
        new_height = int(orig_width / target_ratio)
        top = (orig_height - new_height) // 2
        img = img.crop((0, top, orig_width, top + new_height))

    # Resize to target dimensions
    img = img.resize((target_width, target_height), Image.LANCZOS)
    img.save(output_path, quality=95)
    return output_path


def create_thumbnail_variants(
    base_image_path: str,
    output_dir: Path,
    text_fi: str,
    text_en: str
) -> dict:
    """
    Create thumbnail variants with Finnish and English text.
    All thumbnails are vertical 9:16 format for YouTube Shorts.

    Returns dict with paths to both thumbnails.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # First convert base image to vertical format
    vertical_base = str(output_dir / "thumbnail_base_vertical.jpg")
    make_vertical_thumbnail(base_image_path, vertical_base)

    # Finnish thumbnail
    fi_path = str(output_dir / "thumbnail_fi.jpg")
    add_text_to_thumbnail(vertical_base, fi_path, text_fi)

    # English thumbnail
    en_path = str(output_dir / "thumbnail_en.jpg")
    add_text_to_thumbnail(vertical_base, en_path, text_en)

    # Also keep a clean version without text
    clean_path = str(output_dir / "thumbnail_clean.jpg")
    img = Image.open(vertical_base)
    img.save(clean_path, quality=95)

    return {
        "fi": fi_path,
        "en": en_path,
        "clean": clean_path
    }
