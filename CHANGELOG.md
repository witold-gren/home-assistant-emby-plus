# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/).

## [0.1.0] - 2026-10-25

First release: a UI-configured replacement for the core `emby` integration.

### Added
- Config flow: host, port, HTTPS and API key, checked against `/System/Info`. The server
  ID is the unique ID, so the same server cannot be added twice. The form is filled in
  from the core `platform: emby` YAML when present. Includes reconfigure and reauth flows.
- Setup raises `ConfigEntryNotReady` when the server is unreachable, so Home Assistant
  retries it in the background (the core integration gave up until the next restart).
- Websocket with session updates: reconnects after 5, 10, 30, then every 60 s. Answers
  Emby's `ForceKeepAlive`. A lost connection is logged once.
- Media players per Emby client app, with the same attributes as the core integration.
  Posters come from the item's Primary image (else the series' or album's) via
  `/emby/Items/{id}/Images/Primary`, so `entity_picture` works.
- An Emby server device with a *Server* connectivity sensor and an *Active playbacks*
  sensor (attribute `playing`).
- Moving from the core integration: a Repairs issue while `platform: emby` is in YAML.
  Once the block is removed, the core entities are taken over with their entity IDs,
  names, areas, aliases and labels.
- Translations: English and Polish. Brand images.
