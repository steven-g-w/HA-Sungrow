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

from .conftest import BATTERY_PS_KEY, ESS_PS_KEY, PLANT_PS_KEY


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

    # ESS battery SoC: raw fraction 0.55 scaled to percent via API metadata.
    soc_id = _entity_id(hass, f"{ESS_PS_KEY}_13141")
    assert soc_id is not None
    soc = hass.states.get(soc_id)
    assert soc is not None
    assert soc.state == "55.0"
    assert soc.attributes["unit_of_measurement"] == "%"
    assert soc.attributes["device_class"] == "battery"

    # Battery charging power, unit from API metadata (storage_unit W).
    charge_id = _entity_id(hass, f"{ESS_PS_KEY}_13126")
    assert charge_id is not None
    charge = hass.states.get(charge_id)
    assert charge.state == "2500.0"
    assert charge.attributes["unit_of_measurement"] == "W"
    assert charge.attributes["device_class"] == "power"

    # Plant daily yield is an energy sensor usable in the energy dashboard.
    # The plant has no API metadata in the fixtures -> catalog fallback.
    yield_id = _entity_id(hass, f"{PLANT_PS_KEY}_83022")
    assert yield_id is not None
    yield_state = hass.states.get(yield_id)
    assert yield_state.state == "12345.0"
    assert yield_state.attributes["unit_of_measurement"] == "Wh"
    assert yield_state.attributes["device_class"] == "energy"
    assert yield_state.attributes["state_class"] == "total_increasing"

    # Plant battery SoC: fraction scaled to percent via catalog fallback.
    plant_soc_id = _entity_id(hass, f"{PLANT_PS_KEY}_83252")
    assert plant_soc_id is not None
    plant_soc = hass.states.get(plant_soc_id)
    assert plant_soc.state == "41.0"
    assert plant_soc.attributes["unit_of_measurement"] == "%"

    # Standalone battery device (type 43) SoC and voltage.
    bat_soc_id = _entity_id(hass, f"{BATTERY_PS_KEY}_58604")
    assert bat_soc_id is not None
    bat_soc = hass.states.get(bat_soc_id)
    assert bat_soc.state == "44.0"
    assert bat_soc.attributes["unit_of_measurement"] == "%"
    bat_volt_id = _entity_id(hass, f"{BATTERY_PS_KEY}_58601")
    assert bat_volt_id is not None
    bat_volt = hass.states.get(bat_volt_id)
    assert bat_volt.state == "523.9"
    assert bat_volt.attributes["unit_of_measurement"] == "V"
    assert bat_volt.attributes["device_class"] == "voltage"


async def test_economics_sensors(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Income and CO2 sensors are created on the plant device."""
    await _setup(hass, mock_config_entry)

    income_id = _entity_id(hass, f"{PLANT_PS_KEY}_econ_total_income")
    assert income_id is not None
    income = hass.states.get(income_id)
    assert income.state == "7890.0"
    assert income.attributes["unit_of_measurement"] == "AUD"
    assert income.attributes["device_class"] == "monetary"
    assert income.attributes["state_class"] == "total"

    co2_id = _entity_id(hass, f"{PLANT_PS_KEY}_econ_co2_reduce_total")
    assert co2_id is not None
    co2 = hass.states.get(co2_id)
    assert co2.state == "36437.0"
    assert co2.attributes["unit_of_measurement"] == "kg"
    assert co2.attributes["state_class"] == "total_increasing"

    # The plant device is named after the plant, not the numeric id.
    registry = dr.async_get(hass)
    plant = registry.async_get_device(identifiers={(DOMAIN, PLANT_PS_KEY)})
    assert plant.name == "Test Plant"


async def test_no_entities_for_missing_values(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Points reported as '--' or null do not create entities."""
    await _setup(hass, mock_config_entry)
    assert _entity_id(hass, f"{ESS_PS_KEY}_13112") is None  # value "--"
    assert _entity_id(hass, f"{PLANT_PS_KEY}_83024") is None  # value null


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

    battery = registry.async_get_device(identifiers={(DOMAIN, BATTERY_PS_KEY)})
    assert battery is not None
    assert battery.name == "Battery1"
    assert battery.model == "SBR256"
    assert battery.via_device_id == plant.id


async def test_new_points_add_entities_later(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A point that starts reporting later gets an entity on refresh."""
    await _setup(hass, mock_config_entry)
    assert _entity_id(hass, f"{ESS_PS_KEY}_13150") is not None
    assert _entity_id(hass, f"{ESS_PS_KEY}_13142") is None

    # Next poll reports battery health too (fraction, scaled via metadata).
    async def _realtime(device_type: int, ps_keys: list[str], points: list[str]):
        if device_type == 14:
            return {
                "device_point_list": [
                    {"device_point": {"ps_key": ESS_PS_KEY, "p13142": "0.98"}}
                ]
            }
        return {"device_point_list": []}

    mock_api_client.async_get_realtime_data = AsyncMock(side_effect=_realtime)
    coordinator = mock_config_entry.runtime_data.coordinator
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
