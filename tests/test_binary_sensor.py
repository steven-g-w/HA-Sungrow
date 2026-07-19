"""Tests for the device problem binary sensors."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sungrow_isolarcloud.const import DOMAIN

from .conftest import BATTERY_PS_KEY, ESS_PS_KEY, ESS_REALTIME, PLANT_PS_KEY


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, unique_id: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id("binary_sensor", DOMAIN, unique_id)


async def test_problem_sensors_created_and_off_when_normal(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Devices reporting dev_fault_status get a problem sensor (off = 4)."""
    await _setup(hass, mock_config_entry)

    for ps_key in (ESS_PS_KEY, BATTERY_PS_KEY):
        problem_id = _entity_id(hass, f"{ps_key}_problem")
        assert problem_id is not None
        state = hass.states.get(problem_id)
        assert state.state == "off"
        assert state.attributes["fault_status"] == "normal"
        assert state.attributes["device_status"] == 1

    # The plant pseudo-device reports no dev_fault_status -> no sensor.
    assert _entity_id(hass, f"{PLANT_PS_KEY}_problem") is None


async def test_problem_sensor_turns_on_for_fault(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A fault status flips the problem sensor on at the next poll."""
    await _setup(hass, mock_config_entry)
    problem_id = _entity_id(hass, f"{ESS_PS_KEY}_problem")
    assert hass.states.get(problem_id).state == "off"

    faulted = {
        "device_point_list": [
            {
                "device_point": {
                    **ESS_REALTIME["device_point_list"][0]["device_point"],
                    "dev_fault_status": 1,
                }
            }
        ]
    }

    async def _realtime(device_type: int, ps_keys: list[str], points: list[str]):
        if device_type == 14:
            return faulted
        return {"device_point_list": []}

    mock_api_client.async_get_realtime_data = AsyncMock(side_effect=_realtime)
    await mock_config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(problem_id)
    assert state.state == "on"
    assert state.attributes["fault_status"] == "fault"
