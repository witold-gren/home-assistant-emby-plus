"""Constants for Emby Plus."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "emby_plus"
MANUFACTURER: Final = "Emby"

DEFAULT_PORT: Final = 8096
DEFAULT_SSL_PORT: Final = 8920
REQUEST_TIMEOUT: Final = 10

# Emby positions and runtimes are in ticks of 100 ns
TICKS_PER_SECOND: Final = 10_000_000

# Websocket: session updates every 1.5 s, reconnect with growing delays (seconds)
SESSIONS_INTERVAL_MS: Final = 1500
KEEPALIVE_INTERVAL: Final = 30
RECONNECT_DELAYS: Final = (5, 10, 30, 60)

# The core integration this one replaces - its YAML block and registry entries
CORE_DOMAIN: Final = "emby"
ISSUE_YAML_PLATFORM: Final = "yaml_emby_platform"

# A position that drifts more than this from the extrapolated one is written to the state
POSITION_TOLERANCE: Final = 5
