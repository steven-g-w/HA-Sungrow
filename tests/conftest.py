"""Shared fixtures for the Sungrow iSolarCloud tests."""

from __future__ import annotations

from collections.abc import Generator
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_socket
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sungrow_isolarcloud.const import (
    CONF_APP_KEY,
    CONF_BASE_URL,
    CONF_PS_ID,
    CONF_SECRET_KEY,
    DEVICE_TYPE_ENERGY_STORAGE,
    DEVICE_TYPE_PLANT,
    DOMAIN,
)

PS_ID = "999001"
PLANT_PS_KEY = f"{PS_ID}_11_0_0"
ESS_PS_KEY = f"{PS_ID}_14_1_1"

ENTRY_DATA = {
    CONF_BASE_URL: "https://augateway.isolarcloud.com",
    CONF_APP_KEY: "test-app-key",
    CONF_SECRET_KEY: "test-secret-key",
    "username": "user@example.com",
    "password": "hunter2",
    CONF_PS_ID: PS_ID,
}

DEVICE_LIST: list[dict[str, Any]] = [
    {
        "ps_key": ESS_PS_KEY,
        "ps_id": PS_ID,
        "device_type": DEVICE_TYPE_ENERGY_STORAGE,
        "device_name": "SH10RT",
        "device_sn": "SN-ESS-1",
        "device_model_code": "SH10RT",
    },
    # A device type we have no point catalog for; must be ignored gracefully.
    {
        "ps_key": f"{PS_ID}_22_247_1",
        "ps_id": PS_ID,
        "device_type": 22,
        "device_name": "WiNet-S",
        "device_sn": "SN-COM-1",
    },
]

PLANT_REALTIME: dict[str, Any] = {
    "device_point_list": [
        {
            "device_point": {
                "ps_key": PLANT_PS_KEY,
                "p83022": "12345",  # daily yield Wh
                "p83033": "4321.5",  # PV power W
                "p83106": "789",  # load power W
                "p83252": None,  # battery SoC not reported at plant level
            }
        }
    ],
    "point_dict": [
        {"point_id": "83022", "point_name": "Daily Yield", "point_unit": "Wh"},
        {"point_id": "83033", "point_name": "Plant PV Power", "point_unit": "W"},
        {"point_id": "83106", "point_name": "Load Power", "point_unit": "W"},
    ],
}

ESS_REALTIME: dict[str, Any] = {
    "device_point_list": [
        {
            "device_point": {
                "ps_key": ESS_PS_KEY,
                "p13141": "55.0",  # battery SoC %
                "p13126": "2500",  # charging power W
                "p13150": "0",  # discharging power W
                "p13112": "--",  # not reported -> no entity
            }
        }
    ],
    "point_dict": [
        {"point_id": "13141", "point_name": "Battery Level", "point_unit": "%"},
        {
            "point_id": "13126",
            "point_name": "Battery Charging Power",
            "point_unit": "W",
        },
        {
            "point_id": "13150",
            "point_name": "Battery Discharging Power",
            "point_unit": "W",
        },
    ],
}


# pytest-homeassistant-custom-component blocks socket *creation* for every
# test. On Windows the asyncio event loop itself needs a loopback socketpair,
# so no async test can even start. Neutralise the creation block on Windows
# only; the plugin's loopback-only connect guard (socket_allow_hosts) still
# applies, so tests cannot reach the network. aiodns (aiohttp's resolver)
# additionally requires a selector event loop on Windows.
if sys.platform == "win32":
    import asyncio
    from asyncio import events

    pytest_socket.disable_socket = lambda allow_unix_socket=False: None
    # The plugin replaces asyncio.set_event_loop_policy with a no-op after
    # installing HassEventLoopPolicy (proactor-based on Windows), so go
    # through asyncio.events to actually install the selector policy.
    events.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True, scope="session")
def pycares_shutdown_thread_started() -> None:
    """Start pycares' global shutdown thread before any test runs.

    aiohttp's AsyncResolver (aiodns/pycares) lazily starts a one-time daemon
    thread; without this, the HA plugin's thread-leak check fails whichever
    test happens to create the first aiohttp ClientSession.
    """
    try:
        import pycares

        pycares._shutdown_manager.start()
    except (ImportError, AttributeError):  # pragma: no cover
        pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry as produced by the config flow."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Sungrow plant {PS_ID}",
        data=dict(ENTRY_DATA),
        unique_id=PS_ID,
    )


def _make_client() -> MagicMock:
    """Build a mock SungrowApiClient with canned responses."""
    client = MagicMock()
    client.async_login = AsyncMock()
    client.async_get_device_list = AsyncMock(return_value=list(DEVICE_LIST))

    async def _realtime(
        device_type: int, ps_key_list: list[str], point_ids: list[str]
    ) -> dict[str, Any]:
        if device_type == DEVICE_TYPE_PLANT:
            return PLANT_REALTIME
        if device_type == DEVICE_TYPE_ENERGY_STORAGE:
            return ESS_REALTIME
        return {"device_point_list": []}

    client.async_get_realtime_data = AsyncMock(side_effect=_realtime)
    return client


@pytest.fixture
def mock_api_client() -> Generator[MagicMock]:
    """Patch the client used during entry setup."""
    with patch(
        "custom_components.sungrow_isolarcloud.SungrowApiClient"
    ) as mock_cls:
        client = _make_client()
        mock_cls.return_value = client
        yield client


@pytest.fixture
def mock_flow_client() -> Generator[MagicMock]:
    """Patch the client used by the config flow validation."""
    with patch(
        "custom_components.sungrow_isolarcloud.config_flow.SungrowApiClient"
    ) as mock_cls:
        client = _make_client()
        mock_cls.return_value = client
        yield client
