"""EmbyHub: session bookkeeping and the websocket loop with reconnects."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.emby_plus.api import CannotConnect, InvalidAuth
from custom_components.emby_plus.hub import EmbyHub


def make_hub(hass, sessions_answer=None) -> EmbyHub:
    client = MagicMock()
    client.device_id = "emby_plus-test"
    client.async_get_sessions = AsyncMock(return_value=sessions_answer or [])
    client.async_get_server_info = AsyncMock(
        return_value={"Id": "srv", "ServerName": "NAS", "Version": "4.9"}
    )
    return EmbyHub(hass, client, {"Id": "srv", "ServerName": "NAS", "Version": "4.9"})


def message(kind: str, data=None) -> MagicMock:
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = json.dumps({"MessageType": kind, "Data": data})
    return msg


class FakeWebsocket:
    """Gives queued messages, then a CLOSED one (or waits, when `hold` is set)."""

    def __init__(self, messages, hold=False) -> None:
        self.messages = list(messages)
        self.hold = hold
        self.sent: list[dict] = []
        self.closed = False

    async def send_str(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def receive(self, timeout=None):
        if self.messages:
            item = self.messages.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if self.hold:
            await asyncio.Event().wait()
        closed = MagicMock()
        closed.type = aiohttp.WSMsgType.CLOSED
        return closed

    async def close(self) -> None:
        self.closed = True


async def test_sessions_skip_own_client_and_keep_ended_ones(hass, sessions) -> None:
    hub = make_hub(hass)
    seen: list[list[str]] = []
    hub.async_add_new_session_listener(seen.append)
    hub.async_update_sessions(sessions)
    assert seen == [["tv-0001.Emby for LG", "uuid:dlna-0001.Emby Server DLNA"]]
    # the DLNA session ended: still known, no longer active, not "new" again
    hub.async_update_sessions([s for s in sessions if s["Client"] != "Emby Server DLNA"])
    assert set(hub.sessions) == {"tv-0001.Emby for LG", "uuid:dlna-0001.Emby Server DLNA"}
    assert hub.active == {"tv-0001.Emby for LG"}
    assert len(seen) == 1


async def test_sessions_without_ids_are_ignored(hass) -> None:
    hub = make_hub(hass)
    hub.async_update_sessions([{"DeviceId": "x"}, {"Client": "y"}])
    assert hub.sessions == {}


async def test_listener_removal(hass) -> None:
    hub = make_hub(hass)
    calls = []
    remove = hub.async_add_listener(lambda: calls.append(1))
    hub.async_update_sessions([])
    remove()
    hub.async_update_sessions([])
    assert calls == [1]


async def test_messages(hass, sessions) -> None:
    hub = make_hub(hass)
    assert hub._handle_message(json.dumps({"MessageType": "Sessions", "Data": sessions})) is None
    assert "tv-0001.Emby for LG" in hub.active
    assert hub._handle_message(json.dumps({"MessageType": "ForceKeepAlive", "Data": 60})) == 30
    assert hub._handle_message(json.dumps({"MessageType": "ForceKeepAlive", "Data": 4})) == 5
    assert hub._handle_message("not json") is None
    assert hub._handle_message(json.dumps({"MessageType": "Ping"})) is None


async def test_websocket_subscribes_and_reconnects(hass, sessions) -> None:
    hub = make_hub(hass, sessions)
    first = FakeWebsocket([message("Sessions", sessions[:4])])
    second = FakeWebsocket([], hold=True)
    hub.client.async_ws_connect = AsyncMock(side_effect=[CannotConnect("NAS off"), first, second])
    states: list[bool] = []
    hub.async_add_listener(lambda: states.append(hub.connected))
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        sleeps.append(delay)
        await real_sleep(0)

    with patch("custom_components.emby_plus.hub.asyncio.sleep", fake_sleep):
        task = hass.async_create_task(hub.async_run())
        for _ in range(50):
            await real_sleep(0)
            if hub.client.async_ws_connect.await_count == 3 and hub.connected:
                break
    assert hub.client.async_ws_connect.await_count == 3
    assert hub.connected
    # failed attempt -> 5 s; the first websocket closed after working -> back to 5 s
    assert sleeps == [5, 5]
    assert first.sent[0] == {"MessageType": "SessionsStart", "Data": "0,1500"}
    assert first.closed
    assert False in states
    await hub.async_stop()
    task.cancel()
    assert second.closed


async def test_reconnect_delays_grow(hass) -> None:
    hub = make_hub(hass)
    hub.client.async_ws_connect = AsyncMock(side_effect=CannotConnect("off"))
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 6:
            hub._stopped = True

    with patch("custom_components.emby_plus.hub.asyncio.sleep", fake_sleep):
        await hub.async_run()
    assert sleeps == [5, 10, 30, 60, 60, 60]
    assert not hub.connected


async def test_lost_connection_is_logged_once(hass, caplog) -> None:
    hub = make_hub(hass)
    hub.client.async_ws_connect = AsyncMock(side_effect=CannotConnect("off"))

    async def fake_sleep(delay):
        if hub.client.async_ws_connect.await_count >= 4:
            hub._stopped = True

    with patch("custom_components.emby_plus.hub.asyncio.sleep", fake_sleep):
        await hub.async_run()
    assert caplog.text.count("Lost connection to Emby server") == 1


async def test_keepalive_is_sent(hass) -> None:
    hub = make_hub(hass)
    ws = FakeWebsocket([TimeoutError(), message("ForceKeepAlive", 10)])
    hub.client.async_ws_connect = AsyncMock(return_value=ws)
    clock = iter(range(0, 1000, 20))
    with (
        patch("custom_components.emby_plus.hub.time.monotonic", lambda: next(clock)),
        pytest.raises(CannotConnect),
    ):
        await hub._async_listen()
    assert {"MessageType": "KeepAlive"} in ws.sent


async def test_unexpected_error_does_not_stop_the_loop(hass, caplog) -> None:
    hub = make_hub(hass)
    hub.client.async_ws_connect = AsyncMock(side_effect=[RuntimeError("bug"), CannotConnect("x")])

    async def fake_sleep(delay):
        if hub.client.async_ws_connect.await_count >= 2:
            hub._stopped = True

    with patch("custom_components.emby_plus.hub.asyncio.sleep", fake_sleep):
        await hub.async_run()
    assert "Unexpected error in the Emby websocket" in caplog.text
    assert hub.client.async_ws_connect.await_count == 2


async def test_rejected_key_while_reconnecting_starts_reauth(hass, caplog) -> None:
    """A key revoked while the server was off: one reauth, no error every minute."""
    hub = make_hub(hass)
    hub.client.async_ws_connect = AsyncMock(side_effect=InvalidAuth("HTTP 401"))
    hub.on_auth_failed = MagicMock()
    with patch("custom_components.emby_plus.hub.asyncio.sleep", AsyncMock()):
        await hub.async_run()
    hub.on_auth_failed.assert_called_once()
    assert hub.client.async_ws_connect.await_count == 1
    assert not hub.connected
    assert "rejected the API key" in caplog.text


async def test_server_update_while_off_reaches_the_device(hass, device_registry) -> None:
    """The NAS came back with a newer Emby - the server device shows the new version."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="emby_plus")
    entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("emby_plus", "srv")}, sw_version="4.9"
    )
    hub = make_hub(hass)
    hub.server_device_id = device.id
    hub.client.async_get_server_info.return_value = {
        "Id": "srv",
        "ServerName": "NAS",
        "Version": "4.10",
    }
    hub.client.async_ws_connect = AsyncMock(return_value=FakeWebsocket([]))
    with pytest.raises(CannotConnect):
        await hub._async_listen()
    assert hub.server_version == "4.10"
    assert device_registry.async_get(device.id).sw_version == "4.10"


async def test_lost_connection_is_not_a_warning(hass, caplog) -> None:
    """The NAS is switched off every day - that is no warning."""
    hub = make_hub(hass)
    hub.client.async_ws_connect = AsyncMock(side_effect=CannotConnect("off"))

    async def fake_sleep(delay):
        hub._stopped = True

    with patch("custom_components.emby_plus.hub.asyncio.sleep", fake_sleep):
        await hub.async_run()
    assert [r.levelname for r in caplog.records if "Lost connection" in r.message] == ["INFO"]
