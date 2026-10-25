"""Emby client apps (sessions) as media players."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EmbyConfigEntry
from .api import CannotConnect
from .const import DOMAIN, MANUFACTURER, POSITION_TOLERANCE, TICKS_PER_SECOND
from .entity import EmbyEntity
from .hub import EmbyHub

_LOGGER = logging.getLogger(__name__)

# Emby item type -> media content type (as in the core integration)
CONTENT_TYPES: dict[str, str] = {
    "Episode": MediaType.TVSHOW,
    "Movie": MediaType.MOVIE,
    "Trailer": "trailer",
    "Music": MediaType.MUSIC,
    "Audio": MediaType.MUSIC,
    "Video": MediaType.VIDEO,
    "TvChannel": MediaType.CHANNEL,
}

REMOTE_FEATURES = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SEEK
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EmbyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a player for every session, now and when new ones appear."""
    hub = entry.runtime_data

    @callback
    def add(keys: list[str]) -> None:
        async_add_entities(EmbyMediaPlayer(hub, key) for key in keys)

    add(list(hub.sessions))
    entry.async_on_unload(hub.async_add_new_session_listener(add))


def _seconds(ticks: Any) -> float | None:
    return int(ticks) / TICKS_PER_SECOND if ticks is not None else None


class EmbyMediaPlayer(EmbyEntity, MediaPlayerEntity):
    """One client app on a device, e.g. Emby for LG on the living room TV."""

    _attr_name = None
    # the server URL is local - Home Assistant fetches the poster and serves it itself
    _attr_media_image_remotely_accessible = False

    def __init__(self, hub: EmbyHub, key: str) -> None:
        super().__init__(hub)
        self.key = key
        self._attr_unique_id = key
        session = hub.sessions[key]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, key)},
            name=session.get("DeviceName") or key,
            manufacturer=MANUFACTURER,
            model=session.get("Client"),
            sw_version=session.get("ApplicationVersion"),
            via_device_id=hub.server_device_id,
        )
        self._position: float | None = None
        self._position_at: datetime | None = None
        self._snapshot: tuple | None = None
        self._update_position()

    @property
    def _session(self) -> dict[str, Any]:
        return self.hub.sessions[self.key]

    @property
    def _item(self) -> dict[str, Any]:
        return self._session.get("NowPlayingItem") or {}

    @property
    def available(self) -> bool:
        """A player exists while its session is active and the server connected."""
        return self.hub.connected and self.key in self.hub.active

    @property
    def state(self) -> MediaPlayerState | None:
        """Playing, paused or idle."""
        if not self._item:
            return MediaPlayerState.IDLE
        if (self._session.get("PlayState") or {}).get("IsPaused"):
            return MediaPlayerState.PAUSED
        return MediaPlayerState.PLAYING

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Remote control only for apps that allow it (not e.g. a DLNA renderer list)."""
        if self._session.get("SupportsRemoteControl"):
            return REMOTE_FEATURES
        return MediaPlayerEntityFeature(0)

    @property
    def app_name(self) -> str | None:
        """The Emby user (as in the core integration)."""
        return self._session.get("UserName")

    @property
    def media_content_id(self) -> str | None:
        """Emby item id."""
        return self._item.get("Id")

    @property
    def media_content_type(self) -> str | None:
        """Movie, tvshow, music..."""
        return CONTENT_TYPES.get(self._item.get("Type", ""))

    @property
    def media_title(self) -> str | None:
        """Title of the item."""
        return self._item.get("Name")

    @property
    def media_series_title(self) -> str | None:
        """Series of an episode."""
        return self._item.get("SeriesName")

    @property
    def media_season(self) -> str | None:
        """Season of an episode."""
        season = self._item.get("ParentIndexNumber")
        return str(season) if season is not None else None

    @property
    def media_episode(self) -> str | None:
        """Episode number."""
        episode = self._item.get("IndexNumber")
        return str(episode) if episode is not None else None

    @property
    def media_album_name(self) -> str | None:
        """Album of a track."""
        return self._item.get("Album")

    @property
    def media_artist(self) -> str | None:
        """First artist of a track."""
        artists = self._item.get("Artists") or []
        return artists[0] if artists else None

    @property
    def media_album_artist(self) -> str | None:
        """Album artist of a track."""
        return self._item.get("AlbumArtist")

    @property
    def media_duration(self) -> float | None:
        """Runtime in seconds."""
        return _seconds(self._item.get("RunTimeTicks"))

    @property
    def media_position(self) -> float | None:
        """Position in seconds, valid at media_position_updated_at."""
        return self._position

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When the position was read."""
        return self._position_at

    @property
    def media_image_url(self) -> str | None:
        """Poster of the item (or of its series / album)."""
        return self.hub.client.image_url(self._item) if self._item else None

    def _update_position(self) -> None:
        if not self.available or not self._item:
            self._position = self._position_at = None
            return
        position = _seconds((self._session.get("PlayState") or {}).get("PositionTicks"))
        if position is None:
            self._position = self._position_at = None
            return
        now = dt_util.utcnow()
        expected = self._position
        if expected is not None and self._position_at and self.state == MediaPlayerState.PLAYING:
            expected += (now - self._position_at).total_seconds()
        # Emby sends the position every 1.5 s; Home Assistant extrapolates it itself,
        # so only a seek or pause (a jump from the expected position) is written
        if expected is None or abs(position - expected) > POSITION_TOLERANCE:
            self._position, self._position_at = position, now

    def _handle_hub_update(self) -> None:
        old_state = self.state if self._snapshot else None
        self._update_position()
        if self.state != old_state and self.state == MediaPlayerState.PAUSED:
            # paused: keep the exact position, the extrapolation stops here
            position = _seconds((self._session.get("PlayState") or {}).get("PositionTicks"))
            if position is not None:
                self._position, self._position_at = position, dt_util.utcnow()
        snapshot = (
            self.available,
            self.state,
            self.media_content_id,
            self.media_title,
            self.supported_features,
            self._position_at,
        )
        if snapshot != self._snapshot:
            self._snapshot = snapshot
            self.async_write_ha_state()

    async def _command(self, command: str, position: float | None = None) -> None:
        try:
            await self.hub.client.async_send_playstate(self._session["Id"], command, position)
        except CannotConnect as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"command": command, "error": str(err)},
            ) from err

    async def async_media_play(self) -> None:
        """Resume."""
        await self._command("Unpause")

    async def async_media_pause(self) -> None:
        """Pause."""
        await self._command("Pause")

    async def async_media_stop(self) -> None:
        """Stop."""
        await self._command("Stop")

    async def async_media_next_track(self) -> None:
        """Next item."""
        await self._command("NextTrack")

    async def async_media_previous_track(self) -> None:
        """Previous item."""
        await self._command("PreviousTrack")

    async def async_media_seek(self, position: float) -> None:
        """Jump to a position in seconds."""
        await self._command("Seek", position)
