"""Tests for entry setup, sensors and unload."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sungrow_isolarcloud.api import (
    SungrowApiError,
    SungrowAuthError,
)
from custom_components.sungrow_isolarcloud.const import DOMAIN

from .conftest import ESS_PS_KEY, PLANT_PS_KEY


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, unique_id: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id("sensor", DOMAIN, unique_id)


async def test_setup_creates_sensors(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Setting up the entry creates plant and battery sensors."""
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    # Battery SoC from the ESS device, with API-provided name/unit.
    soc_id = _entity_id(hass, f"{ESS_PS_KEY}_13141")
    assert soc_id is not None
    soc = hass.states.get(soc_id)
    assert soc is not None
    assert soc.state == "55.0"
    assert soc.attributes["unit_of_measurement"] == "%"
    assert soc.attributes["device_class"] == "battery"

    # Battery charging power.
    charge_id = _entity_id(hass, f"{ESS_PS_KEY}_13126")
    assert charge_id is not None
    charge = hass.states.get(charge_id)
    assert charge.state == "2500.0"
    assert charge.attributes["unit_of_measurement"] == "W"
    assert charge.attributes["device_class"] == "power"

    # Plant daily yield is an energy sensor usable in the energy dashboard.
    yield_id = _entity_id(hass, f"{PLANT_PS_KEY}_83022")
    assert yield_id is not None
    yield_state = hass.states.get(yield_id)
    assert yield_state.state == "12345.0"
    assert yield_state.attributes["unit_of_measurement"] == "Wh"
    assert yield_state.attributes["device_class"] == "energy"
    assert yield_state.attributes["state_class"] == "total_increasing"


async def test_no_entities_for_missing_values(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Points reported as '--' or null do not create entities."""
    await _setup(hass, mock_config_entry)
    assert _entity_id(hass, f"{ESS_PS_KEY}_13112") is None  # value "--"
    assert _entity_id(hass, f"{PLANT_PS_KEY}_83252") is None  # value null


async def test_devices_registered(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Plant and ESS devices appear in the device registry."""
    await _setup(hass, mock_config_entry)
    registry = dr.async_get(hass)
    plant = registry.async_get_device(identifiers={(DOMAIN, PLANT_PS_KEY)})
    assert plant is not None
    assert plant.manufacturer == "Sungrow"

    ess = registry.async_get_device(identifiers={(DOMAIN, ESS_PS_KEY)})
    assert ess is not None
    assert ess.name == "SH10RT"
    assert ess.serial_number == "SN-ESS-1"
    assert ess.via_device_id == plant.id


async def test_new_points_add_entities_later(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A point that starts reporting later gets an entity on refresh."""
    await _setup(hass, mock_config_entry)
    assert _entity_id(hass, f"{ESS_PS_KEY}_13150") is not None
    assert _entity_id(hass, f"{ESS_PS_KEY}_13142") is None

    # Next poll reports battery health too.
    async def _realtime(device_type: int, ps_keys: list[str], points: list[str]):
        if device_type == 11:
            return {"device_point_list": []}
        return {
            "device_point_list": [
                {"device_point": {"ps_key": ESS_PS_KEY, "p13142": "98"}}
            ],
            "point_dict": [
                {"point_id": "13142", "point_name": "Battery SoH", "point_unit": "%"}
            ],
        }

    mock_api_client.async_get_realtime_data = AsyncMock(side_effect=_realtime)
    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    soh_id = _entity_id(hass, f"{ESS_PS_KEY}_13142")
    assert soh_id is not None
    assert hass.states.get(soh_id).state == "98.0"


async def test_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An auth failure during setup puts the entry into reauth."""
    mock_api_client.async_get_device_list = AsyncMock(
        side_effect=SungrowAuthError("token dead")
    )
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_api_error_makes_setup_retry(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A transient API failure during setup schedules a retry."""
    mock_api_client.async_get_device_list = AsyncMock(
        side_effect=SungrowApiError("cloud down")
    )
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The entry unloads cleanly."""
    await _setup(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
