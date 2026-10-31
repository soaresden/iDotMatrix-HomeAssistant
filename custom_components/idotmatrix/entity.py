"""Base entity for iDotMatrix."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_MAC, CONF_NAME

class IDotMatrixEntity(CoordinatorEntity):
    """Base class for iDotMatrix entities."""

    def __init__(self, coordinator, entry):
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_has_entity_name = True
        self._mac = entry.data[CONF_MAC]
        self._device_name = entry.data.get(CONF_NAME, "iDotMatrix")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            name=self._device_name,
            manufacturer="iDotMatrix",
            model="Bluetooth Pixel Display",
            connections={("bluetooth", self._mac)},
            # "Visit" button on the device page opens the Pixel Studio panel.
            configuration_url="homeassistant://pixel-studio",
        )
