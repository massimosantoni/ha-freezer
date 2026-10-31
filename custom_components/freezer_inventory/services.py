"""Service actions (automations, scripts, Assist, Developer tools)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback

from . import schemas
from .const import DOMAIN
from .inventory import InventoryError
from .manager import FreezerManager, async_get_manager, async_user_name, to_service_error

type _Op = Callable[[FreezerManager, str | None, dict[str, Any]], dict[str, Any]]

# service name -> (schema, manager operation, response support)
SERVICES: dict[str, tuple[dict, _Op, SupportsResponse]] = {
    "add_item": (schemas.ADD_ITEM, FreezerManager.op_add_item, SupportsResponse.OPTIONAL),
    "add_piece": (schemas.ADD_PIECE, FreezerManager.op_add_piece, SupportsResponse.OPTIONAL),
    "take_piece": (schemas.TAKE_PIECE, FreezerManager.op_take_piece, SupportsResponse.OPTIONAL),
    "update_item": (schemas.UPDATE_ITEM, FreezerManager.op_update_item, SupportsResponse.OPTIONAL),
    "delete_item": (schemas.DELETE_ITEM, FreezerManager.op_delete_item, SupportsResponse.OPTIONAL),
    "undo_last": (schemas.UNDO_LAST, FreezerManager.op_undo_last, SupportsResponse.OPTIONAL),
    "list_items": (schemas.LIST_ITEMS, FreezerManager.op_list_items, SupportsResponse.ONLY),
}


def _make_handler(op: _Op) -> Callable[[ServiceCall], Any]:
    async def handler(call: ServiceCall) -> ServiceResponse:
        manager = async_get_manager(call.hass)
        user = await async_user_name(call.hass, call.context.user_id)
        try:
            return op(manager, user, dict(call.data))
        except InventoryError as err:
            raise to_service_error(err) from err

    return handler


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    for name, (schema, op, supports_response) in SERVICES.items():
        hass.services.async_register(
            DOMAIN,
            name,
            _make_handler(op),
            schema=vol.Schema(schema),
            supports_response=supports_response,
        )
