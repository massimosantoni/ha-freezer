"""Freezer Inventory: track what is in the freezer, piece by piece."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import CARD_URL, DOMAIN, STORAGE_VERSION
from .inventory import Inventory, InventoryError
from .manager import FreezerManager
from .services import async_setup_services
from .websocket import async_setup_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_FILE = Path(__file__).parent / "frontend" / "freezer-inventory-card.js"

type FreezerConfigEntry = ConfigEntry[FreezerManager]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services, websocket commands and the card (once, not per entry)."""
    async_setup_services(hass)
    async_setup_websocket(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
    )
    # ?v= busts the browser/companion-app cache after an update
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")


async def async_setup_entry(hass: HomeAssistant, entry: FreezerConfigEntry) -> bool:
    store = _store(hass, entry)
    data = await store.async_load()
    try:
        inventory = Inventory(data, now=dt_util.now, new_id=ulid_now)
    except (InventoryError, KeyError, TypeError, ValueError) as err:
        # Never start with an empty inventory over a file we failed to read:
        # the next save would overwrite it. The file stays untouched in .storage.
        raise ConfigEntryError(f"Cannot read {store.path}: {err}") from err
    entry.runtime_data = FreezerManager(hass, store, inventory)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FreezerConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_flush()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await _store(hass, entry).async_remove()
