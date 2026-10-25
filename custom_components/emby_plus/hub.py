"""Connection to one Emby server: sessions over a websocket, reconnecting on its own."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
import time
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant, callback

from .api import CLIENT_NAME, CannotConnect, EmbyClient, session_key
from .const import DOMAIN, KEEPALIVE_INTERVAL, RECONNECT_DELAYS, SESSIONS_INTERVAL_MS

_LOGGER = logging.getLogger(__name__)

# client names of Home Assistant integrations talking to Emby (ours and pyEmby)
API_CLIENTS = frozenset({CLIENT_NAME, "pyEmby"})


class EmbyHub:
    """Keeps the sessions of one server up to date and tells the entities about changes."""

    def __init__(self, hass: HomeAssistant, client: EmbyClient, info: dict[str, Any]) -> None:
        self.hass = hass
        self.client = client
        self.server_id: str = info["Id"]
        self.server_name: str = info.get("ServerName") or "Emby"
        self.server_version: str | None = info.get("Version")
        self.server_device_id: str | None = None
        self.connected = True
        # key (DeviceId.Client) -> session; keys stay after a session ends
        self.sessions: dict[str, dict[str, Any]] = {}
        self.active: set[str] = set()
        self._listeners: list[Callable[[], None]] = []
        self._new_session_listeners: list[Callable[[list[str]], None]] = []
        self._stopped = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        """Call `update` after every change of sessions or connection; returns the remover."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def async_add_new_session_listener(
        self, new: Callable[[list[str]], None]
    ) -> Callable[[], None]:
        """Call `new` with keys of sessions seen for the first time."""
        self._new_session_listeners.append(new)
        return lambda: self._new_session_listeners.remove(new)

    @callback
    def async_update_sessions(self, sessions: list[dict[str, Any]]) -> None:
        """Store a full session list (REST answer or websocket "Sessions" message)."""
        new: list[str] = []
        active: set[str] = set()
        for session in sessions:
            if not session.get("DeviceId") or not session.get("Client"):
                continue
            if self._is_api_client(session):
                continue
            key = session_key(session)
            if key not in self.sessions:
                new.append(key)
            self.sessions[key] = session
            active.add(key)
        self.active = active
        if new:
            for listener in list(self._new_session_listeners):
                listener(new)
        self._notify()

    def _is_api_client(self, session: dict[str, Any]) -> bool:
        """Sessions of API clients, not players: this integration (also its config flow),
        the core integration (pyEmby) and requests made with the API key alone, which
        Emby files under the server's own id."""
        device_id = session["DeviceId"]
        return (
            device_id.startswith(f"{DOMAIN}-")
            or device_id == self.server_id
            or session["Client"] in API_CLIENTS
        )

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _set_connected(self, connected: bool) -> None:
        if connected == self.connected:
            return
        self.connected = connected
        # log only the changes - the server (a NAS) may be off for hours
        if connected:
            _LOGGER.info("Connected to Emby server %s", self.server_name)
        else:
            _LOGGER.warning(
                "Lost connection to Emby server %s, reconnecting in the background",
                self.server_name,
            )
        self._notify()

    async def async_run(self) -> None:
        """Keep the websocket open until stopped; reconnect with growing delays."""
        attempt = 0
        while not self._stopped:
            try:
                await self._async_listen()
            except CannotConnect as err:
                _LOGGER.debug("Emby websocket failed: %s", err)
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Emby websocket closed: %s", err)
            except Exception:
                _LOGGER.exception("Unexpected error in the Emby websocket, reconnecting")
            if self._stopped:
                break
            # a connection that worked starts the delays again from the shortest
            if self.connected:
                attempt = 0
            self._set_connected(False)
            delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _async_listen(self) -> None:
        self._ws = ws = await self.client.async_ws_connect()
        try:
            await ws.send_str(
                json.dumps({"MessageType": "SessionsStart", "Data": f"0,{SESSIONS_INTERVAL_MS}"})
            )
            # the websocket answers only on changes - start from the full list
            self.async_update_sessions(await self.client.async_get_sessions())
            self._set_connected(True)
            keepalive = KEEPALIVE_INTERVAL
            last_keepalive = time.monotonic()
            while not self._stopped:
                try:
                    msg = await ws.receive(timeout=keepalive)
                except TimeoutError:
                    msg = None
                if msg is not None:
                    if msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        raise CannotConnect(f"websocket {msg.type.name.lower()}")
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        keepalive = self._handle_message(msg.data) or keepalive
                # Emby closes a websocket that does not send KeepAlive (ForceKeepAlive)
                if time.monotonic() - last_keepalive >= keepalive:
                    await ws.send_str(json.dumps({"MessageType": "KeepAlive"}))
                    last_keepalive = time.monotonic()
        finally:
            self._ws = None
            await ws.close()

    @callback
    def _handle_message(self, data: str) -> float | None:
        """Process one websocket message; returns a new keep-alive interval if asked for."""
        try:
            message = json.loads(data)
        except ValueError:
            return None
        kind = message.get("MessageType")
        payload = message.get("Data")
        if kind == "Sessions" and isinstance(payload, list):
            self.async_update_sessions(payload)
        elif kind == "ForceKeepAlive" and isinstance(payload, int | float) and payload > 0:
            return max(payload / 2, 5)
        return None

    async def async_stop(self) -> None:
        """Stop the websocket loop."""
        self._stopped = True
        if self._ws is not None:
            await self._ws.close()
