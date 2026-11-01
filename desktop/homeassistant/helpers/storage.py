"""helpers.storage.Store for the desktop app: JSON files in the data folder's .storage,
in Home Assistant's own format (so a Studio state can move between the two)."""
from __future__ import annotations

import json
import logging
import os

_LOGGER = logging.getLogger(__name__)


class Store:
    def __init__(self, hass, version: int, key: str, **_options) -> None:
        self.hass = hass
        self.version = version
        self.key = key
        self.path = hass.config.path(".storage", key)
        self._pending = None  # data function of a delayed save
        self._handle = None
        hass.stores.append(self)

    async def async_load(self):
        def read():
            try:
                with open(self.path, encoding="utf-8") as handle:
                    return json.load(handle).get("data")
            except FileNotFoundError:
                return None
            except ValueError:
                # Cut short (the phone killed the app as it wrote): set aside, as Home Assistant does,
                # rather than keep the Studio from starting.
                os.replace(self.path, f"{self.path}.corrupt")
                _LOGGER.warning("%s unreadable, set aside as %s.corrupt", self.path, self.path)
                return None

        return await self.hass.async_add_executor_job(read)

    async def async_save(self, data) -> None:
        self._cancel()
        self._pending = None
        await self.hass.async_add_executor_job(self._write, data)

    def async_delay_save(self, data_func, delay: float = 0) -> None:
        self._pending = data_func
        self._cancel()
        self._handle = self.hass.loop.call_later(delay, lambda: self.hass.async_create_task(self.async_flush()))

    async def async_flush(self) -> None:
        """Write a delayed save now."""
        pending, self._pending = self._pending, None
        if pending is not None:
            await self.async_save(pending())

    def _cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def _write(self, data) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp = f"{self.path}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump({"version": self.version, "minor_version": 1, "key": self.key, "data": data}, handle)
            handle.flush()
            os.fsync(handle.fileno())  # on disk before it replaces the old file, even if the power goes
        os.replace(temp, self.path)
