"""Media players: state, attributes, poster, commands and sensors."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.media_player import ATTR_MEDIA_SEEK_POSITION, MediaPlayerEntityFeature
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
import pytest

from .conftest import BASE, with_session

TV = "media_player.lg_smart_tv_oled55"
DLNA = "media_player.lg_webos_tv_oled55"


def hub_of(entry):
    return entry.runtime_data


async def push(hass, entry, sessions) -> None:
    hub_of(entry).async_update_sessions(sessions)
    await hass.async_block_till_done()


async def test_playing_episode(hass: HomeAssistant, setup_entry) -> None:
    state = hass.states.get(TV)
    assert state.state == "playing"
    attrs = state.attributes
    assert attrs["media_title"] == "W złym miejscu"
    assert attrs["media_series_title"] == "Lego Ninjago"
    assert (attrs["media_season"], attrs["media_episode"]) == ("2", "19")
    assert attrs["media_content_type"] == "tvshow"
    assert attrs["media_content_id"] == "6809"
    assert attrs["media_duration"] == pytest.approx(1326.24)
    assert attrs["media_position"] == 600
    assert attrs["app_name"] == "Rodzina"
    # the poster goes through the Home Assistant proxy (works outside the home network)
    assert attrs["entity_picture"].startswith(f"/api/media_player_proxy/{TV}")
    assert attrs[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.SEEK


async def test_poster_url(hass: HomeAssistant, setup_entry) -> None:
    entity = hass.data["entity_components"]["media_player"].get_entity(TV)
    assert entity.media_image_url == (
        "http://10.0.0.2:8096/emby/Items/6809/Images/Primary?maxHeight=600&tag=episode-tag"
    )


async def test_idle_session_without_remote_control(hass: HomeAssistant, setup_entry) -> None:
    state = hass.states.get(DLNA)
    assert state.state == "idle"
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == 0


async def test_devices(
    hass: HomeAssistant, setup_entry, device_registry: dr.DeviceRegistry
) -> None:
    server = device_registry.async_get_device_by_identifier(
        ("emby_plus", "a1b2c3d4e5f6"), setup_entry.entry_id
    )
    assert (server.name, server.sw_version) == ("Domowy NAS", "4.9.1.80")
    tv = device_registry.async_get_device_by_identifier(
        ("emby_plus", "tv-0001.Emby for LG"), setup_entry.entry_id
    )
    assert (tv.name, tv.model, tv.via_device_id) == (
        "LG Smart TV (OLED55)",
        "Emby for LG",
        server.id,
    )


async def test_pause_and_end_of_session(hass: HomeAssistant, setup_entry, sessions) -> None:
    paused = with_session(
        sessions, "tv-0001", PlayState={"PositionTicks": 6100000000, "IsPaused": True}
    )
    await push(hass, setup_entry, paused)
    state = hass.states.get(TV)
    assert state.state == "paused"
    assert state.attributes["media_position"] == 610
    stopped = with_session(sessions, "tv-0001", NowPlayingItem=None, PlayState={})
    await push(hass, setup_entry, stopped)
    assert hass.states.get(TV).state == "idle"
    assert "media_title" not in hass.states.get(TV).attributes
    # the TV app closed: the session disappears from the list
    await push(hass, setup_entry, [s for s in sessions if s["DeviceId"] != "tv-0001"])
    assert hass.states.get(TV).state == "unavailable"


async def test_position_is_not_rewritten_every_update(
    hass: HomeAssistant, setup_entry, sessions, freezer
) -> None:
    before = hass.states.get(TV)
    freezer.tick(timedelta(seconds=3))
    # 3 s later Emby reports 3 s more - Home Assistant extrapolates that itself
    await push(
        hass,
        setup_entry,
        with_session(
            sessions, "tv-0001", PlayState={"PositionTicks": 6030000000, "IsPaused": False}
        ),
    )
    assert hass.states.get(TV).last_updated == before.last_updated
    # a seek is written
    freezer.tick(timedelta(seconds=1))
    await push(
        hass,
        setup_entry,
        with_session(
            sessions, "tv-0001", PlayState={"PositionTicks": 12000000000, "IsPaused": False}
        ),
    )
    state = hass.states.get(TV)
    assert state.attributes["media_position"] == 1200
    assert state.attributes["media_position_updated_at"] == dt_util.utcnow()


async def test_new_session_adds_player(hass: HomeAssistant, setup_entry, sessions) -> None:
    phone = {
        "Id": "sess-phone",
        "DeviceId": "phone-1",
        "DeviceName": "iPhone",
        "Client": "Emby for iOS",
        "SupportsRemoteControl": True,
        "PlayState": {},
    }
    await push(hass, setup_entry, [*sessions, phone])
    assert hass.states.get("media_player.iphone").state == "idle"


async def test_lost_server_makes_players_unavailable(hass: HomeAssistant, setup_entry) -> None:
    hub = hub_of(setup_entry)
    hub._set_connected(False)
    await hass.async_block_till_done()
    assert hass.states.get(TV).state == "unavailable"
    assert hass.states.get("binary_sensor.domowy_nas_server").state == "off"
    assert hass.states.get("sensor.domowy_nas_active_playbacks").state == "unavailable"
    hub._set_connected(True)
    await hass.async_block_till_done()
    assert hass.states.get(TV).state == "playing"


@pytest.mark.parametrize(
    ("service", "data", "command", "query"),
    [
        ("media_pause", {}, "Pause", {}),
        ("media_play", {}, "Unpause", {}),
        ("media_stop", {}, "Stop", {}),
        ("media_next_track", {}, "NextTrack", {}),
        ("media_previous_track", {}, "PreviousTrack", {}),
        ("media_seek", {ATTR_MEDIA_SEEK_POSITION: 30}, "Seek", {"SeekPositionTicks": "300000000"}),
    ],
)
async def test_commands(
    hass: HomeAssistant, setup_entry, aioclient_mock, service, data, command, query
) -> None:
    url = f"{BASE}/Sessions/sess-tv/Playing/{command}"
    aioclient_mock.post(url, status=204)
    await hass.services.async_call(
        "media_player", service, {ATTR_ENTITY_ID: TV, **data}, blocking=True
    )
    call = next(c for c in aioclient_mock.mock_calls if c[0] == "POST")
    assert str(call[1]).startswith(url)
    assert dict(call[1].query) == query


async def test_command_error(hass: HomeAssistant, setup_entry, aioclient_mock) -> None:
    aioclient_mock.post(f"{BASE}/Sessions/sess-tv/Playing/Pause", status=500)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player", "media_pause", {ATTR_ENTITY_ID: TV}, blocking=True
        )


async def test_active_playbacks_sensor(hass: HomeAssistant, setup_entry, sessions) -> None:
    state = hass.states.get("sensor.domowy_nas_active_playbacks")
    assert state.state == "1"
    assert state.attributes["playing"] == [
        {"device": "LG Smart TV (OLED55)", "client": "Emby for LG", "title": "W złym miejscu"}
    ]
    await push(hass, setup_entry, with_session(sessions, "tv-0001", NowPlayingItem=None))
    assert hass.states.get("sensor.domowy_nas_active_playbacks").state == "0"
