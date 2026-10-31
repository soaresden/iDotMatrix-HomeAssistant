"""Pixel Studio log: what the Pi and the browsers did, with timings.

Kept so the user can copy it from the panel's 📜 tab and have it analysed:
every GIF encoded (sizes frame by frame), every transfer to a display (time
per packet, write mode), routine changes, re-encodings, and the integration's
warnings. The last entries survive Home Assistant restarts.
"""
from __future__ import annotations

import logging
import statistics
from functools import partial
import time
from collections import deque

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN

LOG_EVENT = f"{DOMAIN}_log"
MAX_ENTRIES = 3000
_STORE_KEY = f"{DOMAIN}_studio_log"


class Journal:
    """The last entries, newest last; each one is also fired as LOG_EVENT."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entries: deque[dict] = deque(maxlen=MAX_ENTRIES)
        self._store: Store[dict] = Store(hass, 1, _STORE_KEY)
        self._seq = 0
        self._handler: logging.Handler | None = None

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.entries.extend(data.get("entries", []))
        self._seq = max((entry.get("seq", 0) for entry in self.entries), default=0)

    @callback
    def add(self, kind: str, message: str, *, source: str = "pi", **data) -> dict:
        self._seq += 1
        entry = {"seq": self._seq, "t": round(time.time(), 3), "source": source, "kind": kind, "msg": message}
        if data:
            entry["data"] = data
        self.entries.append(entry)
        self.hass.bus.async_fire(LOG_EVENT, entry)
        self._store.async_delay_save(lambda: {"entries": list(self.entries)}, 15)
        return entry

    @callback
    def clear(self) -> None:
        self.entries.clear()
        self._store.async_delay_save(lambda: {"entries": []}, 1)

    def capture_warnings(self, logger_name: str) -> None:
        """Add the integration's warnings and errors to the log."""
        journal, loop = self, self.hass.loop

        class Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                # Never raise: this runs inside the code that logged, a
                # transfer for instance, which an error here would abort.
                try:
                    kind = "warning" if record.levelno < logging.ERROR else "error"
                    loop.call_soon_threadsafe(partial(journal.add, kind, record.getMessage(), logger=record.name))
                except Exception:  # noqa: BLE001
                    self.handleError(record)

        self._handler = Handler(logging.WARNING)
        logging.getLogger(logger_name).addHandler(self._handler)

    def release(self, logger_name: str) -> None:
        if self._handler is not None:
            logging.getLogger(logger_name).removeHandler(self._handler)
            self._handler = None


def gif_stats(data: bytes) -> dict:
    """How a GIF's bytes are spent, frame by frame, without decoding pixels.

    ``frames`` lists ``[bytes, box area in % of the screen, delay ms]`` per
    frame (the box is the part of the screen the frame redraws).
    """
    if len(data) < 13 or data[:3] != b"GIF":
        return {}
    width, height = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    packed = data[10]
    palette = 2 << (packed & 7) if packed & 0x80 else 0
    pos = 13 + palette * 3
    frames: list[list] = []
    delay = 0
    while pos < len(data):
        block = data[pos]
        if block == 0x3B:  # trailer
            break
        if block == 0x21:  # extension
            label = data[pos + 1]
            pos += 2
            if label == 0xF9 and pos + 4 < len(data):
                delay = int.from_bytes(data[pos + 2:pos + 4], "little") * 10
            while pos < len(data) and data[pos]:
                pos += data[pos] + 1
            pos += 1
        elif block == 0x2C:  # image
            w, h = int.from_bytes(data[pos + 5:pos + 7], "little"), int.from_bytes(data[pos + 7:pos + 9], "little")
            start = pos
            local = data[pos + 9]
            pos += 10 + ((2 << (local & 7)) * 3 if local & 0x80 else 0) + 1  # descriptor, LCT, LZW code size
            while pos < len(data) and data[pos]:
                pos += data[pos] + 1
            pos += 1
            area = round(100 * w * h / max(1, width * height), 1)
            frames.append([pos - start, area, delay])
            delay = 0
        else:
            break
    if not frames:
        return {"width": width, "height": height, "palette": palette}
    deltas = frames[1:]
    return {
        "width": width, "height": height, "palette": palette,
        "header_bytes": 13 + palette * 3,
        "frames_count": len(frames),
        "first_frame_bytes": frames[0][0],
        "delta_bytes_total": sum(f[0] for f in deltas),
        "delta_bytes_median": round(statistics.median(f[0] for f in deltas)) if deltas else 0,
        "delta_bytes_max": max((f[0] for f in deltas), default=0),
        "delta_area_median": statistics.median(f[1] for f in deltas) if deltas else 0,
        "full_screen_deltas": sum(1 for f in deltas if f[1] >= 99.9),
        "frames": frames,
    }
