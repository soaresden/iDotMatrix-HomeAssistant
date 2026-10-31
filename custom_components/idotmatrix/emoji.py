"""Emoji in text drawn on the display (🤣, 🏠...), as small pixel images.

The pixel fonts only hold letters and figures. An emoji typed in a text
(a message, the name of a weather place) is drawn from Twemoji's picture of
it (CC-BY 4.0, https://github.com/jdecked/twemoji), scaled to the height of
the text. Pictures are fetched once from the jsDelivr CDN, then kept in
memory and in a folder when one is given; without network an emoji is left
out. Called from render code that already runs off the event loop.
"""
from __future__ import annotations

import io
import logging
import os
import urllib.request

from PIL import Image, ImageEnhance

_LOGGER = logging.getLogger(__name__)

TWEMOJI_URL = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@v15.1.0/assets/72x72/{}.png"
ZWJ, VS16, KEYCAP = "‍", "️", "⃣"
# Where fetched pictures are kept between runs (set by the integration and the apps).
cache_dir: str | None = None
_pictures: dict[str, Image.Image | None] = {}


def is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF
            or 0x2190 <= cp <= 0x21FF or 0x2300 <= cp <= 0x23FF or 0x1F1E6 <= cp <= 0x1F1FF
            or cp in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299))


def _joins(ch: str) -> bool:
    """Marks that belong to the emoji before them: variation, skin tone, keycap, tags."""
    cp = ord(ch)
    return ch in (VS16, KEYCAP) or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F


def split(text: str) -> list[tuple[str, bool]]:
    """``text`` as runs of plain text and single emoji: [(piece, is_emoji)]."""
    parts: list[tuple[str, bool]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if is_emoji(ch):
            j = i + 1
            # A flag is two regional indicators; ZWJ sequences join several emoji.
            if 0x1F1E6 <= ord(ch) <= 0x1F1FF and j < len(text) and 0x1F1E6 <= ord(text[j]) <= 0x1F1FF:
                j += 1
            while j < len(text):
                if _joins(text[j]):
                    j += 1
                elif text[j] == ZWJ and j + 1 < len(text):
                    j += 2
                else:
                    break
            parts.append((text[i:j], True))
            i = j
        elif ch in (VS16, ZWJ):
            i += 1
        else:
            j = i
            while j < len(text) and not is_emoji(text[j]) and text[j] not in (VS16, ZWJ):
                j += 1
            if parts and not parts[-1][1]:
                parts[-1] = (parts[-1][0] + text[i:j], False)
            else:
                parts.append((text[i:j], False))
            i = j
    return parts


def has_emoji(text: str | None) -> bool:
    return bool(text) and any(is_emoji(ch) for ch in text)


def _names(emoji: str) -> list[str]:
    """Twemoji's file names for it: without the variation selector first, as Twemoji mostly names them."""
    full = "-".join(f"{ord(c):x}" for c in emoji)
    bare = "-".join(f"{ord(c):x}" for c in emoji if c != VS16)
    return list(dict.fromkeys([bare, full]))


def _fetch(emoji: str) -> Image.Image | None:
    for name in _names(emoji):
        path = os.path.join(cache_dir, f"{name}.png") if cache_dir else None
        try:
            if path and os.path.isfile(path):
                with open(path, "rb") as handle:
                    data = handle.read()
            else:
                request = urllib.request.Request(TWEMOJI_URL.format(name), headers={"User-Agent": "iDotMatrix"})
                with urllib.request.urlopen(request, timeout=8) as response:
                    data = response.read()
                if path:
                    os.makedirs(cache_dir, exist_ok=True)
                    with open(path, "wb") as handle:
                        handle.write(data)
            with Image.open(io.BytesIO(data)) as image:
                return image.convert("RGBA")
        except OSError as err:  # not found under that name, no network...
            _LOGGER.debug("Emoji %s (%s): %s", emoji, name, err)
    return None


def picture(emoji: str, size: int) -> Image.Image | None:
    """The emoji as a ``size``×``size`` RGBA image, fully opaque or fully clear pixels (LEDs)."""
    if emoji not in _pictures:
        _pictures[emoji] = _fetch(emoji)
    source = _pictures[emoji]
    if source is None:
        return None
    small = source.resize((size, size), Image.Resampling.BOX)
    # Small pictures look washed out on LEDs: a little more colour.
    rgb = ImageEnhance.Color(small.convert("RGB")).enhance(1.4)
    alpha = small.getchannel("A").point(lambda a: 255 if a >= 110 else 0)
    rgb.putalpha(alpha)
    return rgb


def paste(img: Image.Image, x: int, y: int, emoji: str, size: int) -> int:
    """Draw the emoji with its top-left at (x, y); returns its width (0 when it could not be had)."""
    pic = picture(emoji, size)
    if pic is None:
        return 0
    img.paste(pic.convert("RGB"), (x, y), pic.getchannel("A"))
    return size
