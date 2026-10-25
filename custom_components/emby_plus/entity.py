"""Base entities of Emby Plus."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER
from .hub import EmbyHub


def server_device_info(hub: EmbyHub) -> DeviceInfo:
    """The Emby server as a device (parent of the players)."""
    return DeviceInfo(
        identifiers={(DOMAIN, hub.server_id)},
        name=hub.server_name,
        manufacturer=MANUFACTURER,
        model="Emby Server",
        sw_version=hub.server_version,
        configuration_url=f"{hub.client.base_url}/web/index.html",
    )


class EmbyEntity(Entity):
    """Entity that follows the hub: state written after every change it announces."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: EmbyHub) -> None:
        self.hub = hub

    async def async_added_to_hass(self) -> None:
        """Listen to the hub."""
        self.async_on_remove(self.hub.async_add_listener(self._handle_hub_update))

    def _handle_hub_update(self) -> None:
        self.async_write_ha_state()
