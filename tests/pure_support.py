"""Helpers for the pure domain tests: load the pure modules (const, inventory) without executing the package
``__init__.py``, which imports Home Assistant. This keeps the domain tests
runnable with plain pytest."""

from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "freezer_inventory"

_pkg = types.ModuleType("fi_pure")
_pkg.__path__ = [str(PKG_DIR)]  # type: ignore[attr-defined]
sys.modules.setdefault("fi_pure", _pkg)

inventory_mod = importlib.import_module("fi_pure.inventory")
const_mod = importlib.import_module("fi_pure.const")

TZ = timezone(timedelta(hours=1))


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 31, 18, 0, tzinfo=TZ)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now
