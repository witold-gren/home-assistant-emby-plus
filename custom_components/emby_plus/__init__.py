"""Emby Plus: Emby players configured in the UI, reconnecting when the server comes back.

Why not the core `emby` integration: it is YAML-only, and pyEmby registers with the server
once, at Home Assistant start. A server that is off then (e.g. a NAS on a schedule) leaves
every player unavailable until the next restart. Here a server that is off is a normal
state, not a setup error: the entry loads with the last known server and players, the
"Server" sensor is off, and the websocket loop connects as soon as the server answers.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CannotConnect, EmbyClient, InvalidAuth
from .const import DOMAIN
from .entity import server_device_info
from .hub import EmbyHub
from .migration import async_adopt_core_entities, async_find_yaml_config, async_update_yaml_issue

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.MEDIA_PLAYER, Platform.SENSOR]

type EmbyConfigEntry = ConfigEntry[EmbyHub]


def create_client(hass: HomeAssistant, data: dict, device_id: str) -> EmbyClient:
    """Client for the server in `data` (config entry data or the config flow form)."""
    return EmbyClient(
        async_get_clientsession(hass, verify_ssl=False),
        data[CONF_HOST],
        data[CONF_PORT],
        data[CONF_SSL],
        data[CONF_API_KEY],
        device_id,
    )


async def async_setup_entry(hass: HomeAssistant, entry: EmbyConfigEntry) -> bool:
    """Load the entry; a server that is off is connected later by the websocket loop."""
    client = create_client(hass, dict(entry.data), f"{DOMAIN}-{entry.entry_id}")
    sessions: list[dict] = []
    online = True
    try:
        info = await client.async_get_server_info()
        sessions = await client.async_get_sessions()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        ) from err
    except CannotConnect as err:
        # the unique id is the server id; name and version stay in the device registry
        _LOGGER.info(
            "Emby server at %s is off (%s), connecting when it answers", client.base_url, err
        )
        info = {"Id": entry.unique_id, "ServerName": entry.title}
        online = False

    yaml_config = await async_find_yaml_config(hass)
    async_update_yaml_issue(hass, yaml_config is not None)
    if yaml_config is None:
        async_adopt_core_entities(hass, entry)

    hub = EmbyHub(hass, client, info)
    hub.connected = online
    hub.on_auth_failed = lambda: entry.async_start_reauth(hass)
    device_registry = dr.async_get(hass)
    # the server device first - the players link to it (via_device_id)
    server = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, **server_device_info(hub)
    )
    hub.server_device_id = server.id
    hub.async_restore_players(dr.async_entries_for_config_entry(device_registry, entry.entry_id))
    hub.async_update_sessions(sessions)
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, hub.async_run(), f"{DOMAIN} websocket")
    entry.async_on_unload(hub.async_stop)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: EmbyConfigEntry, device: dr.DeviceEntry
) -> bool:
    """A player device can be deleted in the UI while its app is not running."""
    hub = entry.runtime_data
    keys = {key for domain, key in device.identifiers if domain == DOMAIN}
    if hub.server_id in keys or keys & hub.active:
        return False
    # forget it, so the player is added again if the app comes back
    for key in keys:
        hub.sessions.pop(key, None)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EmbyConfigEntry) -> bool:
    """Stop the websocket and unload the platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
