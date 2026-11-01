"""Summary sensors: total pieces and pieces per category.

The item list itself is *not* exposed as attributes (recorder 16 KB limit and
DB noise): the card reads it through the websocket API.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreezerConfigEntry
from .const import CATEGORIES, DOMAIN, SIGNAL_UPDATED
from .manager import FreezerManager

PARALLEL_UPDATES = 0
TOTAL = "total"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreezerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities(FreezerSensor(entry, manager, key) for key in (TOTAL, *CATEGORIES))


class FreezerSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "pz"
    _unrecorded_attributes = frozenset({"oldest_added_at"})

    def __init__(self, entry: FreezerConfigEntry, manager: FreezerManager, key: str) -> None:
        self._manager = manager
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="ha-freezer",
        )
        self._update_from_inventory()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self._update_from_inventory()
        self.async_write_ha_state()

    @callback
    def _update_from_inventory(self) -> None:
        summary = self._manager.inventory.summary()
        attrs: dict[str, Any]
        if self._key == TOTAL:
            self._attr_native_value = summary["total_pieces"]
            attrs = {
                "items": summary["total_items"],
                "total_weight_g": summary["total_weight_g"],
                "total_portions": summary["total_portions"],
                "oldest_added_at": summary["oldest_added_at"],
            }
        else:
            cat = summary["by_category"][self._key]
            self._attr_native_value = cat["pieces"]
            attrs = {"items": cat["items"]}
        self._attr_extra_state_attributes = attrs
