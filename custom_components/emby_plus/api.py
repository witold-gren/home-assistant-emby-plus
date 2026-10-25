"""A small Emby client on Home Assistant's aiohttp session.

Replaces pyEmby, used by the core integration: pyEmby registers only once, with its own
aiohttp session, and never retries when the server is off at Home Assistant start.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import aiohttp

from .const import REQUEST_TIMEOUT, TICKS_PER_SECOND

CLIENT_NAME = "Home Assistant"


class EmbyError(Exception):
    """Base error of the Emby client."""


class CannotConnect(EmbyError):
    """The server is unreachable or answered with an error."""


class InvalidAuth(EmbyError):
    """The server rejected the API key."""


class EmbyClient:
    """HTTP and websocket access to one Emby server."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        ssl: bool,
        api_key: str,
        device_id: str,
        version: str = "0",
    ) -> None:
        self._session = session
        self._api_key = api_key
        self.device_id = device_id
        self.base_url = f"{'https' if ssl else 'http'}://{host}:{port}"
        self.ws_url = (
            f"{'wss' if ssl else 'ws'}://{host}:{port}"
            f"?api_key={quote(api_key)}&deviceId={quote(device_id)}"
        )
        self._headers = {
            "X-Emby-Token": api_key,
            "X-Emby-Authorization": (
                f'MediaBrowser Client="{CLIENT_NAME}", Device="{CLIENT_NAME}", '
                f'DeviceId="{device_id}", Version="{version}"'
            ),
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/emby{path}"
        # POST without a body: Emby waits for the data until the timeout, an empty JSON is enough
        body = {} if method == "POST" else None
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=body,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status in (401, 403):
                    raise InvalidAuth(f"HTTP {resp.status}")
                if resp.status >= 400:
                    raise CannotConnect(f"HTTP {resp.status} for {path}")
                if resp.status == 204:
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise CannotConnect(str(err) or type(err).__name__) from err

    async def async_get_server_info(self) -> dict[str, Any]:
        """Return the server info (Id, ServerName, Version); checks the API key."""
        info = await self._request("GET", "/System/Info")
        if not isinstance(info, dict) or "Id" not in info:
            raise CannotConnect("Unexpected answer to /System/Info")
        return info

    async def async_get_sessions(self) -> list[dict[str, Any]]:
        """Return the active sessions (one per client app on a device)."""
        sessions = await self._request("GET", "/Sessions")
        if not isinstance(sessions, list):
            raise CannotConnect("Unexpected answer to /Sessions")
        return sessions

    async def async_send_playstate(
        self, session_id: str, command: str, position: float | None = None
    ) -> None:
        """Send Pause, Unpause, Stop, NextTrack, PreviousTrack or Seek to a session."""
        params = None
        if position is not None:
            params = {"SeekPositionTicks": int(position * TICKS_PER_SECOND)}
        await self._request("POST", f"/Sessions/{session_id}/Playing/{command}", params)

    def image_url(self, item: dict[str, Any]) -> str | None:
        """Poster of the item: its own Primary image, else the series' or album's one.

        pyEmby built /Items/... without the /emby prefix and preferred the rarely present
        Thumb image, so the Home Assistant image proxy got 404.
        """
        tags = item.get("ImageTags") or {}
        if item.get("Id") and tags.get("Primary"):
            image_id, tag = item["Id"], tags["Primary"]
        elif item.get("SeriesId") and item.get("SeriesPrimaryImageTag"):
            image_id, tag = item["SeriesId"], item["SeriesPrimaryImageTag"]
        elif item.get("AlbumId") and item.get("AlbumPrimaryImageTag"):
            image_id, tag = item["AlbumId"], item["AlbumPrimaryImageTag"]
        else:
            return None
        return f"{self.base_url}/emby/Items/{image_id}/Images/Primary?maxHeight=600&tag={tag}"

    async def async_ws_connect(self) -> aiohttp.ClientWebSocketResponse:
        """Open the websocket with session updates."""
        try:
            return await self._session.ws_connect(
                self.ws_url,
                headers=self._headers,
                heartbeat=60,
                timeout=aiohttp.ClientWSTimeout(ws_close=REQUEST_TIMEOUT),
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(str(err) or type(err).__name__) from err


def session_key(session: dict[str, Any]) -> str:
    """Stable id of a client app on a device - the unique_id used by the core integration."""
    return f"{session['DeviceId']}.{session['Client']}"
