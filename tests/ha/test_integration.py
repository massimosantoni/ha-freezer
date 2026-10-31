"""Integration tests against a real Home Assistant core."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.freezer_inventory import CARD_FILE
from custom_components.freezer_inventory.const import CARD_URL, DOMAIN
from homeassistant import config_entries
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

STORAGE_KEY = f"{DOMAIN}.{{entry_id}}"


async def call(hass: HomeAssistant, service: str, context: Context | None = None, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True, context=context
    )


def total_sensor(hass: HomeAssistant, entry: MockConfigEntry):
    ent_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_total")
    return hass.states.get(ent_id)


def category_sensor(hass: HomeAssistant, entry: MockConfigEntry, cat: str):
    ent_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{cat}")
    return hass.states.get(ent_id)


# --------------------------------------------------------------------------- #
# config flow
# --------------------------------------------------------------------------- #


async def test_config_flow_single_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": " Freezer piano terra "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Freezer piano terra"
    await hass.async_block_till_done()

    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "single_instance_allowed"


# --------------------------------------------------------------------------- #
# setup, sensors, card
# --------------------------------------------------------------------------- #


async def test_setup_creates_sensors_and_card(hass: HomeAssistant, loaded_entry, hass_client) -> None:
    assert loaded_entry.state is ConfigEntryState.LOADED
    state = total_sensor(hass, loaded_entry)
    assert state.state == "0"
    assert state.attributes["unit_of_measurement"] == "pz"
    for cat in ("carne", "verdura", "frutta", "altro"):
        assert category_sensor(hass, loaded_entry, cat).state == "0"

    version = json.loads((CARD_FILE.parents[1] / "manifest.json").read_text())["version"]
    assert f"{CARD_URL}?v={version}" in hass.data[DATA_EXTRA_MODULE_URL].urls
    client = await hass_client()
    resp = await client.get(CARD_URL)
    assert resp.status == 200
    assert "freezer-inventory-card" in await resp.text()


# --------------------------------------------------------------------------- #
# services
# --------------------------------------------------------------------------- #


async def test_add_take_undo_via_services(hass: HomeAssistant, loaded_entry, hass_admin_user) -> None:
    ctx = Context(user_id=hass_admin_user.id)
    res = await call(
        hass, "add_item", ctx, name="Bistecche di manzo", category="carne", weights="200 300 0,5kg"
    )
    item = res["item"]
    assert item["quantity"] == 3
    assert item["total_weight_g"] == 1000
    assert item["created_by"] == hass_admin_user.name
    await hass.async_block_till_done()

    state = total_sensor(hass, loaded_entry)
    assert state.state == "3"
    assert state.attributes["items"] == 1
    assert state.attributes["total_weight_g"] == 1000
    assert category_sensor(hass, loaded_entry, "carne").state == "3"

    p300 = item["pieces"][1]["id"]
    res = await call(hass, "take_piece", item_id=item["id"], piece_id=p300)
    assert res["piece"]["weight_g"] == 300
    assert res["item"]["quantity"] == 2
    assert not res["item_deleted"]

    res = await call(hass, "take_piece", item_id=item["id"])  # oldest = first inserted (200 g)
    assert res["piece"]["weight_g"] == 200

    res = await call(hass, "undo_last")
    assert res == {"action": "take_piece", "item_id": item["id"], "item_name": "Bistecche di manzo"}
    await hass.async_block_till_done()
    assert total_sensor(hass, loaded_entry).state == "2"

    res = await call(hass, "add_piece", item_id=item["id"], weight_g=250)
    assert res["item"]["quantity"] == 3
    assert res["piece"]["weight_g"] == 250


async def test_no_merge_and_list_items(hass: HomeAssistant, loaded_entry) -> None:
    await call(hass, "add_item", name="Ragù", category="altro")
    await call(hass, "add_item", name="Ragù", category="altro", quantity=2)
    await call(hass, "add_item", name="Arista", category="carne")
    res = await call(hass, "list_items")
    assert [i["name"] for i in res["items"]] == ["Ragù", "Ragù", "Arista"]
    res = await call(hass, "list_items", sort="category")
    assert [i["name"] for i in res["items"]] == ["Arista", "Ragù", "Ragù"]
    res = await call(hass, "list_items", category="carne")
    assert [i["name"] for i in res["items"]] == ["Arista"]


async def test_last_piece_deletes_item(hass: HomeAssistant, loaded_entry) -> None:
    item = (await call(hass, "add_item", name="Gelato", category="altro"))["item"]
    res = await call(hass, "take_piece", item_id=item["id"])
    assert res["item_deleted"] and res["item"] is None
    assert (await call(hass, "list_items"))["items"] == []


async def test_update_item_localizes_dates(hass: HomeAssistant, loaded_entry) -> None:
    item = (await call(hass, "add_item", name="Fragole", category="verdura", weights=[200]))["item"]
    pid = item["pieces"][0]["id"]
    res = await call(
        hass,
        "update_item",
        item_id=item["id"],
        category="frutta",
        note="dal giardino",
        pieces=[{"id": pid, "weight_g": 220}, {"weight_g": 180, "added_at": "2026-06-15"}],
    )
    upd = res["item"]
    assert upd["category"] == "frutta"
    assert upd["note"] == "dal giardino"
    # date-only input → 12:00 local time, and it becomes the oldest piece
    first = dt_util.parse_datetime(upd["pieces"][0]["added_at"])
    assert first.tzinfo is not None
    assert (first.year, first.month, first.day, first.hour) == (2026, 6, 15, 12)
    assert [p["weight_g"] for p in upd["pieces"]] == [180, 220]


@pytest.mark.parametrize(
    ("service", "data", "key"),
    [
        ("add_item", {"name": "Bistecche", "category": "carne", "weights": "due etti"}, "invalid_weight"),
        ("add_item", {"name": "x", "category": "carne"}, "invalid_name"),
        ("add_item", {"name": "Spada", "category": "pesce"}, "invalid_category"),
        (
            "add_item",
            {"name": "Bistecche", "category": "carne", "weights": [1, 2], "quantity": 3},
            "quantity_weights_mismatch",
        ),
        ("take_piece", {"item_id": "nope"}, "item_not_found"),
        ("undo_last", {}, "nothing_to_undo"),
        ("update_item", {"item_id": "nope", "name": "Nuovo"}, "item_not_found"),
    ],
)
async def test_errors_are_translated(hass: HomeAssistant, loaded_entry, service, data, key) -> None:
    with pytest.raises(ServiceValidationError) as exc:
        await call(hass, service, **data)
    assert exc.value.translation_domain == DOMAIN
    assert exc.value.translation_key == key
    # the translated message is rendered (no raw key, no missing placeholder)
    assert str(exc.value) and key not in str(exc.value)


# --------------------------------------------------------------------------- #
# websocket
# --------------------------------------------------------------------------- #


async def test_websocket_subscribe_and_commands(hass: HomeAssistant, loaded_entry, hass_ws_client) -> None:
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/subscribe"})
    msg = await ws.receive_json()
    assert msg["success"]
    msg = await ws.receive_json()
    assert msg["type"] == "event"
    assert msg["event"] == {
        "items": [],
        "can_undo": False,
        "categories": ["carne", "verdura", "frutta", "altro"],
    }

    await ws.send_json(
        {"id": 2, "type": f"{DOMAIN}/add_item", "name": "Piselli", "category": "verdura", "quantity": 4}
    )
    # the push event and the command result can arrive in either order
    got = {}
    for _ in range(2):
        m = await ws.receive_json()
        got[m["type"]] = m
    assert got["result"]["success"]
    item = got["result"]["result"]["item"]
    assert item["quantity"] == 4
    assert got["event"]["event"]["items"][0]["id"] == item["id"]
    assert got["event"]["event"]["can_undo"] is True

    await ws.send_json({"id": 3, "type": f"{DOMAIN}/take_piece", "item_id": "missing"})
    m = await ws.receive_json()
    assert not m["success"]
    assert m["error"]["code"] == "item_not_found"

    await ws.send_json({"id": 4, "type": f"{DOMAIN}/add_item", "name": "Pane", "category": "pane"})
    m = await ws.receive_json()
    assert m["error"]["code"] == "invalid_category"


async def test_websocket_non_admin_user_can_write(
    hass: HomeAssistant, loaded_entry, hass_ws_client, hass_read_only_access_token
) -> None:
    """Family members are not admins: the card must work for them."""
    ws = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/add_item", "name": "Piselli", "category": "verdura"})
    m = await ws.receive_json()
    assert m["success"], m
    assert m["result"]["item"]["created_by"]


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #


async def test_changes_are_saved(hass: HomeAssistant, loaded_entry, hass_storage) -> None:
    await call(hass, "add_item", name="Bistecche", category="carne", weights=[300])
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    stored = hass_storage[STORAGE_KEY.format(entry_id=loaded_entry.entry_id)]
    items = list(stored["data"]["items"].values())
    assert items[0]["name"] == "Bistecche"
    assert items[0]["pieces"][0]["weight_g"] == 300


async def test_unload_flushes_and_reload_restores(hass: HomeAssistant, loaded_entry, hass_storage) -> None:
    await call(hass, "add_item", name="Arista", category="carne", quantity=2)
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert hass_storage[STORAGE_KEY.format(entry_id=loaded_entry.entry_id)]["data"]["items"]

    assert await hass.config_entries.async_setup(loaded_entry.entry_id)
    await hass.async_block_till_done()
    res = await call(hass, "list_items")
    assert [(i["name"], i["quantity"]) for i in res["items"]] == [("Arista", 2)]
    assert total_sensor(hass, loaded_entry).state == "2"


async def test_service_when_not_loaded(hass: HomeAssistant, loaded_entry) -> None:
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    with pytest.raises(ServiceValidationError) as exc:
        await call(hass, "list_items")
    assert exc.value.translation_key == "not_loaded"


async def test_corrupt_storage_does_not_wipe(hass: HomeAssistant, config_entry, hass_storage) -> None:
    key = STORAGE_KEY.format(entry_id=config_entry.entry_id)
    bad = {"version": 1, "items": {"x": {"id": "x", "name": "", "category": "boh"}}, "log": []}
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": bad}
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert hass_storage[key]["data"] == bad


async def test_remove_entry_deletes_storage(hass: HomeAssistant, loaded_entry, hass_storage) -> None:
    await call(hass, "add_item", name="Arista", category="carne")
    key = STORAGE_KEY.format(entry_id=loaded_entry.entry_id)
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert key in hass_storage
    await hass.config_entries.async_remove(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_service_descriptions_load(hass: HomeAssistant, loaded_entry) -> None:
    from homeassistant.helpers.service import async_get_all_descriptions

    descriptions = (await async_get_all_descriptions(hass))[DOMAIN]
    assert set(descriptions) == {
        "add_item",
        "add_piece",
        "take_piece",
        "update_item",
        "delete_item",
        "undo_last",
        "list_items",
    }
    assert descriptions["add_item"]["fields"]["weights"]["example"] == "200 300 0,5kg"
