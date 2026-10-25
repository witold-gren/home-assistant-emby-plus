# Emby Plus

[Polski](README.pl.md)

Emby players in Home Assistant, configured in the UI, that come back on their own when
the Emby server does. A replacement for the built-in
[Emby integration](https://www.home-assistant.io/integrations/emby) that keeps its
entities.

## Why

The built-in integration works well while the Emby server is on all the time. It fails
when the server is not always on, for example on a NAS with a power schedule:

| Problem in the core `emby` integration | Emby Plus |
| --- | --- |
| YAML only: *"This integration was not set up in the UI"*. | Set up in **Settings → Devices & services**. It can also be reconfigured and re-authenticated there. |
| [pyEmby](https://github.com/mezz64/pyEmby) registers with the server **once**, when Home Assistant starts. If the server is off at that moment, every `media_player.emby_*` stays unavailable until the next restart of Home Assistant. There is no reload action. | When the server is not reachable, the setup raises `ConfigEntryNotReady`. Home Assistant then retries it in the background with growing delays. A websocket that drops later reconnects after 5, 10, 30 and then every 60 s. A lost connection is logged once, not every few seconds. |
| The poster URL has no `/emby` prefix and asks for the *Thumb* image, which items rarely have. The Home Assistant image proxy gets 404, so `entity_picture` is empty. | The item's *Primary* image, else the series' or album's one, at `/emby/Items/{id}/Images/Primary`. It works through the proxy, also outside the home network. |
| No server device and no way to see whether the server is up. | An **Emby server** device with a *Server* connectivity sensor and an *Active playbacks* sensor. The sensor's `playing` attribute shows what plays where. |
| pyEmby opens its own aiohttp session and uses deprecated asyncio APIs. | A small client on Home Assistant's shared session. No extra requirements. |
| The state is written every 1.5 s while playing, only because the position changed. | The position is written only on a seek or pause. Home Assistant extrapolates it in between. |

## Installation

HACS: add this repository as a custom repository (category *Integration*) and install
**Emby Plus**.

Manually: copy `custom_components/emby_plus` to `/config/custom_components/`. With the
Samba share mounted, you can run `scripts/deploy.sh` instead. Restart Home Assistant.

## Setup

1. Create an API key in the Emby dashboard: **Advanced → API Keys**.
2. **Settings → Devices & services → Add integration → Emby Plus**. Enter the host, port
   (8096, or 8920 with HTTPS) and the API key. If `configuration.yaml` still has the core
   `platform: emby` block, the form is filled in from it.

## Moving from the core integration

Both integrations name a player `<DeviceId>.<Client>` (its `unique_id`), so Emby Plus can
take over the existing entities:

1. Add Emby Plus as described above. While `media_player: - platform: emby` is still in
   `configuration.yaml`, **Settings → Repairs** asks you to remove it. Until you do, both
   integrations would show the same players, so Emby Plus does not touch the core entities
   yet.
2. Remove the block and restart Home Assistant.
3. At start, Emby Plus moves every `media_player` entity of the core `emby` integration to
   itself. Each keeps its **entity ID**, name, icon, area, aliases, labels and hidden or
   disabled status. Dashboards and automations keep working.

## Entities

- `media_player.*`: one per Emby client app on a device, e.g. *Emby for LG* on a TV.
  - States: playing, paused or idle. The player is unavailable while the app is closed or
    the server is off.
  - Attributes: title, series, season and episode, album and artist, duration, position,
    poster.
  - Controls: play, pause, stop, next, previous and seek, for apps that allow remote
    control.
  - `app_name` is the Emby user, as in the core integration.
- `binary_sensor.<server>_server`: connected to the server.
- `sensor.<server>_active_playbacks`: number of sessions playing or paused. Its `playing`
  attribute lists `device`, `client` and `title` for each.

## Development

```sh
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests run against Home Assistant 2026.10 (`pytest-homeassistant-custom-component`).
They need no Emby server; the session fixtures in `tests/fixtures/` are synthetic.

## License

Apache 2.0. Emby is a trademark of Emby LLC. This project is not affiliated with Emby.
