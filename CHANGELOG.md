# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/).

## [0.1.1] - 2026-10-25

### Changed
- Entity ids are English in every Home Assistant language (`sensor.<server>_active_playbacks`
  instead of `sensor.<serwer>_aktywne_odtwarzania` in a Polish installation); displayed names
  stay translated.
- A server that is off is a normal state, not a setup error. The entry loads, the *Server*
  sensor is off and the websocket loop connects as soon as the server answers. Before,
  the entry showed a red "retrying setup" error for as long as the server (e.g. a NAS
  that runs one hour a day) was off.
- Known players are restored from the device registry, so they are plainly unavailable
  while the server is off or their app is closed, instead of "no longer provided".
- A lost connection is logged at info level, not as a warning.

### Fixed
- The server's version is kept in the device registry while the server is off, and
  updated when it comes back with a newer Emby.
- An API key rejected while reconnecting starts the reauth flow once, instead of
  logging an unexpected error every minute.

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
