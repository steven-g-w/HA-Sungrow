"""Tests for the control entities (number/select/switch/time)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sungrow_isolarcloud.const import DOMAIN

from .conftest import ESS_PS_KEY, ESS_UUID


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id(platform, DOMAIN, unique_id)


async def test_control_disabled_by_default(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Without opting in, no control entities exist and no control calls run."""
    await _setup(hass, mock_config_entry)
    assert _entity_id(hass, "select", f"{ESS_PS_KEY}_ctl_10004") is None
    assert _entity_id(hass, "number", f"{ESS_PS_KEY}_ctl_10001") is None
    assert _entity_id(hass, "switch", f"{ESS_PS_KEY}_ctl_10065") is None
    mock_api_client.async_param_setting_check.assert_not_awaited()
    mock_api_client.async_read_params.assert_not_awaited()


async def test_control_entities_created_when_enabled(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry_control: MockConfigEntry,
) -> None:
    """Opting in creates entities with values from the parameter read-back."""
    await _setup(hass, mock_config_entry_control)
    mock_api_client.async_param_setting_check.assert_awaited_once_with(ESS_UUID, 0)

    select_id = _entity_id(hass, "select", f"{ESS_PS_KEY}_ctl_10004")
    assert select_id is not None
    select_state = hass.states.get(select_id)
    assert select_state.state == "Stop"
    assert select_state.attributes["options"] == ["Charge", "Discharge", "Stop"]

    number_id = _entity_id(hass, "number", f"{ESS_PS_KEY}_ctl_10001")
    assert number_id is not None
    number_state = hass.states.get(number_id)
    assert number_state.state == "100.0"
    assert number_state.attributes["unit_of_measurement"] == "%"
    # Percentage parameters are sliders with 5 % steps.
    assert number_state.attributes["mode"] == "slider"
    assert number_state.attributes["step"] == 5

    switch_id = _entity_id(hass, "switch", f"{ESS_PS_KEY}_ctl_10065")
    assert switch_id is not None
    assert hass.states.get(switch_id).state == "off"

    time_id = _entity_id(hass, "time", f"{ESS_PS_KEY}_ctl_forced_charging_1_start")
    assert time_id is not None
    assert hass.states.get(time_id).state == "01:30:00"

    # Window 2 codes are absent from the read-back -> no entities.
    assert (
        _entity_id(hass, "time", f"{ESS_PS_KEY}_ctl_forced_charging_2_start") is None
    )


async def test_control_unsupported_device(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry_control: MockConfigEntry,
) -> None:
    """If the support check fails, setup succeeds without control entities."""
    mock_api_client.async_param_setting_check = AsyncMock(return_value=False)
    await _setup(hass, mock_config_entry_control)
    assert _entity_id(hass, "select", f"{ESS_PS_KEY}_ctl_10004") is None
    mock_api_client.async_read_params.assert_not_awaited()


async def test_number_write_scales_by_precision(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry_control: MockConfigEntry,
) -> None:
    """Percent values are written in raw 0.1% units (95% -> "950").

    Verified live: the write API interprets set_value in units of
    set_precision, while read-backs report display units.
    """
    await _setup(hass, mock_config_entry_control)
    number_id = _entity_id(hass, "number", f"{ESS_PS_KEY}_ctl_10001")
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": number_id, "value": 95},
        blocking=True,
    )
    mock_api_client.async_write_params.assert_awaited_once_with(
        ESS_UUID, {"10001": "950"}
    )
    # The cache/state keeps display units.
    assert hass.states.get(number_id).state == "95.0"


async def test_number_write_kw_precision(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry_control: MockConfigEntry,
) -> None:
    """kW values with 0.01 precision are written as raw hundredths."""
    await _setup(hass, mock_config_entry_control)
    number_id = _entity_id(hass, "number", f"{ESS_PS_KEY}_ctl_10005")
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": number_id, "value": 2.5},
        blocking=True,
    )
    mock_api_client.async_write_params.assert_awaited_once_with(
        ESS_UUID, {"10005": "250"}
    )
    assert hass.states.get(number_id).state == "2.5"


async def test_select_write(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry_control: MockConfigEntry,
) -> None:
    """Selecting an option writes the mapped raw value."""
    await _setup(hass, mock_config_entry_control)
    select_id = _entity_id(hass, "select", f"{ESS_PS_KEY}_ctl_10004")
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "Charge"},
        blocking=True,
    )
    mock_api_client.async_write_params.assert_awaited_once_with(
        ESS_UUID, {"10004": "170"}
    )
    assert hass.states.get(select_id).state == "Charge"


async def test_switch_write(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry_control: MockConfigEntry,
) -> None:
    """Turning the switch on writes the enable value."""
    await _setup(hass, mock_config_entry_control)
    switch_id = _entity_id(hass, "switch", f"{ESS_PS_KEY}_ctl_10065")
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": switch_id},
        blocking=True,
    )
    mock_api_client.async_write_params.assert_awaited_once_with(
        ESS_UUID, {"10065": "170"}
    )
    assert hass.states.get(switch_id).state == "on"


async def test_time_write(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry_control: MockConfigEntry,
) -> None:
    """Setting a time writes hour and minute in one task."""
    await _setup(hass, mock_config_entry_control)
    time_id = _entity_id(hass, "time", f"{ESS_PS_KEY}_ctl_forced_charging_1_start")
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": time_id, "time": "02:15:00"},
        blocking=True,
    )
    mock_api_client.async_write_params.assert_awaited_once_with(
        ESS_UUID, {"10067": "2", "10068": "15"}
    )
    assert hass.states.get(time_id).state == "02:15:00"
