"""Entity ids in English, whatever the Home Assistant language.

Home Assistant builds the object id of a new entity from its translated name, so a Polish
installation gets e.g. ``sensor.vector_bateria``. Entities of this integration suggest their
English name instead (``sensor.vector_battery``); the displayed name stays translated and
Home Assistant still puts the device name in front.
"""

from __future__ import annotations

import json
from pathlib import Path

# English names of entities without a translation key (named after their device class)
DEVICE_CLASS_NAMES = {
    "battery": "Battery",
    "battery_charging": "Charging",
    "connectivity": "Connectivity",
    "motion": "Motion",
    "restart": "Restart",
}


def _english_names() -> dict[str, str]:
    """``platform.translation_key`` -> English name, from translations/en.json (read once,
    when Home Assistant imports the integration - outside the event loop)."""
    path = Path(__file__).parent / "translations" / "en.json"
    entities = json.loads(path.read_text(encoding="utf-8")).get("entity", {})
    return {
        f"{platform}.{key}": item["name"]
        for platform, items in entities.items()
        for key, item in items.items()
        if "name" in item
    }


ENGLISH_NAMES = _english_names()


def english_object_id(
    platform: str, translation_key: str | None, device_class: str | None, name: str | None
) -> str | None:
    """English name for the entity id; ``name`` is what Home Assistant would use (None =
    the entity is named after the device and gets no suffix)."""
    if name is None:
        return None
    if translation_key:
        return ENGLISH_NAMES.get(f"{platform}.{translation_key}", name)
    return DEVICE_CLASS_NAMES.get(device_class or "", name)
