"""Fixtures for the pure domain tests (no Home Assistant needed)."""

from __future__ import annotations

import itertools

import pytest
from pure_support import FakeClock, inventory_mod


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ids():
    counter = itertools.count(1)
    return lambda: f"id{next(counter):04d}"


@pytest.fixture
def inv(clock, ids):
    return inventory_mod.Inventory(now=clock, new_id=ids)
