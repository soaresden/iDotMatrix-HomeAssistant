"""Render what was sent to the display as an LED-panel style preview.

The device cannot be read back, so the preview is built from the content
the integration uploads: each pixel becomes a round LED on a dark board,
unlit pixels stay faintly visible like on the real panel, and animations
keep their timing. The result is upscaled with hard edges so browsers do
not blur a 64x64 image when showing it in the device page.
"""
from __future__ import annotations

import io
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageSequence

# Output width in pixels, whatever the screen resolution.
PREVIEW_SIZE = 384
# Colour of an unlit LED; pixels dimmer than it on every channel show it.
UNLIT = (28, 28, 28)
_DEFAULT_FRAME_MS = 100


def color_preview(color: tuple[int, int, int], size: int) -> bytes:
    """Preview of a solid fullscreen colour."""
    return render_led_preview(_png(Image.new("RGB", (size, size), tuple(color))))


def image_preview(image: Image.Image) -> bytes:
    """Preview of a still frame rendered by the integration."""
    return render_led_preview(_png(image.convert("RGB")))


def file_preview(path: str) -> bytes:
    """Preview of a GIF/PNG file sent as-is."""
    with open(path, "rb") as handle:
        return render_led_preview(handle.read())


def render_led_preview(content: bytes, size: int = PREVIEW_SIZE) -> bytes:
    """Turn PNG/GIF bytes sent to the display into an animated LED preview GIF."""
    with Image.open(io.BytesIO(content)) as source:
        width, height = source.size
        scale = max(1, size // max(width, height))
        dots = _dot_mask(width, height, scale)
        board = Image.new("RGB", dots.size, (0, 0, 0))
        unlit = Image.new("RGB", (width, height), UNLIT)
        frames, durations = [], []
        for frame in ImageSequence.Iterator(source):
            rgb = frame.convert("RGB")
            r, g, b = rgb.split()
            dark = ImageChops.lighter(ImageChops.lighter(r, g), b).point(
                lambda v: 255 if v < max(UNLIT) else 0
            )
            rgb.paste(unlit, mask=dark)
            big = rgb.resize(dots.size, Image.Resampling.NEAREST)
            frames.append(Image.composite(big, board, dots))
            ms = int(frame.info.get("duration") or source.info.get("duration") or 0)
            durations.append(ms if ms > 0 else _DEFAULT_FRAME_MS)

    out = io.BytesIO()
    if len(frames) == 1:
        frames[0].save(out, format="GIF")
    else:
        frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:],
                       duration=durations, loop=0, disposal=1)
    return out.getvalue()


@lru_cache(maxsize=4)
def _dot_mask(width: int, height: int, scale: int) -> Image.Image:
    """Binary mask with one round LED per source pixel."""
    cell = Image.new("L", (scale, scale), 0)
    gap = max(1, scale // 6) if scale >= 4 else 0
    ImageDraw.Draw(cell).ellipse((gap, gap, scale - 1 - gap, scale - 1 - gap), fill=255)
    mask = Image.new("L", (width * scale, height * scale), 0)
    for y in range(height):
        for x in range(width):
            mask.paste(cell, (x * scale, y * scale))
    return mask


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
