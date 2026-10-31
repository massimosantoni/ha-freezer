from __future__ import annotations

import json
from datetime import datetime

import pytest

from pure_support import TZ, const_mod, inventory_mod

Inventory = inventory_mod.Inventory
InventoryError = inventory_mod.InventoryError
parse_weights = inventory_mod.parse_weights


def err_code(excinfo) -> str:
    return excinfo.value.code


# --------------------------------------------------------------------------- #
# Parsing / validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("200 300 500", [200, 300, 500]),
        ("200, 300; 500", [200, 300, 500]),
        ("200g 300 gr", [200, 300]),
        ("0,5kg", [500]),
        ("0,5", [500]),  # bare number < 10 → kg
        ("1.2 kg", [1200]),
        ("1,5 KG", [1500]),
        ("3hg", [300]),
        ("1.200", [1200]),  # Italian thousands separator reads right by luck of the rule
        ("250/250+250", [250, 250, 250]),
        ("", []),
        ("   ", []),
    ],
)
def test_parse_weights_ok(text, expected):
    assert parse_weights(text) == expected


@pytest.mark.parametrize("text", ["200 abc", "due etti", "200 lb", "0", "60kg", "-200"])
def test_parse_weights_rejects_garbage(text):
    with pytest.raises(InventoryError) as exc:
        parse_weights(text)
    assert err_code(exc) == "invalid_weight"


def test_name_is_normalised_and_bounded(inv):
    item = inv.add_item("  Bistecche   di manzo \n macellaio  ", "Carne")
    assert item.name == "Bistecche di manzo macellaio"
    assert item.category == "carne"
    with pytest.raises(InventoryError) as exc:
        inv.add_item("x", "carne")
    assert err_code(exc) == "invalid_name"
    with pytest.raises(InventoryError):
        inv.add_item("a" * (const_mod.NAME_MAX_LEN + 1), "carne")


def test_invalid_category_and_note(inv):
    with pytest.raises(InventoryError) as exc:
        inv.add_item("Pesce spada", "pesce")
    assert err_code(exc) == "invalid_category"
    with pytest.raises(InventoryError) as exc:
        inv.add_item("Pesce spada", "altro", note="x" * (const_mod.NOTE_MAX_LEN + 1))
    assert err_code(exc) == "invalid_note"
    assert inv.items == {}
    assert inv.log == []


# --------------------------------------------------------------------------- #
# add_item / add_piece
# --------------------------------------------------------------------------- #


def test_add_item_default_one_piece_without_weight(inv, clock):
    item = inv.add_item("Piselli surgelati", "verdura", user="Max")
    assert item.quantity == 1
    assert item.pieces[0].weight_g is None
    assert item.created_at == clock.now == item.pieces[0].added_at
    assert item.created_by == "Max"
    assert item.note == ""


def test_add_item_with_quantity(inv):
    item = inv.add_item("Piselli surgelati", "verdura", quantity=4)
    assert item.quantity == 4
    assert item.total_weight_g == 0
    assert item.weighed_pieces == 0


def test_add_item_with_weights_text_and_list(inv):
    a = inv.add_item("Bistecche", "carne", weights="200 300 0,5kg")
    assert [p.weight_g for p in a.pieces] == [200, 300, 500]
    assert a.quantity == 3 and a.total_weight_g == 1000
    b = inv.add_item("Bistecche", "carne", weights=[250, "300g"], quantity=2)
    assert [p.weight_g for p in b.pieces] == [250, 300]


def test_add_item_quantity_weights_mismatch(inv):
    with pytest.raises(InventoryError) as exc:
        inv.add_item("Bistecche", "carne", weights=[200, 300], quantity=3)
    assert err_code(exc) == "quantity_weights_mismatch"


@pytest.mark.parametrize("qty", [0, -1, const_mod.QUANTITY_MAX + 1, True, 2.5])
def test_add_item_invalid_quantity(inv, qty):
    with pytest.raises(InventoryError) as exc:
        inv.add_item("Piselli", "verdura", quantity=qty)
    assert err_code(exc) == "invalid_quantity"


def test_no_automatic_merge_same_name(inv, clock):
    """Decision D1: same name+category → two items, each with its own date."""
    a = inv.add_item("Ragù della nonna", "altro")
    clock.advance(days=10)
    b = inv.add_item("Ragù della nonna", "altro")
    assert a.id != b.id
    assert len(inv.items) == 2
    assert b.created_at - a.created_at


def test_add_piece_keeps_own_date_and_order(inv, clock):
    item = inv.add_item("Bistecche", "carne", weights=[200])
    t0 = item.pieces[0].added_at
    clock.advance(days=14)
    piece = inv.add_piece(item.id, "300 g")
    assert piece.weight_g == 300
    assert piece.added_at == clock.now
    assert [p.added_at for p in item.pieces] == [t0, clock.now]
    assert item.oldest_added_at == t0
    assert item.updated_at == clock.now
    assert item.created_at == t0


def test_add_piece_unknown_item(inv):
    with pytest.raises(InventoryError) as exc:
        inv.add_piece("nope")
    assert err_code(exc) == "item_not_found"


# --------------------------------------------------------------------------- #
# take_piece
# --------------------------------------------------------------------------- #


def test_take_default_is_oldest(inv, clock):
    item = inv.add_item("Bistecche", "carne", weights=[500])
    clock.advance(days=3)
    inv.add_piece(item.id, 200)
    result = inv.take_piece(item.id)
    assert result.piece.weight_g == 500
    assert not result.item_deleted
    assert [p.weight_g for p in item.pieces] == [200]


def test_take_specific_piece(inv):
    item = inv.add_item("Bistecche", "carne", weights=[200, 300, 500])
    target = item.pieces[2]
    result = inv.take_piece(item.id, target.id)
    assert result.piece is target
    assert [p.weight_g for p in item.pieces] == [200, 300]


def test_take_unknown_piece(inv):
    item = inv.add_item("Bistecche", "carne", weights=[200])
    with pytest.raises(InventoryError) as exc:
        inv.take_piece(item.id, "nope")
    assert err_code(exc) == "piece_not_found"
    assert item.quantity == 1


def test_take_last_piece_deletes_item(inv):
    item = inv.add_item("Gelato", "altro")
    result = inv.take_piece(item.id)
    assert result.item_deleted
    assert item.id not in inv.items
    assert inv.log[-1].detail["item_deleted"] is True


# --------------------------------------------------------------------------- #
# update_item / delete_item
# --------------------------------------------------------------------------- #


def test_update_fields(inv, clock):
    item = inv.add_item("Fragole", "verdura")
    clock.advance(hours=1)
    inv.update_item(item.id, category="frutta", note="  dal giardino ", name="Fragole del giardino")
    assert (item.name, item.category, item.note) == ("Fragole del giardino", "frutta", "dal giardino")
    assert item.updated_at == clock.now


def test_update_none_note_clears(inv):
    item = inv.add_item("Fragole", "frutta", note="x")
    inv.update_item(item.id, note=None)
    assert item.note == ""


def test_update_pieces_replace(inv, clock):
    item = inv.add_item("Bistecche", "carne", weights=[200, 300, 500])
    p200, p300, _p500 = item.pieces
    clock.advance(days=1)
    custom_date = datetime(2026, 10, 1, 12, 0, tzinfo=TZ)
    inv.update_item(
        item.id,
        pieces=[
            {"id": p200.id, "weight_g": 220},  # weight fix, date kept
            {"id": p300.id, "weight_g": None, "added_at": custom_date.isoformat()},
            {"weight_g": 400},  # new piece, now
        ],  # p500 dropped
    )
    assert [(p.id, p.weight_g) for p in item.pieces] == [
        (p300.id, None),  # sorted: 1 Oct first
        (p200.id, 220),
        (item.pieces[2].id, 400),
    ]
    assert item.pieces[1].added_at == datetime(2026, 10, 31, 18, 0, tzinfo=TZ)
    assert item.pieces[2].added_at == clock.now


def test_update_is_atomic_on_error(inv):
    item = inv.add_item("Bistecche", "carne", weights=[200])
    before = item.to_dict()
    log_len = len(inv.log)
    with pytest.raises(InventoryError):
        inv.update_item(item.id, name="Bistecchine", pieces=[{"weight_g": "boh"}])
    with pytest.raises(InventoryError) as exc:
        inv.update_item(item.id, pieces=[])
    assert err_code(exc) == "empty_pieces"
    with pytest.raises(InventoryError) as exc:
        inv.update_item(item.id, pieces=[{"id": "ghost", "weight_g": 1}])
    assert err_code(exc) == "piece_not_found"
    with pytest.raises(InventoryError) as exc:
        pid = item.pieces[0].id
        inv.update_item(item.id, pieces=[{"id": pid}, {"id": pid}])
    assert err_code(exc) == "invalid_piece"
    assert item.to_dict() == before
    assert len(inv.log) == log_len


def test_update_rejects_naive_date(inv):
    item = inv.add_item("Bistecche", "carne")
    with pytest.raises(InventoryError) as exc:
        inv.update_item(item.id, pieces=[{"weight_g": 1, "added_at": "2026-10-01T12:00:00"}])
    assert err_code(exc) == "invalid_date"


def test_delete_item(inv):
    item = inv.add_item("Bistecche", "carne")
    inv.delete_item(item.id)
    assert inv.items == {}
    with pytest.raises(InventoryError):
        inv.delete_item(item.id)


# --------------------------------------------------------------------------- #
# undo
# --------------------------------------------------------------------------- #


def test_undo_each_action(inv):
    item = inv.add_item("Bistecche", "carne", weights=[200, 300])
    snap_after_add = item.to_dict()

    inv.add_piece(item.id, 500)
    inv.undo_last()
    assert inv.items[item.id].to_dict() == snap_after_add

    inv.take_piece(item.id)
    inv.undo_last()
    assert inv.items[item.id].to_dict() == snap_after_add

    inv.update_item(item.id, name="Altro nome")
    inv.undo_last()
    assert inv.items[item.id].to_dict() == snap_after_add

    inv.delete_item(item.id)
    inv.undo_last()
    assert inv.items[item.id].to_dict() == snap_after_add

    inv.undo_last()  # undo the add_item itself
    assert inv.items == {}
    with pytest.raises(InventoryError) as exc:
        inv.undo_last()
    assert err_code(exc) == "nothing_to_undo"
    assert not inv.can_undo()


def test_undo_restores_deleted_by_last_take(inv):
    item = inv.add_item("Gelato", "altro", weights=[750])
    inv.take_piece(item.id)
    assert inv.items == {}
    entry = inv.undo_last(user="Anna")
    assert entry.action == "take_piece"
    assert entry.detail["undone_by"] == "Anna"
    restored = inv.items[item.id]
    assert restored.pieces[0].weight_g == 750


def test_undo_stack_after_new_operation(inv):
    a = inv.add_item("A cosa", "altro", quantity=3)
    inv.take_piece(a.id)  # op1
    inv.take_piece(a.id)  # op2
    inv.undo_last()  # undo op2 → 2 pieces
    inv.take_piece(a.id)  # op3 → 1 piece
    inv.undo_last()  # undo op3 → 2 pieces
    assert inv.items[a.id].quantity == 2
    inv.undo_last()  # skips op2 (undone), undoes op1 → 3 pieces
    assert inv.items[a.id].quantity == 3


def test_undo_after_reload_from_storage(inv, clock, ids):
    item = inv.add_item("Bistecche", "carne", weights=[200, 300])
    inv.take_piece(item.id)
    data = json.loads(json.dumps(inv.to_dict()))  # must be JSON-serialisable
    reloaded = Inventory(data, now=clock, new_id=ids)
    reloaded.undo_last()
    assert reloaded.items[item.id].quantity == 2


def test_log_is_bounded(inv):
    item = inv.add_item("Piselli", "verdura")
    for _ in range(const_mod.LOG_MAX_ENTRIES + 20):
        inv.add_piece(item.id) if item.quantity < 10 else inv.take_piece(item.id)
    assert len(inv.log) == const_mod.LOG_MAX_ENTRIES


# --------------------------------------------------------------------------- #
# queries
# --------------------------------------------------------------------------- #


@pytest.fixture
def stocked(inv, clock):
    names = {}
    names["sugo"] = inv.add_item("Sugo", "altro")  # day 0
    clock.advance(days=1)
    names["piselli"] = inv.add_item("piselli", "verdura")  # day 1
    clock.advance(days=1)
    names["bistecche"] = inv.add_item("Bistecche", "carne")  # day 2
    clock.advance(days=1)
    names["fragole"] = inv.add_item("Fragole", "frutta")  # day 3
    clock.advance(days=1)
    names["arista"] = inv.add_item("Arista", "carne")  # day 4
    # an old piece makes "fragole" the oldest item
    inv.update_item(
        names["fragole"].id,
        pieces=[{"weight_g": None, "added_at": "2026-01-01T10:00:00+01:00"}],
    )
    return names


def _names(items):
    return [i.name for i in items]


def test_sort_by_date_uses_oldest_piece(inv, stocked):
    assert _names(inv.list_items()) == ["Fragole", "Sugo", "piselli", "Bistecche", "Arista"]
    assert _names(inv.list_items(descending=True)) == ["Arista", "Bistecche", "piselli", "Sugo", "Fragole"]


def test_sort_by_category_then_date(inv, stocked):
    assert _names(inv.list_items(sort="category")) == ["Bistecche", "Arista", "piselli", "Fragole", "Sugo"]


def test_sort_by_name_case_insensitive(inv, stocked):
    assert _names(inv.list_items(sort="name")) == ["Arista", "Bistecche", "Fragole", "piselli", "Sugo"]


def test_filter_category(inv, stocked):
    assert _names(inv.list_items(category="Carne")) == ["Bistecche", "Arista"]
    with pytest.raises(InventoryError):
        inv.list_items(category="pesce")
    with pytest.raises(InventoryError) as exc:
        inv.list_items(sort="weight")
    assert err_code(exc) == "invalid_sort"


def test_summary_and_view(inv):
    a = inv.add_item("Bistecche", "carne", weights=[200, 300])
    inv.add_item("Piselli", "verdura", quantity=3)
    s = inv.summary()
    assert s["total_items"] == 2
    assert s["total_pieces"] == 5
    assert s["total_weight_g"] == 500
    assert s["by_category"]["carne"] == {"items": 1, "pieces": 2}
    assert s["by_category"]["frutta"] == {"items": 0, "pieces": 0}
    assert s["oldest_added_at"] == a.created_at.isoformat()
    view = a.to_view()
    assert view["quantity"] == 2 and view["total_weight_g"] == 500
    assert view["weighed_pieces"] == 2
    json.dumps(view)


def test_empty_summary(inv):
    assert inv.summary()["oldest_added_at"] is None
    assert inv.summary()["total_pieces"] == 0


def test_roundtrip_serialisation(inv, clock, ids):
    inv.add_item("Bistecche – macellaio", "carne", weights=[200], note="sottovuoto", user="Max")
    data = json.loads(json.dumps(inv.to_dict()))
    assert data["version"] == inventory_mod.DATA_VERSION
    again = Inventory(data, now=clock, new_id=ids)
    assert again.to_dict() == inv.to_dict()


def test_naive_clock_rejected(ids):
    inv = Inventory(now=lambda: datetime(2026, 1, 1), new_id=ids)
    with pytest.raises(RuntimeError):
        inv.add_item("Bistecche", "carne")
