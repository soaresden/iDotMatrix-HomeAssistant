"""Image platform for iDotMatrix: a live preview of the display."""
from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import IDotMatrixEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the iDotMatrix preview image."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IDotMatrixPreview(hass, coordinator, entry)])


class IDotMatrixPreview(IDotMatrixEntity, ImageEntity):
    """LED-style render of the content last sent to the display.

    Animated content stays animated (the frontend shows the GIF as-is).
    Empty while the device draws content itself (native text, firmware
    clock) or before anything was sent since Home Assistant started.
    """

    _attr_icon = "mdi:led-strip-variant"
    _attr_name = "Preview"
    _attr_content_type = "image/gif"

    def __init__(self, hass: HomeAssistant, coordinator, entry: ConfigEntry) -> None:
        IDotMatrixEntity.__init__(self, coordinator, entry)
        ImageEntity.__init__(self, hass)
        self._attr_image_last_updated = coordinator.preview_updated

    @property
    def unique_id(self) -> str:
        return f"{self._mac}_preview"

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = self.coordinator.preview_updated
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        return self.coordinator.preview
