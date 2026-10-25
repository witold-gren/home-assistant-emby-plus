"""Config flow: server address and API key, filled in from the core YAML when present."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SSL
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import create_client
from .api import CannotConnect, InvalidAuth
from .const import DEFAULT_PORT, DOMAIN
from .migration import async_find_yaml_config

try:  # Home Assistant 2026.10+ validates with probatio, older versions with voluptuous
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

API_KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _server_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, False)): bool,
            vol.Required(CONF_API_KEY, default=defaults.get(CONF_API_KEY, "")): API_KEY_SELECTOR,
        }
    )


class EmbyPlusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add an Emby server."""

    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> tuple[dict | None, dict[str, str]]:
        """Return (server info, errors)."""
        client = create_client(self.hass, data, f"{DOMAIN}-config-flow")
        try:
            return await client.async_get_server_info(), {}
        except InvalidAuth:
            return None, {"base": "invalid_auth"}
        except CannotConnect:
            return None, {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error while connecting to Emby")
            return None, {"base": "unknown"}

    @staticmethod
    def _clean(user_input: Mapping[str, Any]) -> dict[str, Any]:
        return {
            CONF_HOST: str(user_input[CONF_HOST]).strip(),
            CONF_PORT: int(user_input[CONF_PORT]),
            CONF_SSL: bool(user_input[CONF_SSL]),
            CONF_API_KEY: str(user_input[CONF_API_KEY]).strip(),
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the server; the YAML of the core integration fills in the form."""
        errors: dict[str, str] = {}
        defaults: Mapping[str, Any] = {}
        if user_input is not None:
            data = self._clean(user_input)
            info, errors = await self._async_validate(data)
            if info:
                await self.async_set_unique_id(info["Id"])
                self._abort_if_unique_id_configured(updates=data)
                return self.async_create_entry(
                    title=info.get("ServerName") or data[CONF_HOST], data=data
                )
            defaults = data
        if not defaults:
            defaults = await async_find_yaml_config(self.hass) or {}
        return self.async_show_form(
            step_id="user", data_schema=_server_schema(defaults), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or key of the configured server."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._clean(user_input)
            info, errors = await self._async_validate(data)
            if info:
                await self.async_set_unique_id(info["Id"])
                self._abort_if_unique_id_mismatch(reason="wrong_server")
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_server_schema(user_input or entry.data),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The server rejected the API key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_API_KEY: user_input[CONF_API_KEY].strip()}
            info, errors = await self._async_validate(data)
            if info:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): API_KEY_SELECTOR}),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )
