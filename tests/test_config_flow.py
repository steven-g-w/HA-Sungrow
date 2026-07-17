"""Tests for the Sungrow iSolarCloud config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sungrow_isolarcloud.api import (
    SungrowApiError,
    SungrowAuthError,
)
from custom_components.sungrow_isolarcloud.const import (
    CONF_PS_ID,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import ENTRY_DATA, PS_ID


async def test_user_flow_success(
    hass: HomeAssistant, mock_flow_client: MagicMock
) -> None:
    """A valid submission creates a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Sungrow plant {PS_ID}"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == PS_ID
    mock_flow_client.async_login.assert_awaited_once()
    mock_flow_client.async_get_device_list.assert_awaited_once_with(PS_ID)


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, mock_flow_client: MagicMock
) -> None:
    """Bad credentials show an invalid_auth error and allow retrying."""
    mock_flow_client.async_login = AsyncMock(side_effect=SungrowAuthError("nope"))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    # Fixing the credentials lets the flow finish.
    mock_flow_client.async_login = AsyncMock()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, mock_flow_client: MagicMock
) -> None:
    """API/connection errors show a cannot_connect error."""
    mock_flow_client.async_get_device_list = AsyncMock(
        side_effect=SungrowApiError("boom")
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate_plant_aborts(
    hass: HomeAssistant,
    mock_flow_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Configuring the same ps_id twice aborts."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant,
    mock_flow_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The reauth flow updates the stored credentials."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": mock_config_entry.entry_id,
        },
        data=dict(mock_config_entry.data),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "app_key": "new-app-key",
            "secret_key": "new-secret",
            "username": "user@example.com",
            "password": "new-password",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["app_key"] == "new-app-key"
    assert mock_config_entry.data["password"] == "new-password"
    # ps_id and base_url are preserved.
    assert mock_config_entry.data[CONF_PS_ID] == PS_ID


async def test_options_flow_sets_scan_interval(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The options flow stores the polling interval."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_SCAN_INTERVAL: 600}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_SCAN_INTERVAL] == 600
