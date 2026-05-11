"""Static Open Graph banner generator for the Lankford Legends homepage.

Produces a 1200x630 PNG used as the og:image when sharing
https://lankfordlegends.co on iMessage / social. Parent-brand artwork
for the two Blot-published reports (Cardinals daily digest + MLB daily
roundup), so this card pairs the historical Cardinals logo with the
MLB silhouette logo around a centered "LANKFORD LEGENDS" wordmark.

Layout (1200x630, Cardinals navy bg, red 8px bottom rule):
    +---------------------------------------------------+
    |  [STL LOGO]                       [MLB LOGO]      |
    |  240x240                          ~280 wide       |
    |                                                   |
    |              LANKFORD LEGENDS                     |  ← center wordmark
    |              ─────────────                        |  ← yellow underline
    |     Daily Cardinals + MLB Game Summaries & ...    |  ← tagline
    |                                                   |
    |  [AI-GENERATED]              lankfordlegends.co   |  ← badge + domain
    +---------------------------------------------------+  ← cardinal-red rule
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
STL_LOGO_PATH = ROOT / "assets" / "StLCardinals7197.png"
MLB_LOGO_PATH = ROOT / "assets" / "Major_League_Baseball_logo.png"
FONT_PATH = ROOT / "assets" / "fonts" / "RobotoSlab.ttf"

WIDTH = 1200
HEIGHT = 630

# Cardinals palette (matches og_banner.py)
NAVY = (12, 35, 64)        # #0C2340
RED = (196, 30, 58)        # #C41E3A
YELLOW = (254, 219, 0)     # #FEDB00
WHITE = (255, 255, 255)

# Roboto Slab variable font weight axis values
WGHT_REGULAR = 400
WGHT_BOLD = 700


def _font(size: int, weight: int = WGHT_BOLD) -> ImageFont.FreeTypeFont:
    """Load the variable Roboto Slab font at a given weight axis value."""
    f = ImageFont.truetype(str(FONT_PATH), size=size)
    try:
        f.set_variation_by_axes([weight])
    except (AttributeError, OSError):
        pass
    return f


def _fit_font(text: str, max_width: int, weight: int, max_size: int, min_size: int = 20) -> ImageFont.FreeTypeFont:
    """Return the largest font size whose rendered text width is ≤ max_width."""
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, weight)
        bbox = font.getbbox(text)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
    return _font(min_size, weight)


def _logo_circle(target: int) -> Image.Image:
    """Open the historical Cardinals logo and clip it to a circle so the
    white bounding box doesn't show on the navy banner. Returns RGBA."""
    logo = Image.open(STL_LOGO_PATH).convert("RGBA")
    w, h = logo.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, w, h), fill=255)
    logo.putalpha(mask)
    return logo.resize((target, target), Image.LANCZOS)


def _mlb_logo(target_width: int) -> Image.Image:
    """Load the MLB silhouette logo and resize to target_width, preserving aspect."""
    logo = Image.open(MLB_LOGO_PATH).convert("RGBA")
    w, h = logo.size
    target_height = int(round(target_width * h / w))
    return logo.resize((target_width, target_height), Image.LANCZOS)


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


def _letterspaced_width(text: str, font: ImageFont.FreeTypeFont, spacing: int = 0) -> int:
    """Measure rendered width of letterspaced text without drawing."""
    total = 0
    for ch in text:
        bbox = font.getbbox(ch)
        total += (bbox[2] - bbox[0]) + spacing
    return total - spacing if text else 0


def generate_site_card(out_path: Path) -> Path:
    """Render the static 1200x630 Lankford Legends homepage OG banner.

    Always emits the same image; no parameters other than out_path.
    """
    canvas = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(canvas)

    # Bottom Cardinal-red rule
    draw.rectangle((0, HEIGHT - 8, WIDTH, HEIGHT), fill=RED)

    # Top-left: Cardinals historical logo, circle-masked, 240x240 at (60, 80)
    stl_size = 240
    stl = _logo_circle(stl_size)
    canvas.paste(stl, (60, 80), stl)

    # Top-right: MLB silhouette, 280 wide, top-aligned with Cardinals logo
    mlb_width = 280
    mlb = _mlb_logo(mlb_width)
    # Right edge near x=1140 → left x = 1140 - mlb_width = 860
    mlb_x = 1140 - mlb_width
    # Vertically center MLB logo within Cardinals logo's vertical extent
    mlb_y = 80 + (stl_size - mlb.height) // 2
    canvas.paste(mlb, (mlb_x, mlb_y), mlb)

    # Center wordmark "LANKFORD LEGENDS" — Roboto Slab Bold ~64pt, white,
    # 3px letter-spacing, baseline ≈ y=380
    wordmark_text = "LANKFORD LEGENDS"
    wm_spacing = 3
    wm_font = _font(64, WGHT_BOLD)
    wm_width = _letterspaced_width(wordmark_text, wm_font, spacing=wm_spacing)
    wm_bbox = wm_font.getbbox(wordmark_text)
    wm_height = wm_bbox[3] - wm_bbox[1]
    wm_x = (WIDTH - wm_width) // 2
    # "baseline around y=380" → top of glyphs ≈ 380 - wm_height
    wm_y = 380 - wm_height
    _draw_letterspaced(draw, wordmark_text, (wm_x, wm_y), wm_font, WHITE, spacing=wm_spacing)

    # Yellow underline: 3px tall, 480px wide, centered. Gap calculation uses
    # font ascent/descent metrics so the bar sits cleanly below the glyphs
    # regardless of variable-font weight quirks in bbox reporting.
    underline_width = 480
    underline_height = 3
    ascent, descent = wm_font.getmetrics()
    underline_y = wm_y + ascent + descent + 10
    underline_x = (WIDTH - underline_width) // 2
    draw.rectangle(
        (underline_x, underline_y, underline_x + underline_width, underline_y + underline_height),
        fill=YELLOW,
    )

    # Tagline: Roboto Slab Regular ~28pt, white, centered, 28px gap below underline.
    # "AI-Generated" is baked into the tagline (no separate yellow pill).
    tagline_text = "AI-Generated Daily Cardinals + MLB Game Summaries"
    tagline_max_width = WIDTH - 120  # 60px side padding each side
    tagline_font = _fit_font(tagline_text, tagline_max_width, WGHT_REGULAR, max_size=28, min_size=18)
    tagline_bbox = tagline_font.getbbox(tagline_text)
    tagline_width = tagline_bbox[2] - tagline_bbox[0]
    tagline_x = (WIDTH - tagline_width) // 2
    tagline_y = underline_y + underline_height + 28
    draw.text((tagline_x, tagline_y), tagline_text, font=tagline_font, fill=WHITE)

    # Domain stamp (bottom-center): Roboto Slab Regular ~24pt, white,
    # centered with 60px from the red rule.
    domain_text = "lankfordlegends.co"
    domain_font = _font(24, WGHT_REGULAR)
    domain_bbox = domain_font.getbbox(domain_text)
    domain_w = domain_bbox[2] - domain_bbox[0]
    domain_x = (WIDTH - domain_w) // 2
    domain_y = HEIGHT - 8 - 56  # 56px above the red rule
    draw.text((domain_x, domain_y), domain_text, font=domain_font, fill=WHITE)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG", optimize=True)
    return out_path
