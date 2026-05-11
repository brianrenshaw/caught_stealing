"""Open Graph banner generator for Cardinals daily Blot posts.

Generates a 1200x630 PNG branded with the historical 1971-97 St. Louis
Cardinals logo plus game data (score, opponent, date, W/L). Embedded as
the first inline image in the post so Blot's {{#thumbnail.large}} resolves
to it for iMessage / social link previews.

Layout (1200x630, navy bg, red 8px bottom rule):
    +-----------------------------------------------+
    |                                               |
    |   [LOGO 380x380]   CARDINALS DAILY  ─────     |  ← yellow wordmark + underline
    |     centered                                  |
    |     vertically    STL 2 — SD 3                |  ← big white score
    |                                               |
    |                   [LOSS]                      |  ← red/yellow result chip
    |                                               |
    |                   @ Padres · May 10, 2026     |  ← yellow subtitle
    |                                               |
    +-----------------------------------------------+   ← cardinal-red rule
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = ROOT / "assets" / "StLCardinals7197.png"
FONT_PATH = ROOT / "assets" / "fonts" / "RobotoSlab.ttf"

WIDTH = 1200
HEIGHT = 630

NAVY = (12, 35, 64)
RED = (196, 30, 58)
YELLOW = (254, 219, 0)
WHITE = (255, 255, 255)

# Roboto Slab variable font wght axis
WGHT_REGULAR = 400
WGHT_BOLD = 700

# MLB team-name → short code for the score line ("Padres" → "SD").
TEAM_SHORT = {
    "Diamondbacks": "ARI", "Braves": "ATL", "Orioles": "BAL", "Red Sox": "BOS",
    "Cubs": "CHC", "White Sox": "CHW", "Reds": "CIN", "Guardians": "CLE",
    "Rockies": "COL", "Tigers": "DET", "Astros": "HOU", "Royals": "KC",
    "Angels": "LAA", "Dodgers": "LAD", "Marlins": "MIA", "Brewers": "MIL",
    "Twins": "MIN", "Mets": "NYM", "Yankees": "NYY", "Athletics": "OAK",
    "Phillies": "PHI", "Pirates": "PIT", "Padres": "SD", "Mariners": "SEA",
    "Giants": "SF", "Cardinals": "STL", "Rays": "TB", "Rangers": "TEX",
    "Blue Jays": "TOR", "Nationals": "WSH",
}


def _font(size: int, weight: int = WGHT_BOLD) -> ImageFont.FreeTypeFont:
    """Load the variable Roboto Slab font at a given weight axis value."""
    f = ImageFont.truetype(str(FONT_PATH), size=size)
    try:
        f.set_variation_by_axes([weight])
    except (AttributeError, OSError):
        pass
    return f


def _fit_font(text: str, max_width: int, weight: int, max_size: int, min_size: int = 60) -> ImageFont.FreeTypeFont:
    """Return the largest font size whose rendered text width is ≤ max_width.
    Steps down by 2pt from max_size to min_size; falls back to min_size."""
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, weight)
        bbox = font.getbbox(text)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
    return _font(min_size, weight)


def _logo_circle(target: int) -> Image.Image:
    """Open the historical logo and clip it to a circle so the white bounding
    box doesn't show on the navy banner. Returns RGBA at target x target."""
    logo = Image.open(LOGO_PATH).convert("RGBA")
    w, h = logo.size
    mask = Image.new("L", (w, h), 0)
    # Source is 500x500 with ~5px white border around the red circle; use the
    # full extent so the red ring stays intact.
    ImageDraw.Draw(mask).ellipse((0, 0, w, h), fill=255)
    logo.putalpha(mask)
    return logo.resize((target, target), Image.LANCZOS)


def _team_short(full_name: str | None) -> str:
    if not full_name:
        return "OPP"
    last = full_name.split()[-1]
    return TEAM_SHORT.get(last) or TEAM_SHORT.get(full_name) or last[:3].upper()


def _draw_letterspaced(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    spacing: int = 0,
) -> int:
    """Draw text with extra inter-character spacing. Returns total width."""
    x, y = xy
    start_x = x
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        bbox = font.getbbox(ch)
        x += (bbox[2] - bbox[0]) + spacing
    return x - start_x - spacing


def _score_parts(postgame: dict) -> tuple[str, int, str, int, str, str]:
    """Extract (connector, stl_runs, opp_short, opp_runs, opp_pretty, result)
    from the postgame dict."""
    ls = postgame.get("line_score") or {}
    totals = ls.get("totals") or {}
    stl_home = bool(postgame.get("stl_is_home"))

    if stl_home:
        stl_r = ((totals.get("home") or {}).get("R")) or 0
        opp_r = ((totals.get("away") or {}).get("R")) or 0
        opp_full = postgame.get("away_team") or "Opponent"
        connector = "vs"
    else:
        stl_r = ((totals.get("away") or {}).get("R")) or 0
        opp_r = ((totals.get("home") or {}).get("R")) or 0
        opp_full = postgame.get("home_team") or "Opponent"
        connector = "@"

    opp_short = _team_short(opp_full)
    opp_pretty = opp_full.split()[-1] if opp_full else "Opponent"

    if stl_r > opp_r:
        result = "WIN"
    elif stl_r < opp_r:
        result = "LOSS"
    else:
        result = "TIE"

    return connector, int(stl_r), opp_short, int(opp_r), opp_pretty, result


def generate_og_banner(
    postgame: dict | None,
    out_path: Path,
    game_date: date,
) -> Path:
    """Render a 1200x630 OG banner for the post. Falls back to an "off day"
    banner when postgame is None. Writes PNG to out_path and returns it."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(canvas)

    # Bottom Cardinal-red rule
    draw.rectangle((0, HEIGHT - 8, WIDTH, HEIGHT), fill=RED)

    # Historical logo, vertically centered on the left.
    LOGO_SIZE = 420
    logo = _logo_circle(LOGO_SIZE)
    logo_x = 55
    logo_y = (HEIGHT - LOGO_SIZE) // 2 - 8
    canvas.paste(logo, (logo_x, logo_y), logo)

    # Right column anchor (logo ends near x=475 with padding)
    RIGHT_X = 540

    # Wordmark "CARDINALS DAILY" — yellow, letter-spaced
    wm_font = _font(44, WGHT_BOLD)
    wm_y = 115
    wm_width = _draw_letterspaced(
        draw, "CARDINALS DAILY", (RIGHT_X, wm_y), wm_font, YELLOW, spacing=4
    )
    # Yellow underline beneath the wordmark
    underline_y = wm_y + 62
    draw.rectangle(
        (RIGHT_X, underline_y, RIGHT_X + wm_width, underline_y + 4),
        fill=YELLOW,
    )

    if postgame:
        connector, stl_r, opp_short, opp_r, opp_pretty, result = _score_parts(postgame)

        # Big score line, white. Auto-fit so double-digit runs ("STL 12 — SD 11")
        # don't overflow the canvas.
        score_text = f"STL {stl_r} — {opp_short} {opp_r}"
        score_max_width = WIDTH - RIGHT_X - 40
        score_font = _fit_font(score_text, score_max_width, WGHT_BOLD, max_size=120, min_size=70)
        score_y = 230
        draw.text((RIGHT_X, score_y), score_text, font=score_font, fill=WHITE)

        # Result chip — red bg for LOSS, yellow for WIN, white for TIE.
        # Text colour picks the contrast partner (navy on yellow/white, white on red).
        chip_font = _font(36, WGHT_BOLD)
        chip_styles = {
            "WIN": (YELLOW, NAVY),
            "LOSS": (RED, WHITE),
            "TIE": (WHITE, NAVY),
        }
        chip_fill, chip_text_fill = chip_styles[result]
        chip_y = 405
        chip_padding_x, chip_padding_y = 18, 10
        chip_bbox = chip_font.getbbox(result)
        chip_w = (chip_bbox[2] - chip_bbox[0]) + 2 * chip_padding_x
        chip_h = (chip_bbox[3] - chip_bbox[1]) + 2 * chip_padding_y
        draw.rectangle(
            (RIGHT_X, chip_y, RIGHT_X + chip_w, chip_y + chip_h),
            fill=chip_fill,
        )
        draw.text(
            (RIGHT_X + chip_padding_x, chip_y + chip_padding_y - chip_bbox[1]),
            result,
            font=chip_font,
            fill=chip_text_fill,
        )

        # Subtitle: "@ Padres · May 10, 2026"
        sub_font = _font(34, WGHT_REGULAR)
        date_str = game_date.strftime("%B %-d, %Y")
        subtitle = f"{connector} {opp_pretty}  ·  {date_str}"
        draw.text((RIGHT_X, 510), subtitle, font=sub_font, fill=YELLOW)
    else:
        # Off-day banner
        off_font = _font(96, WGHT_BOLD)
        draw.text((RIGHT_X, 260), "OFF DAY", font=off_font, fill=WHITE)
        sub_font = _font(34, WGHT_REGULAR)
        date_long = game_date.strftime("%A, %B %-d, %Y")
        draw.text((RIGHT_X, 410), date_long, font=sub_font, fill=YELLOW)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG", optimize=True)
    return out_path
