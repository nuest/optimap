# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Open Graph preview image generator for work landing pages — issue #22.

Renders a 1200×630 PNG showing the work's spatial extent on an OSM basemap,
with a small "OPTIMAP" wordmark in the bottom-right. Files are cached on
disk under ``CACHE_DIR / 'work_previews' / <id>.png`` and regenerated lazily
on the first request after the work changes (see signal handler in
``works/signals.py``).
"""

from __future__ import annotations

import io
import json
import logging
import tempfile
from pathlib import Path

from datetime import datetime, timezone

import cairosvg
from PIL import Image, ImageDraw, ImageFont
from staticmap import StaticMap, Polygon, Line, CircleMarker
from staticmap.staticmap import _lon_to_x, _lat_to_y

logger = logging.getLogger(__name__)

PREVIEW_WIDTH = 1200
PREVIEW_HEIGHT = 630
TILE_URL = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "OPTIMAP-preview/1.0 (+https://optimap.science)"

# OPTIMAP brand colours — see works/static/css/main.css. The navbar uses
# #158F9B (teal) and the alerts use rgba(21, 143, 155, 0.2) for the
# transparent variant. We use the same teal for the geometry: thick opaque
# outline + translucent fill so the basemap shows through.
BRAND_TEAL = "#158F9B"
EXTENT_FILL = (21, 143, 155, 102)  # 0.4 alpha — slightly stronger than the
                                   # CSS 0.2 because the OSM background is
                                   # busy and faint colours wash out.
EXTENT_OUTLINE = BRAND_TEAL
EXTENT_OUTLINE_WIDTH = 6  # px — "thick outline" per the request

LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "optimap_logo.svg"
LOGO_TARGET_HEIGHT = 60  # px on the 1200×630 canvas
LOGO_MARGIN = 18         # px from the bottom-right corner
LOGO_URL_TEXT = "optimap.science"
TIMESTAMP_FONT_SIZE = 11  # px — "very small font" per the request


def preview_cache_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "optimap_cache" / "work_previews"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_path_for(work) -> Path:
    return preview_cache_dir() / f"{work.id}.png"


def invalidate_preview(work) -> None:
    """Remove the cached preview for ``work`` if it exists. Called from the
    Work post_save signal so subsequent requests regenerate."""
    p = cache_path_for(work)
    try:
        p.unlink(missing_ok=True)
    except OSError as err:  # pragma: no cover — disk-level failure
        logger.warning("could not unlink cached preview %s: %s", p, err)


def render_work_preview(work) -> bytes:
    """Render and return PNG bytes for ``work`` (no I/O — caller writes to
    disk). Raises ``ValueError`` if the work has no usable geometry."""
    if not work.geometry or work.geometry.empty:
        raise ValueError("work has no geometry — preview cannot be generated")

    smap = StaticMap(
        PREVIEW_WIDTH,
        PREVIEW_HEIGHT,
        url_template=TILE_URL,
        headers={"User-Agent": USER_AGENT},
        padding_x=40,
        padding_y=40,
    )
    geojson = json.loads(work.geometry.geojson)
    # Register the geometries with the staticmap as invisible polygons /
    # lines so the auto-zoom fits them, then draw them ourselves on top of
    # the rendered basemap so we control opacity and outline thickness.
    _register_extent_only(smap, geojson)

    image = smap.render(zoom=None)
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    _draw_geometry_on_image(smap, image, geojson)
    image = _add_logo(image)
    _add_generation_timestamp(image)

    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _register_extent_only(smap: StaticMap, geojson: dict) -> None:
    """Add geometries to the staticmap with no fill / no outline so the
    auto-zoom fits them in view but they don't render. We draw them with
    PIL afterwards (staticmap's polygon outline is 1px and lacks an alpha
    channel for the fill)."""
    gtype = geojson.get("type")
    if gtype == "GeometryCollection":
        for child in geojson.get("geometries", []):
            _register_extent_only(smap, child)
        return
    coords = geojson.get("coordinates")
    if coords is None:
        return
    if gtype in ("Point", "MultiPoint"):
        # Use a tiny invisible marker so determine_extent picks the points up.
        pts = [coords] if gtype == "Point" else coords
        for c in pts:
            smap.add_marker(CircleMarker((c[0], c[1]), "#00000000", 1))
    elif gtype == "LineString":
        smap.add_line(Line([(c[0], c[1]) for c in coords], "#00000000", 1))
    elif gtype == "MultiLineString":
        for line in coords:
            smap.add_line(Line([(c[0], c[1]) for c in line], "#00000000", 1))
    elif gtype == "Polygon":
        if coords:
            smap.add_polygon(Polygon([(c[0], c[1]) for c in coords[0]], None, None))
    elif gtype == "MultiPolygon":
        for poly in coords:
            if poly:
                smap.add_polygon(Polygon([(c[0], c[1]) for c in poly[0]], None, None))


def _project(smap: StaticMap, lon: float, lat: float) -> tuple[float, float]:
    """Project ``(lon, lat)`` to a pixel coordinate using staticmap's own
    projection state (set during ``render``)."""
    return (
        smap._x_to_px(_lon_to_x(lon, smap.zoom)),
        smap._y_to_px(_lat_to_y(lat, smap.zoom)),
    )


def _draw_geometry_on_image(smap: StaticMap, image: Image.Image, geojson: dict) -> None:
    """Draw geometries on the rendered basemap with translucent fill + thick
    teal outline. Drawn on a separate RGBA overlay so the alpha-composite
    cleanly stacks on the (opaque) basemap."""
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_geom(smap, draw, geojson)
    image.alpha_composite(overlay)


def _draw_geom(smap, draw, geom):
    gtype = geom.get("type")
    if gtype == "GeometryCollection":
        for child in geom.get("geometries", []):
            _draw_geom(smap, draw, child)
        return
    coords = geom.get("coordinates")
    if coords is None:
        return

    if gtype == "Point":
        x, y = _project(smap, coords[0], coords[1])
        _draw_point(draw, x, y)
    elif gtype == "MultiPoint":
        for c in coords:
            x, y = _project(smap, c[0], c[1])
            _draw_point(draw, x, y)
    elif gtype == "LineString":
        pts = [_project(smap, c[0], c[1]) for c in coords]
        draw.line(pts, fill=BRAND_TEAL, width=EXTENT_OUTLINE_WIDTH, joint="curve")
    elif gtype == "MultiLineString":
        for line in coords:
            pts = [_project(smap, c[0], c[1]) for c in line]
            draw.line(pts, fill=BRAND_TEAL, width=EXTENT_OUTLINE_WIDTH, joint="curve")
    elif gtype == "Polygon":
        if coords:
            _draw_ring(draw, [_project(smap, c[0], c[1]) for c in coords[0]])
    elif gtype == "MultiPolygon":
        for poly in coords:
            if poly:
                _draw_ring(draw, [_project(smap, c[0], c[1]) for c in poly[0]])


def _draw_point(draw, x, y):
    r = 11
    draw.ellipse((x - r, y - r, x + r, y + r),
                 fill=EXTENT_FILL, outline=BRAND_TEAL, width=EXTENT_OUTLINE_WIDTH // 2)


def _draw_ring(draw, pts):
    if len(pts) < 3:
        return
    # Translucent fill.
    draw.polygon(pts, fill=EXTENT_FILL)
    # Thick opaque outline (Pillow's polygon outline is 1px and not anti-aliased).
    closed = list(pts) + [pts[0]]
    draw.line(closed, fill=BRAND_TEAL, width=EXTENT_OUTLINE_WIDTH, joint="curve")


def _add_logo(image: Image.Image) -> Image.Image:
    """Composite the OPTIMAP SVG logo + ``optimap.science`` URL onto the
    bottom-right corner, on a small translucent white pill so it stays
    legible over busy basemap tiles. Falls back to skipping the overlay
    entirely if SVG rendering or font loading fails."""
    logo_img = _load_logo_png()
    if logo_img is None:
        return image
    url_font = _load_font(13, bold=False)
    margin = LOGO_MARGIN
    pad_x, pad_y = 14, 8
    gap = 4   # space between logo and URL text

    # Measure URL text against the loaded font.
    tmp_draw = ImageDraw.Draw(image)
    url_w, url_h = _text_size(tmp_draw, LOGO_URL_TEXT, url_font)

    content_w = max(logo_img.width, url_w)
    content_h = logo_img.height + gap + url_h
    pill_w = content_w + pad_x * 2
    pill_h = content_h + pad_y * 2
    pill_xy = (image.width - pill_w - margin, image.height - pill_h - margin)

    pill = Image.new("RGBA", (pill_w, pill_h), (255, 255, 255, 0))
    pill_draw = ImageDraw.Draw(pill)
    pill_draw.rounded_rectangle((0, 0, pill_w - 1, pill_h - 1),
                                radius=10, fill=(255, 255, 255, 230))
    # Centre the logo + URL horizontally inside the pill.
    logo_x = pad_x + (content_w - logo_img.width) // 2
    url_x = pad_x + (content_w - url_w) // 2
    pill_draw.text(
        (url_x, pad_y + logo_img.height + gap),
        LOGO_URL_TEXT,
        font=url_font,
        fill=BRAND_TEAL,
    )
    image.alpha_composite(pill, dest=pill_xy)
    image.alpha_composite(logo_img, dest=(pill_xy[0] + logo_x, pill_xy[1] + pad_y))
    return image


def _add_generation_timestamp(image: Image.Image) -> None:
    """Stamp a tiny UTC generation timestamp in the bottom-left so a viewer
    can tell how stale a preview image is. Drawn directly on the basemap
    with a faint white shadow for contrast against any tile colour."""
    font = _load_font(TIMESTAMP_FONT_SIZE, bold=False)
    label = f"generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    draw = ImageDraw.Draw(image, "RGBA")
    margin = 8
    tw, th = _text_size(draw, label, font)
    x = margin
    y = image.height - th - margin
    # Faint white halo for legibility on dark tiles.
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        draw.text((x + dx, y + dy), label, font=font, fill=(255, 255, 255, 200))
    draw.text((x, y), label, font=font, fill=(40, 40, 40, 220))


def _load_font(size: int, bold: bool):
    """Load a TrueType font at the given size, falling back through a small
    list of common installed fonts and finally PIL's default bitmap font."""
    candidates = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size=size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _text_size(draw, text, font):
    """Pillow ≥9 uses ``textbbox``; older versions use ``textsize``."""
    if hasattr(draw, "textbbox"):
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t
    return draw.textsize(text, font=font)  # pragma: no cover — pre-9 Pillow


def _load_logo_png() -> Image.Image | None:
    """Render the SVG logo at ``LOGO_TARGET_HEIGHT`` px tall and return a
    Pillow image. Returns ``None`` on failure so the caller can degrade
    gracefully."""
    try:
        png_bytes = cairosvg.svg2png(
            url=str(LOGO_PATH),
            output_height=LOGO_TARGET_HEIGHT,
        )
    except Exception as err:
        logger.warning("OPTIMAP SVG logo render failed (%s) — preview "
                       "skipping logo overlay", err)
        return None
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


