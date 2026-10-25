"""Base entities of Emby Plus."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER
from .entity_ids import english_object_id
from .hub import EmbyHub


def server_device_info(hub: EmbyHub) -> DeviceInfo:
    """The Emby server as a device (parent of the players)."""
    info = DeviceInfo(
        identifiers={(DOMAIN, hub.server_id)},
        name=hub.server_name,
        manufacturer=MANUFACTURER,
        model="Emby Server",
        configuration_url=f"{hub.client.base_url}/web/index.html",
    )
    # unknown while the server is off - keep the version stored in the device registry
    if hub.server_version:
        info["sw_version"] = hub.server_version
    return info


class EmbyEntity(Entity):
    """Entity that follows the hub: state written after every change it announces."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: EmbyHub) -> None:
        self.hub = hub

    @property
    def suggested_object_id(self) -> str | None:
        """English name for the entity id in every HA language (the shown name is translated)."""
        return english_object_id(
            self.platform.domain,
            self.translation_key,
            self.device_class,
            super().suggested_object_id,
        )

    async def async_added_to_hass(self) -> None:
        """Listen to the hub."""
        self.async_on_remove(self.hub.async_add_listener(self._handle_hub_update))

    def _handle_hub_update(self) -> None:
        self.async_write_ha_state()
