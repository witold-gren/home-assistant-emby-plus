"""Moving from the core Emby integration (YAML `media_player: - platform: emby`)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config import async_hass_config_yaml
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PLATFORM, CONF_PORT, CONF_SSL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import CORE_DOMAIN, DEFAULT_PORT, DEFAULT_SSL_PORT, DOMAIN, ISSUE_YAML_PLATFORM
from .hub import API_CLIENTS

_LOGGER = logging.getLogger(__name__)

# registry fields the user may have changed on an entity of the core integration
_KEPT_FIELDS = ("name", "icon", "area_id", "aliases", "hidden_by", "labels")


async def async_find_yaml_config(hass: HomeAssistant) -> dict[str, Any] | None:
    """Return host/port/ssl/api_key of `platform: emby` in the YAML configuration, if any."""
    try:
        config = await async_hass_config_yaml(hass)
    except HomeAssistantError as err:
        _LOGGER.debug("Cannot read the YAML configuration: %s", err)
        return None
    platforms = config.get("media_player") or []
    if isinstance(platforms, dict):
        platforms = [platforms]
    for platform in platforms:
        if isinstance(platform, dict) and platform.get(CONF_PLATFORM) == CORE_DOMAIN:
            ssl = bool(platform.get(CONF_SSL, False))
            return {
                CONF_HOST: platform.get(CONF_HOST, "localhost"),
                CONF_PORT: int(
                    platform.get(CONF_PORT) or (DEFAULT_SSL_PORT if ssl else DEFAULT_PORT)
                ),
                CONF_SSL: ssl,
                CONF_API_KEY: platform.get(CONF_API_KEY, ""),
            }
    return None


def async_update_yaml_issue(hass: HomeAssistant, yaml_present: bool) -> None:
    """Ask to remove the YAML block - otherwise both integrations show the same players."""
    if yaml_present:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_YAML_PLATFORM,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_YAML_PLATFORM,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_YAML_PLATFORM)


def async_adopt_core_entities(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Take over entities of the core integration, keeping their entity_id and settings.

    Both integrations use the same unique_id (DeviceId.Client), but the registry keeps
    entities per integration, so without this step Home Assistant would create new
    entities with a `_2` suffix. Only run when the core integration is no longer set up.
    """
    registry = er.async_get(hass)
    adopted: list[str] = []
    for old in list(registry.entities.values()):
        if old.platform != CORE_DOMAIN or old.domain != "media_player":
            continue
        # players the core integration made of API clients (Home Assistant itself) - drop
        device_id, _, client = old.unique_id.rpartition(".")
        if client in API_CLIENTS or device_id.startswith(f"{DOMAIN}-"):
            registry.async_remove(old.entity_id)
            continue
        # an entity created by us while the YAML block was still there gives way to the
        # core one, whose entity_id the dashboards and automations use
        if ours := registry.async_get_entity_id("media_player", DOMAIN, old.unique_id):
            registry.async_remove(ours)
        kept = {field: getattr(old, field) for field in _KEPT_FIELDS}
        registry.async_remove(old.entity_id)
        # the "unavailable" state restored at start would make the entity_id look taken
        if (state := hass.states.get(old.entity_id)) and state.attributes.get("restored"):
            hass.states.async_remove(old.entity_id)
        new = registry.async_get_or_create(
            "media_player",
            DOMAIN,
            old.unique_id,
            config_entry=entry,
            suggested_object_id=old.entity_id.split(".", 1)[1],
            disabled_by=old.disabled_by,
        )
        # a re-created entity may come back with the entity_id it had before deletion
        if new.entity_id != old.entity_id:
            kept["new_entity_id"] = old.entity_id
        new = registry.async_update_entity(new.entity_id, **kept)
        adopted.append(new.entity_id)
    if adopted:
        _LOGGER.info("Took over %d entities of the core Emby integration", len(adopted))
    return adopted
