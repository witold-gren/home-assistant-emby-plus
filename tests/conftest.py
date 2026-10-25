"""Shared fixtures: a mocked Emby server and a config entry."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SSL
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.emby_plus.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://10.0.0.2:8096/emby"
ENTRY_DATA = {CONF_HOST: "10.0.0.2", CONF_PORT: 8096, CONF_SSL: False, CONF_API_KEY: "secret"}


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom_components in tests."""


@pytest.fixture
def server_info() -> dict:
    return load("server_info.json")


@pytest.fixture
def sessions() -> list[dict]:
    return load("sessions.json")


@pytest.fixture
def no_yaml():
    """No core `platform: emby` in the YAML configuration."""
    with patch(
        "custom_components.emby_plus.migration.async_hass_config_yaml", return_value={}
    ) as mock:
        yield mock


@pytest.fixture
def no_websocket():
    """The websocket loop does nothing - tests drive the hub directly."""

    async def idle(self) -> None:
        return None

    with patch("custom_components.emby_plus.hub.EmbyHub.async_run", idle):
        yield


@pytest.fixture
def mock_server(aioclient_mock, server_info, sessions):
    aioclient_mock.get(f"{BASE}/System/Info", json=server_info)
    aioclient_mock.get(f"{BASE}/Sessions", json=sessions)
    return aioclient_mock


def entry_for(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Domowy NAS",
        unique_id="a1b2c3d4e5f6",
        data=dict(ENTRY_DATA),
        entry_id="test",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_entry(hass: HomeAssistant, mock_server, no_yaml, no_websocket) -> MockConfigEntry:
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def with_session(sessions: list[dict], key_device: str, **changes: Any) -> list[dict]:
    """Copy of `sessions` with fields of one session changed (None removes a field)."""
    result = copy.deepcopy(sessions)
    for session in result:
        if session["DeviceId"] == key_device:
            for field, value in changes.items():
                if value is None:
                    session.pop(field, None)
                else:
                    session[field] = value
    return result
