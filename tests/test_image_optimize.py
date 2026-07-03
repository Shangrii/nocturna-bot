"""Behaviour tests for the gallery image-optimization pipeline (BOT-03).

Every source image is generated in-memory with Pillow — no fixture files on disk.
Covers the D-11/D-12 contract:
  * every published image becomes web-ready WebP (D-11)
  * long edge is capped at 1920px, downscale-only, aspect preserved (D-12)
  * post-resize dimensions are returned (the gallery.json width/height, Phase 4 D-04)
  * EXIF/GPS metadata is stripped from the published file (privacy default)
  * palette/transparency images are handled without raising (Pitfall 3)
"""

import io

import pytest
from PIL import Image, ImageOps

from core.image_optimize import optimize_to_webp


# ── helpers: build source images in-memory ───────────────────────────────────────
def _png_bytes(width: int, height: int, color=(200, 50, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(width: int, height: int, color=(30, 40, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG")
    return buf.getvalue()


def _jpeg_with_exif(width: int, height: int) -> bytes:
    """A JPEG carrying orientation + camera + GPS EXIF tags."""
    im = Image.new("RGB", (width, height), (120, 30, 44))
    exif = Image.Exif()
    exif[0x010F] = "NocturnaCam"          # Make
    exif[0x0110] = "AvatarShooter"        # Model
    exif[0x0112] = 6                      # Orientation (rotate 90 CW)
    exif[0x9003] = "2026:07:03 12:00:00"  # DateTimeOriginal
    exif[0x8825] = {1: "N", 3: "W", 5: 0}  # GPS IFD: lat/long/altitude refs
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _palette_png_with_transparency(width: int, height: int) -> bytes:
    """A P-mode (palette) PNG with a transparent index — the Pitfall-3 case."""
    im = Image.new("P", (width, height))
    im.putpalette([i % 256 for i in range(768)])
    im.info["transparency"] = 0
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _decode(webp_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(webp_bytes))


# ── behaviour ─────────────────────────────────────────────────────────────────────
def test_large_image_downscales_to_1920_long_edge_preserving_aspect():
    """3000x2000 → long edge 1920, short edge 1280 (downscale + aspect preserved)."""
    webp, width, height = optimize_to_webp(_png_bytes(3000, 2000))

    # returned dims are the post-resize dims the gallery.json contract needs
    assert (width, height) == (1920, 1280)
    # and they match the actually-encoded pixels
    decoded = _decode(webp)
    assert decoded.size == (1920, 1280)
    assert max(decoded.size) == 1920
    assert min(decoded.size) == 1280


def test_small_image_is_never_upscaled():
    """800x600 stays 800x600 — thumbnail is downscale-only."""
    webp, width, height = optimize_to_webp(_jpeg_bytes(800, 600))

    assert (width, height) == (800, 600)
    assert _decode(webp).size == (800, 600)


def test_output_is_webp():
    """Returned bytes decode as a Pillow image whose format is WEBP (D-11)."""
    webp, _, _ = optimize_to_webp(_png_bytes(1000, 1000))

    assert _decode(webp).format == "WEBP"


def test_exif_and_gps_metadata_are_stripped():
    """Even when the source carries EXIF orientation/GPS, the WebP has none."""
    src = _jpeg_with_exif(1600, 1200)

    # sanity: the source really does carry EXIF (so the test proves stripping)
    assert len(Image.open(io.BytesIO(src)).getexif()) > 0

    webp, _, _ = optimize_to_webp(src)
    decoded = _decode(webp)

    assert decoded.format == "WEBP"
    assert len(decoded.getexif()) == 0
    assert "exif" not in decoded.info


def test_palette_png_with_transparency_optimizes_without_raising():
    """A P-mode PNG with transparency must be mode-converted before WEBP save."""
    webp, width, height = optimize_to_webp(_palette_png_with_transparency(1000, 700))

    decoded = _decode(webp)
    assert decoded.format == "WEBP"
    assert (width, height) == (1000, 700)
