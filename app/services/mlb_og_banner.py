"""Open Graph banner generator for MLB Daily Roundup Blot posts.

Parallel to `og_banner.py` (Cardinals digest) but uses the official MLB
silhouette logo + MLB brand palette and lists the date / game count instead
of a single-game score. Embedded as the first inline image in the post so
Blot's {{#thumbnail.large}} resolves to it for iMessage / social link
previews.

Layout (1200x630, MLB navy bg, red 8px bottom rule):
    +-----------------------------------------------+
    |                                               |
    |   [MLB LOGO]   MLB DAILY ROUNDUP  ──────      |  ← red underline
    |    ~440 wide                                  |
    |                MAY 10, 2026                   |  ← big white date
    |                                               |
    |                [15 GAMES]                     |  ← red chip
    |                                               |
    +-----------------------------------------------+   ← MLB-red rule
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = ROOT / "assets" / "Major_League_Baseball_logo.png"
FONT_PATH = ROOT / "assets" / "fonts" / "RobotoSlab.ttf"

WIDTH = 1200
HEIGHT = 630

# Official MLB brand palette (from brandcolorcode.com/mlb-major-league-baseball)
MLB_NAVY = (4, 30, 66)      # #041E42
MLB_RED = (191, 13, 62)     # #BF0D3E
WHITE = (255, 255, 255)

# Roboto Slab variable font weight axis values
WGHT_REGULAR = 400
WGHT_BOLD = 700


def _font(size: int, weight: int = WGHT_BOLD) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_PATH), size=size)
    try:
        f.set_variation_by_axes([weight])
    except (AttributeError, OSError):
        pass
    return f


def _fit_font(text: str, max_width: int, weight: int, max_size: int, min_size: int = 60) -> ImageFont.FreeTypeFont:
    """Return the largest font size whose rendered text width is ≤ max_width."""
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, weight)
        bbox = font.getbbox(text)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
    return _font(min_size, weight)


def _draw_letterspaced(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    spacing: int = 0,
) -> int:
    """Draw text with extra inter-character spacing; returns total rendered width."""
    x, y = xy
    start_x = x
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        bbox = font.getbbox(ch)
        x += (bbox[2] - bbox[0]) + spacing
    return x - start_x - spacing


def _resized_logo(target_width: int) -> Image.Image:
    """Load the MLB logo and upscale to target_width, preserving aspect."""
    logo = Image.open(LOGO_PATH).convert("RGBA")
    w, h = logo.size
    target_height = int(round(target_width * h / w))
    return logo.resize((target_width, target_height), Image.LANCZOS)


def generate_mlb_og_banner(
    game_date: date,
    n_games: int,
    out_path: Path,
) -> Path:
    """Render a 1200x630 OG banner for an MLB Daily Roundup post."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), MLB_NAVY)
    draw = ImageDraw.Draw(canvas)

    # Bottom red rule (matches the Cardinals banner red-rule pattern)
    draw.rectangle((0, HEIGHT - 8, WIDTH, HEIGHT), fill=MLB_RED)

    # MLB silhouette logo on the left, vertically centered
    LOGO_WIDTH = 440
    logo = _resized_logo(LOGO_WIDTH)
    logo_x = 70
    logo_y = (HEIGHT - logo.height) // 2 - 6
    canvas.paste(logo, (logo_x, logo_y), logo)

    # Right column anchor (after logo + breathing room)
    RIGHT_X = 560

    # Wordmark "MLB DAILY ROUNDUP" — white, letter-spaced, red underline
    wm_font = _font(42, WGHT_BOLD)
    wm_y = 130
    wm_width = _draw_letterspaced(
        draw, "MLB DAILY ROUNDUP", (RIGHT_X, wm_y), wm_font, WHITE, spacing=3
    )
    underline_y = wm_y + 60
    draw.rectangle(
        (RIGHT_X, underline_y, RIGHT_X + wm_width, underline_y + 4),
        fill=MLB_RED,
    )

    # Big date line, white. Auto-fit so long dates ("SEPTEMBER 30, 2026") still
    # fit — min_size kept low so the longest month name still shrinks in bounds.
    date_text = game_date.strftime("%B %-d, %Y").upper()
    date_max_width = WIDTH - RIGHT_X - 40
    date_font = _fit_font(date_text, date_max_width, WGHT_BOLD, max_size=96, min_size=52)
    draw.text((RIGHT_X, 240), date_text, font=date_font, fill=WHITE)

    # Game count chip — red bg, white text
    chip_text = "OFF DAY" if n_games == 0 else f"{n_games} GAMES"
    chip_font = _font(36, WGHT_BOLD)
    chip_padding_x, chip_padding_y = 18, 10
    chip_bbox = chip_font.getbbox(chip_text)
    chip_w = (chip_bbox[2] - chip_bbox[0]) + 2 * chip_padding_x
    chip_h = (chip_bbox[3] - chip_bbox[1]) + 2 * chip_padding_y
    chip_y = 410
    draw.rectangle(
        (RIGHT_X, chip_y, RIGHT_X + chip_w, chip_y + chip_h),
        fill=MLB_RED,
    )
    draw.text(
        (RIGHT_X + chip_padding_x, chip_y + chip_padding_y - chip_bbox[1]),
        chip_text,
        font=chip_font,
        fill=WHITE,
    )

    # Subtitle: weekday name in white
    sub_font = _font(34, WGHT_REGULAR)
    weekday = game_date.strftime("%A").upper()
    draw.text((RIGHT_X, 510), weekday, font=sub_font, fill=WHITE)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG", optimize=True)
    return out_path
