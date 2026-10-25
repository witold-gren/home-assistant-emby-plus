"""How many sessions are playing something."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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
    """Add the active playbacks sensor."""
    async_add_entities([EmbyActivePlaybacks(entry.runtime_data)])


class EmbyActivePlaybacks(EmbyEntity, SensorEntity):
    """Number of sessions with something playing or paused; titles in `playing`."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "active_playbacks"

    def __init__(self, hub: EmbyHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.server_id}_active_playbacks"
        self._attr_device_info = server_device_info(hub)
        self._last: tuple | None = None

    def _playing(self) -> list[dict[str, str]]:
        return [
            {
                "device": session.get("DeviceName", ""),
                "client": session.get("Client", ""),
                "title": session["NowPlayingItem"].get("Name", ""),
            }
            for key, session in sorted(self.hub.sessions.items())
            if key in self.hub.active and session.get("NowPlayingItem")
        ]

    @property
    def available(self) -> bool:
        """Known only while connected."""
        return self.hub.connected

    @property
    def native_value(self) -> int:
        """Number of playbacks."""
        return len(self._playing())

    @property
    def extra_state_attributes(self) -> dict:
        """What plays where."""
        return {"playing": self._playing()}

    def _handle_hub_update(self) -> None:
        # session updates come every 1.5 s - write only real changes
        current = (self.hub.connected, tuple(tuple(p.values()) for p in self._playing()))
        if current != self._last:
            self._last = current
            self.async_write_ha_state()
