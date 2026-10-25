"""EmbyClient: requests, errors and poster URLs."""

from __future__ import annotations

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.emby_plus.api import CannotConnect, EmbyClient, InvalidAuth, session_key

from .conftest import BASE


@pytest.fixture
async def client(hass, aioclient_mock) -> EmbyClient:
    return EmbyClient(async_get_clientsession(hass), "10.0.0.2", 8096, False, "secret", "dev-1")


async def test_server_info_sends_the_api_key(client, aioclient_mock, server_info) -> None:
    aioclient_mock.get(f"{BASE}/System/Info", json=server_info)
    assert (await client.async_get_server_info())["ServerName"] == "Domowy NAS"
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["X-Emby-Token"] == "secret"
    assert 'DeviceId="dev-1"' in headers["X-Emby-Authorization"]


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_key_is_invalid_auth(client, aioclient_mock, status) -> None:
    aioclient_mock.get(f"{BASE}/System/Info", status=status)
    with pytest.raises(InvalidAuth):
        await client.async_get_server_info()


@pytest.mark.parametrize(
    "kwargs",
    [{"status": 500}, {"exc": aiohttp.ClientConnectionError()}, {"exc": TimeoutError()}],
)
async def test_unreachable_server_is_cannot_connect(client, aioclient_mock, kwargs) -> None:
    aioclient_mock.get(f"{BASE}/Sessions", **kwargs)
    with pytest.raises(CannotConnect):
        await client.async_get_sessions()


async def test_unexpected_answers_are_cannot_connect(client, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/System/Info", json={"something": "else"})
    aioclient_mock.get(f"{BASE}/Sessions", json={"not": "a list"})
    with pytest.raises(CannotConnect):
        await client.async_get_server_info()
    with pytest.raises(CannotConnect):
        await client.async_get_sessions()


async def test_playstate_posts_with_seek_ticks(client, aioclient_mock) -> None:
    aioclient_mock.post(f"{BASE}/Sessions/s1/Playing/Seek", status=204)
    await client.async_send_playstate("s1", "Seek", 90.5)
    method, url, body, _ = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert url.query["SeekPositionTicks"] == "905000000"
    # Emby waits for a body of a POST - an empty JSON is sent
    assert body == {}


async def test_image_url_prefers_item_then_series_then_album(client) -> None:
    base = "http://10.0.0.2:8096/emby/Items"
    assert client.image_url({"Id": "1", "ImageTags": {"Primary": "t1"}}) == (
        f"{base}/1/Images/Primary?maxHeight=600&tag=t1"
    )
    assert (
        client.image_url(
            {"Id": "1", "ImageTags": {}, "SeriesId": "2", "SeriesPrimaryImageTag": "t2"}
        )
        == f"{base}/2/Images/Primary?maxHeight=600&tag=t2"
    )
    assert client.image_url({"Id": "1", "AlbumId": "3", "AlbumPrimaryImageTag": "t3"}) == (
        f"{base}/3/Images/Primary?maxHeight=600&tag=t3"
    )
    assert client.image_url({"Id": "1", "ImageTags": {"Thumb": "x"}}) is None


async def test_urls_with_ssl(hass) -> None:
    client = EmbyClient(async_get_clientsession(hass), "nas", 8920, True, "k y", "d")
    assert client.base_url == "https://nas:8920"
    assert client.ws_url == "wss://nas:8920?api_key=k%20y&deviceId=d"


def test_session_key_matches_core_unique_id() -> None:
    assert session_key({"DeviceId": "tv-1", "Client": "Emby for LG"}) == "tv-1.Emby for LG"


async def test_ws_connect_errors_are_cannot_connect(client, aioclient_mock) -> None:
    async def refuse(*args, **kwargs):
        raise aiohttp.ClientConnectionError("refused")

    client._session.ws_connect = refuse
    with pytest.raises(CannotConnect):
        await client.async_ws_connect()


async def test_ws_connect_uses_key_and_device(client) -> None:
    calls = []

    async def connect(url, **kwargs):
        calls.append((url, kwargs))
        return "ws"

    client._session.ws_connect = connect
    assert await client.async_ws_connect() == "ws"
    url, kwargs = calls[0]
    assert url == "ws://10.0.0.2:8096?api_key=secret&deviceId=dev-1"
    assert kwargs["headers"]["X-Emby-Token"] == "secret"
