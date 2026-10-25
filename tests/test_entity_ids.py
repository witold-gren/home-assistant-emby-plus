"""Entity ids are English in a Polish installation; the shown names stay translated."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import entry_for


def _polish_entity_ids(hass: HomeAssistant, entry_id: str) -> list[str]:
    """Entity ids that end with the Polish name (what HA builds in a Polish installation)."""
    entries = er.async_entries_for_config_entry(er.async_get(hass), entry_id)
    assert entries
    return [
        e.entity_id
        for e in entries
        if e.original_name
        and e.entity_id.split(".")[1].endswith(slugify(e.original_name))
        and not e.entity_id.split(".")[1].endswith(slugify(e.object_id_base or ""))
    ]


async def test_entity_ids_are_english(
    hass: HomeAssistant, mock_server, no_yaml, no_websocket
) -> None:
    hass.config.language = "pl"
    entry: MockConfigEntry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _polish_entity_ids(hass, entry.entry_id) == []
    server = hass.states.get("binary_sensor.domowy_nas_server")
    assert server.attributes["friendly_name"] == "Domowy NAS Serwer"
    assert hass.states.get("sensor.domowy_nas_active_playbacks") is not None
