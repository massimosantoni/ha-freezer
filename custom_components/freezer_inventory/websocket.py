"""Websocket API used by the Lovelace card.

* ``freezer_inventory/subscribe`` — sends the full snapshot immediately and
  after every change (all clients stay in sync).
* ``freezer_inventory/<operation>`` — same payloads as the services; errors
  are returned with the stable InventoryError code so the card can translate.

Commands are available to every authenticated user (no admin required): the
whole family must be able to add and take items.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_UPDATED
from .inventory import InventoryError
from .manager import async_get_manager
from .services import SERVICES

ERR_NOT_LOADED = "not_loaded"


@callback
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    @callback
    def forward() -> None:
        try:
            manager = async_get_manager(hass)
        except ServiceValidationError:
            return  # entry unloaded/reloading: the next signal will refresh
        connection.send_message(websocket_api.event_message(msg["id"], manager.snapshot()))

    try:
        async_get_manager(hass)
    except ServiceValidationError:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "Freezer Inventory is not loaded")
        return

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED, forward)
    connection.send_result(msg["id"])
    forward()


def _make_command(name: str, schema: dict, op) -> Any:
    @callback
    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/{name}", **schema})
    def handler(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
        try:
            manager = async_get_manager(hass)
        except ServiceValidationError:
            connection.send_error(msg["id"], ERR_NOT_LOADED, "Freezer Inventory is not loaded")
            return
        data = {k: v for k, v in msg.items() if k not in ("id", "type")}
        try:
            result = op(manager, connection.user.name, data)
        except InventoryError as err:
            connection.send_error(msg["id"], err.code, str(err), translation_placeholders=err.placeholders)
            return
        connection.send_result(msg["id"], result)

    return handler


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_subscribe)
    for name, (schema, op, _resp) in SERVICES.items():
        websocket_api.async_register_command(hass, _make_command(name, schema, op))
