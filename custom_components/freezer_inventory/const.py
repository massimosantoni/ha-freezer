"""Constants for the Freezer Inventory integration.

This module must not import Home Assistant: it is shared with inventory.py,
which is tested without HA installed.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "freezer_inventory"

# Order matters: it is the display / sort order of categories.
CATEGORIES: Final[tuple[str, ...]] = ("carne", "verdura", "frutta", "altro")

NAME_MIN_LEN: Final = 2
NAME_MAX_LEN: Final = 80
NOTE_MAX_LEN: Final = 500
WEIGHT_MIN_G: Final = 1
WEIGHT_MAX_G: Final = 50_000
QUANTITY_MAX: Final = 50
LOG_MAX_ENTRIES: Final = 300

SORT_DATE: Final = "date"
SORT_CATEGORY: Final = "category"
SORT_NAME: Final = "name"
SORT_KEYS: Final[tuple[str, ...]] = (SORT_DATE, SORT_CATEGORY, SORT_NAME)

# --- Home Assistant layer (plain strings, still no HA imports) -------------- #
STORAGE_VERSION: Final = 1
SAVE_DELAY_S: Final = 1
SIGNAL_UPDATED: Final = f"{DOMAIN}_updated"
CARD_URL: Final = f"/{DOMAIN}/freezer-inventory-card.js"
DEFAULT_NAME: Final = "Freezer"
