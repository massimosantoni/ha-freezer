"""Pure domain model and operations for the freezer inventory.

No Home Assistant imports here: the HA layer (``__init__.py``) owns persistence
(``helpers.storage.Store``), clocks, ids and users, and calls into this module.
Everything is synchronous and in-memory; the caller saves ``to_dict()``.

Model
-----
An *item* (voce) is something like "Bistecche di manzo". It holds a list of
*pieces* (pezzi); quantity == len(pieces). Each piece has its own optional
weight and its own insertion timestamp, so pieces added later keep their date.
An item whose last piece is taken is deleted. Every mutating operation stores
a snapshot of the item *before* the change in a bounded log, which makes
``undo_last`` a simple stack pop.
"""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .const import (
    CATEGORIES,
    LOG_MAX_ENTRIES,
    NAME_MAX_LEN,
    NAME_MIN_LEN,
    NOTE_MAX_LEN,
    QUANTITY_MAX,
    SORT_CATEGORY,
    SORT_DATE,
    SORT_KEYS,
    SORT_NAME,
    WEIGHT_MAX_G,
    WEIGHT_MIN_G,
)

DATA_VERSION = 1


class InventoryError(ValueError):
    """Validation or lookup error.

    ``code`` is stable and doubles as the HA translation key, so the UI can
    show a localised message; ``placeholders`` fill that message.
    """

    def __init__(self, code: str, message: str, **placeholders: Any) -> None:
        super().__init__(message)
        self.code = code
        self.placeholders = {k: str(v) for k, v in placeholders.items()}


class _Unset:
    """Sentinel for "argument not given" (``None`` is a valid value for some fields)."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "UNSET"


UNSET: Any = _Unset()


# --------------------------------------------------------------------------- #
# Validation / parsing helpers
# --------------------------------------------------------------------------- #


def normalize_name(value: Any) -> str:
    if not isinstance(value, str):
        raise InventoryError("invalid_name", "Name must be a string")
    name = " ".join(value.split())
    if not NAME_MIN_LEN <= len(name) <= NAME_MAX_LEN:
        raise InventoryError(
            "invalid_name",
            f"Name must be {NAME_MIN_LEN}-{NAME_MAX_LEN} characters",
            min=NAME_MIN_LEN,
            max=NAME_MAX_LEN,
        )
    return name


def normalize_category(value: Any) -> str:
    cat = value.strip().casefold() if isinstance(value, str) else None
    if cat not in CATEGORIES:
        raise InventoryError(
            "invalid_category",
            f"Category must be one of {', '.join(CATEGORIES)}",
            categories=", ".join(CATEGORIES),
        )
    return cat


def normalize_note(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InventoryError("invalid_note", "Note must be a string")
    note = value.strip()
    if len(note) > NOTE_MAX_LEN:
        raise InventoryError("invalid_note", f"Note exceeds {NOTE_MAX_LEN} characters", max=NOTE_MAX_LEN)
    return note


def validate_weight(value: Any) -> int | None:
    """Return a weight in whole grams, or None for "unknown"."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        raise InventoryError("invalid_weight", "Weight must be a number of grams")
    if isinstance(value, str):
        parsed = parse_weights(value)
        if len(parsed) != 1:
            raise InventoryError("invalid_weight", f"Cannot parse weight {value!r}")
        return parsed[0]
    if isinstance(value, float):
        value = round(value)
    if not isinstance(value, int):
        raise InventoryError("invalid_weight", "Weight must be a number of grams")
    if not WEIGHT_MIN_G <= value <= WEIGHT_MAX_G:
        raise InventoryError(
            "invalid_weight",
            f"Weight must be {WEIGHT_MIN_G}-{WEIGHT_MAX_G} g",
            min=WEIGHT_MIN_G,
            max=WEIGHT_MAX_G,
        )
    return value


# number, optional decimal part with "," or ".", optional unit
_WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|hg|gr|g)?(?![a-z])")
_UNIT_FACTOR = {"kg": 1000, "hg": 100, "gr": 1, "g": 1}


def parse_weights(text: str) -> list[int]:
    """Parse free text such as ``"200 300 0,5kg 1.2 kg 3hg"`` into grams.

    Rules:
    * tokens are separated by anything that is not part of a number+unit
      (spaces, ``;``, ``/``, ``+``, or ``", "`` — a comma *followed by a space*);
    * ``,`` or ``.`` directly between digits is a decimal separator;
    * a bare number below 10 is read as kg (``0,5`` → 500 g), otherwise as g.

    Raises InventoryError if the text contains anything that is not a weight.
    """
    if not isinstance(text, str):
        raise InventoryError("invalid_weight", "Weights must be text")
    lowered = text.casefold()
    weights: list[int] = []
    pos = 0
    for match in _WEIGHT_RE.finditer(lowered):
        gap = lowered[pos : match.start()]
        if gap.strip(" \t;/+,") != "":
            raise InventoryError("invalid_weight", f"Cannot parse weights {text!r}")
        number = float(match.group(1).replace(",", "."))
        unit = match.group(2)
        if unit is None:
            unit = "kg" if number < 10 else "g"
        weights.append(validate_weight(round(number * _UNIT_FACTOR[unit])))  # type: ignore[arg-type]
        pos = match.end()
    if lowered[pos:].strip(" \t;/+,") != "":
        raise InventoryError("invalid_weight", f"Cannot parse weights {text!r}")
    return weights


def _coerce_weights(weights: Any) -> list[int]:
    if weights is None:
        return []
    if isinstance(weights, str):
        return parse_weights(weights)
    if isinstance(weights, Iterable):
        result = []
        for w in weights:
            v = validate_weight(w)
            if v is None:
                raise InventoryError("invalid_weight", "Empty weight in list")
            result.append(v)
        return result
    raise InventoryError("invalid_weight", "Weights must be a list or text")


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError as err:
            raise InventoryError("invalid_date", f"Invalid date {value!r}") from err
    else:
        raise InventoryError("invalid_date", f"Invalid date {value!r}")
    if dt.tzinfo is None:
        raise InventoryError("invalid_date", "Date must include a timezone")
    return dt


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass
class Piece:
    id: str
    added_at: datetime
    weight_g: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "weight_g": self.weight_g, "added_at": self.added_at.isoformat()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Piece:
        return cls(
            id=str(data["id"]),
            added_at=_parse_dt(data["added_at"]),
            weight_g=validate_weight(data.get("weight_g")),
        )


@dataclass
class Item:
    id: str
    name: str
    category: str
    created_at: datetime
    updated_at: datetime
    note: str = ""
    created_by: str | None = None
    pieces: list[Piece] = field(default_factory=list)

    # ----- derived values ------------------------------------------------- #
    @property
    def quantity(self) -> int:
        return len(self.pieces)

    @property
    def total_weight_g(self) -> int:
        """Sum of the known weights (pieces without weight count as 0)."""
        return sum(p.weight_g or 0 for p in self.pieces)

    @property
    def weighed_pieces(self) -> int:
        return sum(1 for p in self.pieces if p.weight_g is not None)

    @property
    def oldest_added_at(self) -> datetime:
        return self.pieces[0].added_at if self.pieces else self.created_at

    def sort_pieces(self) -> None:
        # stable: pieces inserted together keep their insertion order
        self.pieces.sort(key=lambda p: p.added_at)

    def get_piece(self, piece_id: str) -> Piece:
        for piece in self.pieces:
            if piece.id == piece_id:
                return piece
        raise InventoryError("piece_not_found", f"Piece {piece_id} not found in {self.id}", piece_id=piece_id)

    # ----- (de)serialisation ---------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "note": self.note,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "pieces": [p.to_dict() for p in self.pieces],
        }

    def to_view(self) -> dict[str, Any]:
        """Serialised item plus derived fields, for the card and list_items."""
        data = self.to_dict()
        data.update(
            quantity=self.quantity,
            total_weight_g=self.total_weight_g,
            weighed_pieces=self.weighed_pieces,
            oldest_added_at=self.oldest_added_at.isoformat(),
        )
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Item:
        item = cls(
            id=str(data["id"]),
            name=normalize_name(data["name"]),
            category=normalize_category(data["category"]),
            note=normalize_note(data.get("note")),
            created_at=_parse_dt(data["created_at"]),
            updated_at=_parse_dt(data.get("updated_at") or data["created_at"]),
            created_by=data.get("created_by"),
            pieces=[Piece.from_dict(p) for p in data.get("pieces", [])],
        )
        item.sort_pieces()
        return item


@dataclass
class LogEntry:
    id: str
    ts: datetime
    action: str
    item_id: str
    item_name: str
    before: dict[str, Any] | None  # item snapshot before the change; None = item did not exist
    user: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    undone: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "action": self.action,
            "item_id": self.item_id,
            "item_name": self.item_name,
            "before": self.before,
            "user": self.user,
            "detail": self.detail,
            "undone": self.undone,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LogEntry:
        return cls(
            id=str(data["id"]),
            ts=_parse_dt(data["ts"]),
            action=str(data["action"]),
            item_id=str(data["item_id"]),
            item_name=str(data.get("item_name", "")),
            before=data.get("before"),
            user=data.get("user"),
            detail=dict(data.get("detail") or {}),
            undone=bool(data.get("undone", False)),
        )


@dataclass
class TakeResult:
    piece: Piece
    item: Item | None  # None when the item was deleted (last piece taken)

    @property
    def item_deleted(self) -> bool:
        return self.item is None


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #


def _default_now() -> datetime:
    return datetime.now().astimezone()


def _default_id() -> str:
    return uuid.uuid4().hex


class Inventory:
    """In-memory inventory. Not thread-safe; HA calls it from the event loop."""

    def __init__(
        self,
        data: Mapping[str, Any] | None = None,
        *,
        now: Callable[[], datetime] = _default_now,
        new_id: Callable[[], str] = _default_id,
    ) -> None:
        self._now = now
        self._new_id = new_id
        self.items: dict[str, Item] = {}
        self.log: list[LogEntry] = []
        if data:
            self.items = {i["id"]: Item.from_dict(i) for i in data.get("items", {}).values()}
            self.log = [LogEntry.from_dict(e) for e in data.get("log", [])]

    # ----- persistence ----------------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": DATA_VERSION,
            "items": {i.id: i.to_dict() for i in self.items.values()},
            "log": [e.to_dict() for e in self.log],
        }

    # ----- internals ------------------------------------------------------- #
    def _now_checked(self) -> datetime:
        now = self._now()
        if now.tzinfo is None:
            raise RuntimeError("Clock must return timezone-aware datetimes")
        return now

    def get_item(self, item_id: str) -> Item:
        try:
            return self.items[item_id]
        except KeyError:
            raise InventoryError("item_not_found", f"Item {item_id} not found", item_id=item_id) from None

    def _record(
        self,
        action: str,
        item_id: str,
        item_name: str,
        before: Item | None,
        user: str | None,
        now: datetime,
        **detail: Any,
    ) -> None:
        self.log.append(
            LogEntry(
                id=self._new_id(),
                ts=now,
                action=action,
                item_id=item_id,
                item_name=item_name,
                before=copy.deepcopy(before.to_dict()) if before else None,
                user=user,
                detail=detail,
            )
        )
        if len(self.log) > LOG_MAX_ENTRIES:
            del self.log[: len(self.log) - LOG_MAX_ENTRIES]

    def _snapshot(self, item: Item) -> Item:
        return Item.from_dict(item.to_dict())

    # ----- operations ------------------------------------------------------ #
    def add_item(
        self,
        name: str,
        category: str,
        *,
        quantity: int | None = None,
        weights: Any = None,
        note: str | None = None,
        user: str | None = None,
    ) -> Item:
        """Create a new item. Never merges with existing items (decision D1).

        ``weights`` (list or free text) defines one piece per weight; if given,
        ``quantity`` must be omitted or equal to the number of weights.
        Without weights, ``quantity`` pieces with unknown weight are created.
        """
        name = normalize_name(name)
        category = normalize_category(category)
        note = normalize_note(note)
        weight_list = _coerce_weights(weights)

        if weight_list:
            if quantity not in (None, len(weight_list)):
                raise InventoryError(
                    "quantity_weights_mismatch",
                    f"Quantity {quantity} does not match {len(weight_list)} weights",
                    quantity=quantity,
                    weights=len(weight_list),
                )
            piece_weights: list[int | None] = list(weight_list)
        else:
            qty = 1 if quantity is None else quantity
            if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= QUANTITY_MAX:
                raise InventoryError(
                    "invalid_quantity", f"Quantity must be 1-{QUANTITY_MAX}", max=QUANTITY_MAX
                )
            piece_weights = [None] * qty
        if len(piece_weights) > QUANTITY_MAX:
            raise InventoryError("invalid_quantity", f"Quantity must be 1-{QUANTITY_MAX}", max=QUANTITY_MAX)

        now = self._now_checked()
        item = Item(
            id=self._new_id(),
            name=name,
            category=category,
            note=note,
            created_at=now,
            updated_at=now,
            created_by=user,
            pieces=[Piece(id=self._new_id(), added_at=now, weight_g=w) for w in piece_weights],
        )
        self.items[item.id] = item
        self._record("add_item", item.id, item.name, None, user, now, quantity=item.quantity)
        return item

    def add_piece(self, item_id: str, weight_g: Any = None, *, user: str | None = None) -> Piece:
        item = self.get_item(item_id)
        weight = validate_weight(weight_g)
        if item.quantity >= QUANTITY_MAX:
            raise InventoryError("invalid_quantity", f"Quantity must be 1-{QUANTITY_MAX}", max=QUANTITY_MAX)
        now = self._now_checked()
        before = self._snapshot(item)
        piece = Piece(id=self._new_id(), added_at=now, weight_g=weight)
        item.pieces.append(piece)
        item.sort_pieces()
        item.updated_at = now
        self._record("add_piece", item.id, item.name, before, user, now, weight_g=weight)
        return piece

    def take_piece(self, item_id: str, piece_id: str | None = None, *, user: str | None = None) -> TakeResult:
        """Remove one piece; the oldest unless ``piece_id`` is given (decision D3)."""
        item = self.get_item(item_id)
        piece = item.get_piece(piece_id) if piece_id else item.pieces[0]
        now = self._now_checked()
        before = self._snapshot(item)
        item.pieces.remove(piece)
        deleted = not item.pieces
        if deleted:
            del self.items[item.id]
        else:
            item.updated_at = now
        self._record(
            "take_piece",
            item.id,
            item.name,
            before,
            user,
            now,
            piece=piece.to_dict(),
            item_deleted=deleted,
        )
        return TakeResult(piece=piece, item=None if deleted else item)

    def update_item(
        self,
        item_id: str,
        *,
        name: Any = UNSET,
        category: Any = UNSET,
        note: Any = UNSET,
        pieces: Any = UNSET,
        user: str | None = None,
    ) -> Item:
        """Correct an item. ``pieces`` replaces the whole list:

        * ``{"id": <existing>, "weight_g": ..., "added_at"?: ...}`` updates a piece
          (omitted ``added_at`` keeps the original date);
        * an entry without ``id`` creates a new piece (``added_at`` defaults to now);
        * existing pieces not listed are removed.
        An empty list is rejected: use ``delete_item``.
        """
        item = self.get_item(item_id)
        # validate everything before mutating anything
        new_name = item.name if name is UNSET else normalize_name(name)
        new_category = item.category if category is UNSET else normalize_category(category)
        new_note = item.note if note is UNSET else normalize_note(note)
        now = self._now_checked()

        new_pieces = item.pieces
        if pieces is not UNSET:
            if not isinstance(pieces, list) or not pieces:
                raise InventoryError("empty_pieces", "An item needs at least one piece")
            if len(pieces) > QUANTITY_MAX:
                raise InventoryError(
                    "invalid_quantity", f"Quantity must be 1-{QUANTITY_MAX}", max=QUANTITY_MAX
                )
            new_pieces = []
            seen: set[str] = set()
            for raw in pieces:
                if not isinstance(raw, Mapping):
                    raise InventoryError("invalid_piece", "Each piece must be an object")
                weight = validate_weight(raw.get("weight_g"))
                piece_id = raw.get("id")
                if piece_id:
                    if piece_id in seen:
                        raise InventoryError(
                            "invalid_piece", f"Duplicate piece {piece_id}", piece_id=piece_id
                        )
                    seen.add(piece_id)
                    old = item.get_piece(piece_id)
                    added_at = _parse_dt(raw["added_at"]) if raw.get("added_at") else old.added_at
                    new_pieces.append(Piece(id=old.id, added_at=added_at, weight_g=weight))
                else:
                    added_at = _parse_dt(raw["added_at"]) if raw.get("added_at") else now
                    new_pieces.append(Piece(id=self._new_id(), added_at=added_at, weight_g=weight))

        before = self._snapshot(item)
        item.name, item.category, item.note = new_name, new_category, new_note
        item.pieces = new_pieces
        item.sort_pieces()
        item.updated_at = now
        self._record("update_item", item.id, item.name, before, user, now)
        return item

    def delete_item(self, item_id: str, *, user: str | None = None) -> Item:
        item = self.get_item(item_id)
        now = self._now_checked()
        del self.items[item.id]
        self._record("delete_item", item.id, item.name, item, user, now)
        return item

    def undo_last(self, *, user: str | None = None) -> LogEntry:
        """Revert the most recent operation that has not been undone yet."""
        for entry in reversed(self.log):
            if entry.undone:
                continue
            if entry.before is None:
                self.items.pop(entry.item_id, None)
            else:
                restored = Item.from_dict(entry.before)
                self.items[restored.id] = restored
            entry.undone = True
            entry.detail = {**entry.detail, "undone_by": user}
            return entry
        raise InventoryError("nothing_to_undo", "Nothing to undo")

    # ----- queries --------------------------------------------------------- #
    def list_items(
        self,
        *,
        sort: str = SORT_DATE,
        category: str | None = None,
        descending: bool = False,
    ) -> list[Item]:
        """Items filtered by category and sorted.

        * ``date``: by oldest piece (FIFO — what should be eaten first);
        * ``category``: grouped in CATEGORIES order, oldest first inside a group;
        * ``name``: case-insensitive, then date.
        ``descending`` reverses the primary key only (e.g. newest first).
        """
        if sort not in SORT_KEYS:
            raise InventoryError(
                "invalid_sort", f"Sort must be one of {', '.join(SORT_KEYS)}", sorts=", ".join(SORT_KEYS)
            )
        items = list(self.items.values())
        if category is not None:
            cat = normalize_category(category)
            items = [i for i in items if i.category == cat]

        # secondary keys first (stable sort), then the primary key
        items.sort(key=lambda i: (i.oldest_added_at, i.name.casefold()))
        if sort == SORT_DATE:
            items.sort(key=lambda i: i.oldest_added_at, reverse=descending)
        elif sort == SORT_CATEGORY:
            items.sort(key=lambda i: CATEGORIES.index(i.category), reverse=descending)
        elif sort == SORT_NAME:
            items.sort(key=lambda i: i.name.casefold(), reverse=descending)
        return items

    def summary(self) -> dict[str, Any]:
        """Small aggregate for sensor state/attributes (keep it well under 16 KB)."""
        by_cat = {c: {"items": 0, "pieces": 0} for c in CATEGORIES}
        for item in self.items.values():
            by_cat[item.category]["items"] += 1
            by_cat[item.category]["pieces"] += item.quantity
        oldest = min((i.oldest_added_at for i in self.items.values()), default=None)
        return {
            "total_items": len(self.items),
            "total_pieces": sum(i.quantity for i in self.items.values()),
            "total_weight_g": sum(i.total_weight_g for i in self.items.values()),
            "by_category": by_cat,
            "oldest_added_at": oldest.isoformat() if oldest else None,
        }

    def can_undo(self) -> bool:
        return any(not e.undone for e in self.log)
