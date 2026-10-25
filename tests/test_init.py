"""Setup, retry when the server is off, unload, YAML issue and taking over core entities."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)

from custom_components.emby_plus import async_remove_config_entry_device
from custom_components.emby_plus.const import DOMAIN, ISSUE_YAML_PLATFORM

from .conftest import BASE, entry_for

YAML = {"media_player": [{"platform": "emby", "host": "10.0.0.2", "api_key": "secret"}]}


async def test_setup_and_unload(hass: HomeAssistant, setup_entry) -> None:
    assert setup_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.domowy_nas_server").state == "on"
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    assert setup_entry.state is ConfigEntryState.NOT_LOADED


async def test_server_off_at_start_is_not_an_error(
    hass: HomeAssistant,
    aioclient_mock,
    server_info,
    sessions,
    no_yaml,
    no_websocket,
    device_registry: dr.DeviceRegistry,
) -> None:
    """The bug of the core integration: NAS off at Home Assistant start. Off is a normal
    state here - the entry loads, known players exist and the websocket loop connects."""
    # a previous run left the server (with its version) and a player in the registry
    entry = entry_for(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "a1b2c3d4e5f6")},
        name="Domowy NAS",
        sw_version="4.9.1.80",
    )
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "tv-0001.Emby for LG")},
        name="LG Smart TV",
        model="Emby for LG",
    )
    aioclient_mock.get(f"{BASE}/System/Info", exc=aiohttp.ClientConnectionError())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.reason is None
    assert hass.states.get("binary_sensor.domowy_nas_server").state == "off"
    assert hass.states.get("sensor.domowy_nas_active_playbacks").state == "unavailable"
    tv = hass.states.get("media_player.lg_smart_tv")
    assert tv.state == "unavailable"
    assert not tv.attributes.get("restored")
    server = device_registry.async_get_device_by_identifier(
        (DOMAIN, "a1b2c3d4e5f6"), entry.entry_id
    )
    assert server.sw_version == "4.9.1.80"

    # the NAS is on now - the websocket loop connects and the players come back
    hub = entry.runtime_data
    hub.async_update_sessions(sessions)
    hub._set_connected(True)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.domowy_nas_server").state == "on"
    assert hass.states.get("media_player.lg_smart_tv").state == "playing"


async def test_rejected_key_starts_reauth(
    hass: HomeAssistant, aioclient_mock, no_yaml, no_websocket
) -> None:
    aioclient_mock.get(f"{BASE}/System/Info", status=401)
    entry = entry_for(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flows[0]["context"]["source"] == "reauth"


async def test_yaml_block_raises_issue_and_keeps_core_entities(
    hass: HomeAssistant, mock_server, no_websocket, entity_registry: er.EntityRegistry
) -> None:
    old = entity_registry.async_get_or_create(
        "media_player", "emby", "tv-0001.Emby for LG", suggested_object_id="emby_tv"
    )
    entry = entry_for(hass)
    with patch("custom_components.emby_plus.migration.async_hass_config_yaml", return_value=YAML):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_YAML_PLATFORM)
    # the core integration still owns its entity - no takeover while YAML is there
    assert entity_registry.async_get(old.entity_id).platform == "emby"


async def test_core_entities_are_taken_over(
    hass: HomeAssistant, mock_server, no_yaml, no_websocket, entity_registry: er.EntityRegistry
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_YAML_PLATFORM,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_YAML_PLATFORM,
    )
    old = entity_registry.async_get_or_create(
        "media_player", "emby", "tv-0001.Emby for LG", suggested_object_id="emby_salon_tv"
    )
    entity_registry.async_update_entity(old.entity_id, name="Telewizor", area_id="salon")
    # restored "unavailable" state written at start for the not-yet-loaded core entity
    hass.states.async_set(old.entity_id, "unavailable", {"restored": True})
    other = entity_registry.async_get_or_create("media_player", "cast", "x")

    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    new = entity_registry.async_get("media_player.emby_salon_tv")
    assert new.platform == DOMAIN
    assert new.config_entry_id == entry.entry_id
    assert (new.name, new.area_id) == ("Telewizor", "salon")
    assert hass.states.get("media_player.emby_salon_tv").state == "playing"
    assert entity_registry.async_get(other.entity_id).platform == "cast"
    assert not ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_YAML_PLATFORM)
    # the DLNA session got a new entity - no core entity to take over
    assert hass.states.get("media_player.lg_webos_tv_oled55")


async def test_unreadable_yaml_counts_as_no_yaml(
    hass: HomeAssistant, mock_server, no_websocket
) -> None:
    from homeassistant.exceptions import HomeAssistantError

    entry = entry_for(hass)
    with patch(
        "custom_components.emby_plus.migration.async_hass_config_yaml",
        side_effect=HomeAssistantError("bad yaml"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
    assert not ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_YAML_PLATFORM)


async def test_entity_created_during_yaml_period_gives_way(
    hass: HomeAssistant, mock_server, no_yaml, no_websocket, entity_registry: er.EntityRegistry
) -> None:
    """Emby Plus ran once next to the YAML block, then the block was removed."""
    entry = entry_for(hass)
    entity_registry.async_get_or_create(
        "media_player", "emby", "tv-0001.Emby for LG", suggested_object_id="emby_salon_tv"
    )
    entity_registry.async_get_or_create(
        "media_player",
        DOMAIN,
        "tv-0001.Emby for LG",
        config_entry=entry,
        suggested_object_id="lg_smart_tv_oled55",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get("media_player.emby_salon_tv").platform == DOMAIN
    assert entity_registry.async_get("media_player.lg_smart_tv_oled55") is None
    assert hass.states.get("media_player.emby_salon_tv").state == "playing"


async def test_core_entities_of_api_clients_are_dropped(
    hass: HomeAssistant, mock_server, no_yaml, no_websocket, entity_registry: er.EntityRegistry
) -> None:
    for unique_id in (
        "server-1.Home Assistant",
        "2335917080054.pyEmby",
        "emby_plus-x.Home Assistant",
    ):
        entity_registry.async_get_or_create("media_player", "emby", unique_id)
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not [
        e
        for e in entity_registry.entities.values()
        if e.platform in ("emby", DOMAIN)
        and e.domain == "media_player"
        and "Home Assistant" in e.unique_id
    ]
    assert not [e for e in entity_registry.entities.values() if e.unique_id.endswith("pyEmby")]


async def test_remove_inactive_player_device(
    hass: HomeAssistant, setup_entry, sessions, device_registry: dr.DeviceRegistry
) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "config", {})
    hub = setup_entry.runtime_data
    server = device_registry.async_get_device_by_identifier(
        (DOMAIN, "a1b2c3d4e5f6"), setup_entry.entry_id
    )
    tv_key = "tv-0001.Emby for LG"
    tv = device_registry.async_get_device_by_identifier((DOMAIN, tv_key), setup_entry.entry_id)
    assert not await async_remove_config_entry_device(hass, setup_entry, server)
    assert not await async_remove_config_entry_device(hass, setup_entry, tv)
    hub.async_update_sessions([s for s in sessions if s["DeviceId"] != "tv-0001"])
    assert await async_remove_config_entry_device(hass, setup_entry, tv)
    # the app comes back - its player is added again
    assert tv_key not in hub.sessions
    hub.async_update_sessions(sessions)
    assert tv_key in hub.sessions
