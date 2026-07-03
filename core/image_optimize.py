"""Image optimization for the gallery publish pipeline (BOT-03).

Pure, dependency-light helper: given the raw bytes of a staff attachment, produce a
web-ready WebP plus its post-resize dimensions — the exact ``width``/``height`` the
website's ``gallery.json`` contract expects (Phase 4 D-04).

Design notes:
  * Downscale-only to a 1920px long edge, aspect preserved — never upscales (D-12).
  * Always re-encodes to WebP (one consistent format, D-11).
  * EXIF/GPS metadata is dropped: ``ImageOps.exif_transpose`` bakes orientation into
    the pixels, then ``save(WEBP)`` is called with no ``exif=`` argument, so no metadata
    chunk is written (privacy default — GPS/camera data never reaches the public site).
  * Pillow's default ``MAX_IMAGE_PIXELS`` decompression-bomb guard is left in place.

This module imports only ``io`` and ``PIL`` — no ``discord`` and no ``config`` — so it
stays a pure, independently testable unit. The cog (05-03) is responsible for calling
it off the event loop (e.g. ``asyncio.to_thread``); no threading wrapper lives here.
"""

import io

from PIL import Image, ImageOps

# Long edge cap in pixels (D-12) and WebP encoder settings.
MAX_EDGE = 1920
WEBP_QUALITY = 82   # D-12: ~80-85 band; good size/quality for page load
WEBP_METHOD = 6     # 0=fast .. 6=best compression; publishing is a background task


def optimize_to_webp(raw: bytes) -> tuple[bytes, int, int]:
    """Convert raw image bytes to web-ready WebP.

    Args:
        raw: the original attachment bytes (PNG/JPEG/WebP).

    Returns:
        ``(webp_bytes, width, height)`` where ``width``/``height`` are the POST-resize
        pixel dimensions of the encoded WebP (what ``gallery.json`` stores).
    """
    with Image.open(io.BytesIO(raw)) as im:
        # Honour EXIF orientation by baking it into the pixels, then drop the metadata.
        im = ImageOps.exif_transpose(im)

        # WebP encodes RGB/RGBA; normalize palette/other modes first (Pitfall 3).
        if im.mode in ("P", "LA"):
            im = im.convert("RGBA")
        elif im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")  # CMYK, L, etc.

        # Downscale-only to the long-edge cap, preserving aspect ratio (D-12).
        im.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        width, height = im.size  # post-resize dims -> gallery.json width/height

        out = io.BytesIO()
        # No exif= argument => metadata (EXIF/GPS) is stripped on save.
        im.save(out, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
        return out.getvalue(), width, height
