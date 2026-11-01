"""Bridge between Home Assistant and the pure Inventory.

The manager owns the Store, runs operations on the Inventory, schedules the
save and notifies listeners (sensors, websocket subscribers). Services and
websocket commands both go through the same ``op_*`` methods, so they return
exactly the same payloads.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CATEGORIES, DOMAIN, SAVE_DELAY_S, SIGNAL_UPDATED, SORT_DATE
from .inventory import UNSET, Inventory, InventoryError


class FreezerManager:
    """Per-config-entry runtime object (``entry.runtime_data``)."""

    def __init__(self, hass: HomeAssistant, store: Store[dict[str, Any]], inventory: Inventory) -> None:
        self.hass = hass
        self.store = store
        self.inventory = inventory

    # ----- plumbing -------------------------------------------------------- #
    @callback
    def _changed(self) -> None:
        self.store.async_delay_save(self.inventory.to_dict, SAVE_DELAY_S)
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    async def async_flush(self) -> None:
        await self.store.async_save(self.inventory.to_dict())

    @callback
    def snapshot(self) -> dict[str, Any]:
        """Full state pushed to the card (small: < 200 items expected)."""
        return {
            "items": [i.to_view() for i in self.inventory.list_items(sort=SORT_DATE)],
            "can_undo": self.inventory.can_undo(),
            "categories": list(CATEGORIES),
        }

    # ----- operations (raise InventoryError) -------------------------------- #
    @callback
    def op_add_item(self, user: str | None, data: dict[str, Any]) -> dict[str, Any]:
        item = self.inventory.add_item(
            data["name"],
            data["category"],
            quantity=data.get("quantity"),
            weights=data.get("weights"),
            note=data.get("note"),
            user=user,
        )
        self._changed()
        return {"item": item.to_view()}

    @callback
    def op_add_piece(self, user: str | None, data: dict[str, Any]) -> dict[str, Any]:
        piece = self.inventory.add_piece(
            data["item_id"],
            data.get("weight_g"),
            portions=data.get("portions"),
            amount=data.get("amount"),
            user=user,
        )
        self._changed()
        return {"item": self.inventory.get_item(data["item_id"]).to_view(), "piece": piece.to_dict()}

    @callback
    def op_take_piece(self, user: str | None, data: dict[str, Any]) -> dict[str, Any]:
        result = self.inventory.take_piece(data["item_id"], data.get("piece_id"), user=user)
        self._changed()
        return {
            "piece": result.piece.to_dict(),
            "item": result.item.to_view() if result.item else None,
            "item_deleted": result.item_deleted,
        }

    @callback
    def op_update_item(self, user: str | None, data: dict[str, Any]) -> dict[str, Any]:
        pieces = data.get("pieces", UNSET)
        if pieces is not UNSET:
            pieces = [_localize_piece(p) for p in pieces]
        item = self.inventory.update_item(
            data["item_id"],
            name=data.get("name", UNSET),
            category=data.get("category", UNSET),
            note=data.get("note", UNSET),
            pieces=pieces,
            user=user,
        )
        self._changed()
        return {"item": item.to_view()}

    @callback
    def op_delete_item(self, user: str | None, data: dict[str, Any]) -> dict[str, Any]:
        item = self.inventory.delete_item(data["item_id"], user=user)
        self._changed()
        return {"item": item.to_view()}

    @callback
    def op_undo_last(self, user: str | None, data: dict[str, Any]) -> dict[str, Any]:
        entry = self.inventory.undo_last(user=user)
        self._changed()
        return {"action": entry.action, "item_id": entry.item_id, "item_name": entry.item_name}

    @callback
    def op_list_items(self, user: str | None, data: dict[str, Any]) -> dict[str, Any]:
        items = self.inventory.list_items(
            sort=data.get("sort", SORT_DATE),
            category=data.get("category"),
            descending=data.get("descending", False),
        )
        return {"items": [i.to_view() for i in items]}


def _localize_piece(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept naive or date-only ``added_at`` from the UI and make it aware (local tz)."""
    added_at = raw.get("added_at")
    if not added_at or isinstance(added_at, datetime):
        return raw
    text = str(added_at).strip()
    # date-only ("2026-06-15") → midday, so a timezone shift never changes the day
    day = dt_util.parse_date(text) if len(text) == 10 else None
    parsed = datetime.combine(day, time(12, 0)) if day else dt_util.parse_datetime(text)
    if parsed is None:
        raise InventoryError("invalid_date", f"Invalid date {added_at!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return {**raw, "added_at": parsed}


def to_service_error(err: InventoryError) -> ServiceValidationError:
    return ServiceValidationError(
        str(err),
        translation_domain=DOMAIN,
        translation_key=err.code,
        translation_placeholders=err.placeholders,
    )


@callback
def async_get_manager(hass: HomeAssistant) -> FreezerManager:
    """Return the manager of the (single) loaded entry."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            "Freezer Inventory is not loaded",
            translation_domain=DOMAIN,
            translation_key="not_loaded",
        )
    return entries[0].runtime_data


async def async_user_name(hass: HomeAssistant, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = await hass.auth.async_get_user(user_id)
    return user.name if user else None
