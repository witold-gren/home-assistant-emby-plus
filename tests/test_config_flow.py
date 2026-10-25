"""Config flow: add, YAML prefill, errors, reconfigure and reauth."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.emby_plus.const import DOMAIN

from .conftest import BASE, ENTRY_DATA, entry_for

FORM = {CONF_HOST: " 10.0.0.2 ", CONF_PORT: 8096.0, CONF_SSL: False, CONF_API_KEY: "secret "}


@pytest.fixture(autouse=True)
def no_setup():
    """Creating the entry must not start the integration."""
    with patch("custom_components.emby_plus.async_setup_entry", return_value=True):
        yield


def form_defaults(result) -> dict:
    return {
        str(key): key.default() for key in result["data_schema"].schema if callable(key.default)
    }


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_server, no_yaml) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert form_defaults(result)[CONF_PORT] == 8096
    result = await hass.config_entries.flow.async_configure(result["flow_id"], FORM)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Domowy NAS"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == "a1b2c3d4e5f6"


async def test_form_is_filled_from_core_yaml(hass: HomeAssistant) -> None:
    yaml = {
        "media_player": [{"platform": "cast"}, {"platform": "emby", "host": "nas", "api_key": "k"}]
    }
    with patch("custom_components.emby_plus.migration.async_hass_config_yaml", return_value=yaml):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert form_defaults(result) == {
        CONF_HOST: "nas",
        CONF_PORT: 8096,
        CONF_SSL: False,
        CONF_API_KEY: "k",
    }


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"status": 401}, "invalid_auth"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
        ({"exc": KeyError("x")}, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, aioclient_mock, no_yaml, kwargs, error
) -> None:
    aioclient_mock.get(f"{BASE}/System/Info", **kwargs)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], FORM)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    # the form keeps what was typed
    assert form_defaults(result)[CONF_HOST] == "10.0.0.2"


async def test_same_server_is_aborted(hass: HomeAssistant, mock_server, no_yaml) -> None:
    entry_for(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], FORM)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant, aioclient_mock, server_info) -> None:
    entry = entry_for(hass)
    aioclient_mock.get("http://nas:8096/emby/System/Info", json=server_info)
    result = await entry.start_reconfigure_flow(hass)
    assert form_defaults(result)[CONF_HOST] == "10.0.0.2"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**FORM, CONF_HOST: "nas"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "nas"


async def test_reconfigure_to_other_server_is_refused(
    hass: HomeAssistant, aioclient_mock, server_info
) -> None:
    entry = entry_for(hass)
    aioclient_mock.get(f"{BASE}/System/Info", json={**server_info, "Id": "other"})
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], FORM)
    assert result["reason"] == "wrong_server"


async def test_reconfigure_error_shows_form(hass: HomeAssistant, aioclient_mock) -> None:
    entry = entry_for(hass)
    aioclient_mock.get(f"{BASE}/System/Info", status=500)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], FORM)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth(hass: HomeAssistant, mock_server) -> None:
    entry = entry_for(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: " new "}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new"


async def test_reauth_rejected_key(hass: HomeAssistant, aioclient_mock) -> None:
    entry = entry_for(hass)
    aioclient_mock.get(f"{BASE}/System/Info", status=401)
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
