"""Emby Plus: Emby players configured in the UI, reconnecting when the server comes back.

Why not the core `emby` integration: it is YAML-only, and pyEmby registers with the server
once, at Home Assistant start. A server that is off then (e.g. a NAS on a schedule) leaves
every player unavailable until the next restart. Here the setup raises
ConfigEntryNotReady, so Home Assistant retries it, and the websocket reconnects on its own.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CannotConnect, EmbyClient, InvalidAuth
from .const import DOMAIN
from .entity import server_device_info
from .hub import EmbyHub
from .migration import async_adopt_core_entities, async_find_yaml_config, async_update_yaml_issue

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
    """Connect to the server; not reachable = Home Assistant retries later."""
    client = create_client(hass, dict(entry.data), f"{DOMAIN}-{entry.entry_id}")
    try:
        info = await client.async_get_server_info()
        sessions = await client.async_get_sessions()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        ) from err
    except CannotConnect as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"url": client.base_url, "error": str(err)},
        ) from err

    yaml_config = await async_find_yaml_config(hass)
    async_update_yaml_issue(hass, yaml_config is not None)
    if yaml_config is None:
        async_adopt_core_entities(hass, entry)

    hub = EmbyHub(hass, client, info)
    # the server device first - the players link to it (via_device_id)
    server = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **server_device_info(hub)
    )
    hub.server_device_id = server.id
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
