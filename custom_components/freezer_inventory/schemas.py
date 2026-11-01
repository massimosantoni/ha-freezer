"""Voluptuous schemas shared by services and websocket commands.

They only check shapes/types; domain validation (lengths, categories, weight
ranges) lives in inventory.py so both entry points report the same errors.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .const import QUANTITY_MAX, SORT_KEYS

ITEM_ID = "item_id"

_WEIGHT = vol.Any(None, vol.Coerce(int))
_PORTIONS = vol.Any(None, vol.Coerce(int))
# free text for one piece: "250", "0,5kg", "4" (portions), "12 por"
_AMOUNT = vol.Any(None, cv.string)

ADD_ITEM = {
    vol.Required("name"): cv.string,
    vol.Required("category"): cv.string,
    vol.Optional("quantity"): vol.All(vol.Coerce(int), vol.Range(min=1, max=QUANTITY_MAX)),
    # one value per piece, list or free text: "300 0,5kg 4" (bare numbers < 10 = portions)
    vol.Optional("weights"): vol.Any([vol.Any(vol.Coerce(int), cv.string)], cv.string),
    vol.Optional("note"): vol.Any(None, cv.string),
}

ADD_PIECE = {
    vol.Required(ITEM_ID): cv.string,
    vol.Optional("weight_g"): _WEIGHT,
    vol.Optional("portions"): _PORTIONS,
    vol.Optional("amount"): _AMOUNT,
}

TAKE_PIECE = {
    vol.Required(ITEM_ID): cv.string,
    vol.Optional("piece_id"): vol.Any(None, cv.string),
}

PIECE = vol.Schema(
    {
        vol.Optional("id"): vol.Any(None, cv.string),
        vol.Optional("weight_g"): _WEIGHT,
        vol.Optional("portions"): _PORTIONS,
        vol.Optional("amount"): _AMOUNT,
        vol.Optional("added_at"): vol.Any(None, cv.string),
    }
)

UPDATE_ITEM = {
    vol.Required(ITEM_ID): cv.string,
    vol.Optional("name"): cv.string,
    vol.Optional("category"): cv.string,
    vol.Optional("note"): vol.Any(None, cv.string),
    vol.Optional("pieces"): [PIECE],
}

DELETE_ITEM = {vol.Required(ITEM_ID): cv.string}

UNDO_LAST: dict = {}

LIST_ITEMS = {
    vol.Optional("category"): cv.string,
    vol.Optional("sort", default="date"): vol.In(SORT_KEYS),
    vol.Optional("descending", default=False): cv.boolean,
}
