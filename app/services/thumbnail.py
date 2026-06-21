from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from app.config import settings


def _hex_to_rgb(hex_color):
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return (76, 175, 80)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (76, 175, 80)


def add_text_to_thumbnail(
    input_path: str,
    output_path: str,
    text: str,
    position: str = "bottom",
    text_color: str = None,
) -> str:
    """
    Add text overlay to a thumbnail image. Supports multiple lines.

    Args:
        input_path: Path to source image
        output_path: Path to save result
        text: Text to overlay (can contain newlines for multiple lines)
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

    # Convert to uppercase and split into lines
    text = text.upper()
    lines = text.split('\n')

    # Auto-wrap long lines that would exceed image width
    max_text_width = img.width * 0.85  # Leave 15% margin
    wrapped_lines = []
    for line in lines:
        words = line.split()
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] > max_text_width and current_line:
                wrapped_lines.append(current_line)
                current_line = word
            else:
                current_line = test_line
        if current_line:
            wrapped_lines.append(current_line)
    lines = wrapped_lines if wrapped_lines else lines

    # Find the widest line and reduce font size if still needed
    def get_max_line_width():
        return max(draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0] for line in lines)

    while get_max_line_width() > img.width * 0.85 and font_size > 20:
        font_size = int(font_size * 0.85)
        for fp in font_paths:
            if Path(fp).exists():
                font = ImageFont.truetype(fp, font_size)
                break
        # Re-wrap with new font size
        wrapped_lines = []
        for line in text.split('\n'):
            words = line.split()
            current_line = ""
            for word in words:
                test_line = f"{current_line} {word}".strip()
                bbox = draw.textbbox((0, 0), test_line, font=font)
                if bbox[2] - bbox[0] > max_text_width and current_line:
                    wrapped_lines.append(current_line)
                    current_line = word
                else:
                    current_line = test_line
            if current_line:
                wrapped_lines.append(current_line)
        lines = wrapped_lines if wrapped_lines else lines

    # Calculate total text block height
    line_height = int(font_size * 1.2)
    total_height = line_height * len(lines)

    # Calculate starting Y position
    if position == "top":
        start_y = int(img.height * 0.1)
    elif position == "center":
        start_y = (img.height - total_height) // 2
    else:  # bottom
        start_y = int(img.height * 0.85) - total_height

    # Draw thick black outline for clickbait look
    outline_size = max(3, font_size // 12)

    # Draw each line centered
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = (img.width - line_width) // 2
        y = start_y + (i * line_height)

        # Draw black outline (multiple passes for thickness)
        for dx in range(-outline_size, outline_size + 1):
            for dy in range(-outline_size, outline_size + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))

        # Draw green text (brand color)
        draw.text((x, y), line, font=font, fill=_hex_to_rgb(text_color))  # default brand green

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
    text_en: str,
    text_color: str = None,
    target_width: int = 1080,
    target_height: int = 1920,
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
    make_vertical_thumbnail(base_image_path, vertical_base, target_width, target_height)

    # Finnish thumbnail
    fi_path = str(output_dir / "thumbnail_fi.jpg")
    add_text_to_thumbnail(vertical_base, fi_path, text_fi, text_color=text_color)

    # English thumbnail
    en_path = str(output_dir / "thumbnail_en.jpg")
    add_text_to_thumbnail(vertical_base, en_path, text_en, text_color=text_color)

    # Also keep a clean version without text
    clean_path = str(output_dir / "thumbnail_clean.jpg")
    img = Image.open(vertical_base)
    img.save(clean_path, quality=95)

    return {
        "fi": fi_path,
        "en": en_path,
        "clean": clean_path
    }
