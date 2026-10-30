"""The desktop app's coordinator.py: one display on the PC's own Bluetooth.

Loaded in place of the integration's coordinator (desktop/pixel_studio.py
puts this folder first in the package path). Pixel Studio (studio.py,
routines.py, schedule.py) only uses the members below; they follow the
integration's IDotMatrixCoordinator, without Home Assistant's config entries
and display modes (clock, weather...).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from types import SimpleNamespace

from bleak.exc import BleakError
from PIL import Image

from homeassistant.exceptions import HomeAssistantError

from .client.connectionManager import ConnectionManager, TransferRejectedError
from .client.modules.common import Common
from .client.modules.gif import Gif
from .weather import frames_to_gif

_LOGGER = logging.getLogger(__name__)

# As in the integration: a big GIF's first image goes ahead of it.
FIRST_FRAME_AHEAD_BYTES = 12 * 1024


def first_frame_still(path: str) -> str | None:
    """A one-image GIF of a big GIF's first frame, in a temp file (None for small GIFs)."""
    if os.path.getsize(path) <= FIRST_FRAME_AHEAD_BYTES:
        return None
    with Image.open(path) as image:
        frame = image.convert("RGB")
    fd, still = tempfile.mkstemp(suffix=".gif")
    with os.fdopen(fd, "wb") as handle:
        handle.write(frames_to_gif([frame], 1000, colors=256))
    return still


class IDotMatrixCoordinator:
    def __init__(self, hass, address: str, name: str, screen_size: int) -> None:
        self.hass = hass
        self.entry = SimpleNamespace(entry_id=address, title=name, data={"mac": address}, options={})
        self.conn = ConnectionManager.for_address(address)
        self.text_settings = {"screen_size": int(screen_size), "is_on": True}
        self._device_lock = asyncio.Lock()
        # Unknown after a start: the next single upload resets the device first,
        # in case it still runs a carousel (it ignores single uploads then).
        self._carousel_active = True
        self._gif_cfg = None
        self._listeners: list = []

    @property
    def connected(self) -> bool:
        client = self.conn.client
        return bool(client and client.is_connected)

    @property
    def data(self) -> dict:
        return {"connected": self.connected}

    def async_add_listener(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def async_update_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def async_connect(self) -> None:
        async with self._device_lock:
            await self._ensure_connected()

    async def async_disconnect(self) -> None:
        async with self._device_lock:
            await self.conn.disconnect()
        self.async_update_listeners()

    async def _ensure_connected(self) -> None:
        if self.connected:
            return
        try:
            await self.conn.connect()
        except (BleakError, ConnectionError, OSError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Connection to %s failed: %s", self.conn.address, err)
            raise HomeAssistantError(
                f"{self.entry.title} ne répond pas : allume-le, approche-le du PC et ferme l'appli iDotMatrix "
                "du téléphone (le cadre n'accepte qu'un appareil à la fois)."
            ) from err
        finally:
            self.async_update_listeners()

    async def _device_call(self, fn, *args, generation=None, **kwargs):
        """Finish an active write before propagating cancellation to its caller."""
        task = asyncio.ensure_future(self._device_call_locked(fn, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(task)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Device operation failed during cancellation")
            raise

    async def _device_call_locked(self, fn, *args, **kwargs):
        async with self._device_lock:
            await self._ensure_connected()
            # Modules built without a connection (the schedule's Common()) reach this display.
            ConnectionManager.bind(self.conn)
            return await fn(*args, **kwargs)

    async def _leave_carousel(self) -> None:
        if self._carousel_active:
            await Common(self.conn).reset()
            await asyncio.sleep(0.6)

    async def async_display_gif(self, path: str, rotation_interval: int = 5, files: list[str] | None = None) -> None:
        """Show one GIF (single upload) or a carousel of up to 12 (batch upload)."""
        self._gif_cfg = {"path": path, "rotation_interval": rotation_interval, "files": files}
        if not files and await self.hass.async_add_executor_job(os.path.isfile, path):
            label = os.path.basename(path)

            async def upload() -> bool:
                await self._leave_carousel()
                self.conn.transfer_label = label
                still = await self.hass.async_add_executor_job(first_frame_still, path)
                if still:
                    try:
                        await Gif(self.conn).uploadSingleRaw(still)
                    finally:
                        await self.hass.async_add_executor_job(os.remove, still)
                ok = await Gif(self.conn).uploadSingleRaw(path)
                if ok:
                    self._carousel_active = False
                return ok

            try:
                ok = await self._device_call(upload)
            except TransferRejectedError as err:
                raise HomeAssistantError(f"{err}: {label}") from err
            if not ok:
                raise HomeAssistantError(f"Envoi du GIF échoué : {label}")
            return

        if files:
            gifs = list(files)
        elif await self.hass.async_add_executor_job(os.path.isdir, path):
            gifs = sorted(os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".gif"))
        else:
            raise HomeAssistantError(f"Fichier introuvable : {path}")
        if not gifs:
            raise HomeAssistantError(f"Aucun GIF dans {path}")
        batch = gifs[:12]
        interval = max(1, min(0xFFFF if files else 255, int(rotation_interval)))

        async def upload_batch() -> bool:
            # Reset first: clears a wedged upload left by an aborted stream.
            await Common(self.conn).reset()
            await asyncio.sleep(0.6)
            self._carousel_active = True  # even a partial batch leaves the carousel on
            self.conn.transfer_label = "carrousel"
            return await Gif(self.conn).uploadBatch(
                batch, pixel_size=self.text_settings["screen_size"], interval=interval, raw=True)

        try:
            ok = await self._device_call(upload_batch)
        except TransferRejectedError as err:
            raise HomeAssistantError(f"Envoi du carrousel échoué : {err}") from err
        if not ok:
            raise HomeAssistantError("Envoi du carrousel échoué")

    async def async_stop_gif_display(self) -> None:
        if self._gif_cfg is None:
            return
        if await self._device_call(Common(self.conn).reset) is False:
            raise HomeAssistantError("Impossible d'arrêter l'affichage du GIF")
        self._carousel_active = False

    async def _upload_single(self, gif_bytes: bytes, generation: int | None = None,
                             label: str | None = None) -> bool:
        """Send a GIF made in memory (the panel's live preview)."""
        async def run() -> bool:
            def write_tmp() -> str:
                fd, path = tempfile.mkstemp(suffix=".gif")
                with os.fdopen(fd, "wb") as handle:
                    handle.write(gif_bytes)
                return path

            tmp_path = await self.hass.async_add_executor_job(write_tmp)
            try:
                await self._leave_carousel()
                self.conn.transfer_label = label
                try:
                    ok = await Gif(self.conn).uploadSingleRaw(tmp_path)
                except TransferRejectedError as err:
                    _LOGGER.warning("Device rejected the rendered GIF: %s", err)
                    return False
                if ok:
                    self._carousel_active = False
                return ok
            finally:
                await self.hass.async_add_executor_job(os.remove, tmp_path)

        return await self._device_call(run)
