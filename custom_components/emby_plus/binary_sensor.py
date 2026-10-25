"""Is the Emby server reachable."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EmbyConfigEntry
from .entity import EmbyEntity, server_device_info
from .hub import EmbyHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EmbyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the server connectivity sensor."""
    async_add_entities([EmbyServerConnected(entry.runtime_data)])


class EmbyServerConnected(EmbyEntity, BinarySensorEntity):
    """On while the websocket to the server is open."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "server"

    def __init__(self, hub: EmbyHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.server_id}_server"
        self._attr_device_info = server_device_info(hub)

    @property
    def is_on(self) -> bool:
        """Connected to the server."""
        return self.hub.connected
