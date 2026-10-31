"""Fixtures for the Home Assistant integration tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freezer_inventory.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/ in every test."""
    return


@pytest.fixture
def config_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Freezer piano terra", data={})
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def loaded_entry(hass, config_entry) -> MockConfigEntry:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
