"""Shared fixtures for the Sungrow iSolarCloud tests.

Response shapes mirror the live iSolarCloud OpenAPI (verified against a real
SH10RT + SBR256 system): getDeviceRealTimeData returns no point_dict, ratio
points (SOC/SOH) are 0..1 fractions, and point names/units come from
getOpenPointInfo (storage_unit = unit of raw values).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
import pytest_socket
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sungrow_isolarcloud.const import (
    CONF_APP_KEY,
    CONF_BASE_URL,
    CONF_PS_ID,
    CONF_SECRET_KEY,
    DEVICE_TYPE_BATTERY,
    DEVICE_TYPE_ENERGY_STORAGE,
    DEVICE_TYPE_PLANT,
    DOMAIN,
)

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

PS_ID = "999001"
PLANT_PS_KEY = f"{PS_ID}_11_0_0"
ESS_PS_KEY = f"{PS_ID}_14_1_1"
BATTERY_PS_KEY = f"{PS_ID}_43_2_1"

ENTRY_DATA = {
    CONF_BASE_URL: "https://augateway.isolarcloud.com",
    CONF_APP_KEY: "test-app-key",
    CONF_SECRET_KEY: "test-secret-key",
    "username": "user@example.com",
    "password": "hunter2",
    CONF_PS_ID: PS_ID,
    "enable_backfill": False,
}

ESS_UUID = "9001"
PS_NAME = "Test Plant"

POWER_STATION_LIST: list[dict[str, Any]] = [
    {
        "ps_id": int(PS_ID),
        "ps_name": PS_NAME,
        "ps_type": 5,
        "today_income": {"unit": "AUD", "value": "1.23"},
        "year_income": {"unit": "AUD", "value": "456"},
        "total_income": {"unit": "AUD", "value": "7890"},
        "co2_reduce": {"unit": "kg", "value": "12.5"},
        "co2_reduce_total": {"unit": "kg", "value": "36437"},
    },
]

DEVICE_LIST: list[dict[str, Any]] = [
    {
        "ps_key": ESS_PS_KEY,
        "ps_id": PS_ID,
        "device_type": DEVICE_TYPE_ENERGY_STORAGE,
        "device_name": "SH10RT",
        "device_sn": "SN-ESS-1",
        "device_model_code": "SH10RT-V112",
        "uuid": ESS_UUID,
    },
    {
        "ps_key": BATTERY_PS_KEY,
        "ps_id": PS_ID,
        "device_type": DEVICE_TYPE_BATTERY,
        "device_name": "Battery1",
        "device_sn": "SN-BAT-1",
        "device_model_code": "SBR256",
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
                "p83252": "0.41",  # battery SoC as fraction
                "p83024": None,  # not reported -> no entity
            }
        }
    ],
    "fail_ps_key_list": [],
}

ESS_REALTIME: dict[str, Any] = {
    "device_point_list": [
        {
            "device_point": {
                "dev_fault_status": 4,
                "dev_status": 1,
                "ps_key": ESS_PS_KEY,
                "p13141": "0.55",  # battery SoC as fraction
                "p13126": "2500",  # charging power W
                "p13150": "0",  # discharging power W
                "p13112": "--",  # not reported -> no entity
            }
        }
    ],
    "fail_ps_key_list": [],
}

BATTERY_REALTIME: dict[str, Any] = {
    "device_point_list": [
        {
            "device_point": {
                "dev_fault_status": 4,
                "dev_status": 1,
                "ps_key": BATTERY_PS_KEY,
                "p58604": "0.44",  # battery SoC as fraction
                "p58601": "523.9",  # battery voltage V
            }
        }
    ],
    "fail_ps_key_list": [],
}

# getOpenPointInfo metadata. Plant (11) deliberately has none so the tests
# cover the catalog fallback path (names, units and SOC scaling).
POINT_META: dict[int, list[dict[str, Any]]] = {
    DEVICE_TYPE_PLANT: [],
    DEVICE_TYPE_ENERGY_STORAGE: [
        {
            "point_id": 13141,
            "point_name": "Battery level (SOC)",
            "storage_unit": "",
            "show_unit": "%",
        },
        {
            "point_id": 13142,
            "point_name": "Battery SOH",
            "storage_unit": "",
            "show_unit": "%",
        },
        {
            "point_id": 13126,
            "point_name": "Battery charging power",
            "storage_unit": "W",
            "show_unit": "kW",
        },
        {
            "point_id": 13150,
            "point_name": "Battery discharging power",
            "storage_unit": "W",
            "show_unit": "kW",
        },
        {
            "point_id": 13112,
            "point_name": "Daily generation",
            "storage_unit": "Wh",
            "show_unit": "kWh",
        },
    ],
    DEVICE_TYPE_BATTERY: [
        {
            "point_id": 58604,
            "point_name": "Battery SOC",
            "storage_unit": "",
            "show_unit": "%",
        },
        {
            "point_id": 58601,
            "point_name": "Battery voltage",
            "storage_unit": "V",
            "show_unit": "V",
        },
    ],
}


# Parameter read-back rows as returned by getParamSettingTask (subset of the
# live response). Window 2 hour/minute codes are deliberately absent so tests
# cover the "entity only created when both codes present" filter.
CONTROL_ROWS: list[dict[str, Any]] = [
    {
        "param_code": "10001",
        "return_value": "100",
        "point_name": "SOC upper limit",
        "unit": "%",
        "set_precision": "0.1",
        "set_val_name": None,
        "set_val_name_val": None,
    },
    {
        "param_code": "10002",
        "return_value": "5",
        "point_name": "SOC lower limit",
        "unit": "%",
        "set_precision": "0.1",
    },
    {
        "param_code": "10004",
        "return_value": "204",
        "point_name": "Charging/discharging command",
        "unit": "",
        "set_val_name": "Charge|Discharge|Stop",
        "set_val_name_val": "170|187|204",
    },
    {
        "param_code": "10005",
        "return_value": "0",
        "point_name": "Charging/discharging power",
        "unit": "kW",
        "set_precision": "0.01",
    },
    {
        "param_code": "10065",
        "return_value": "85",
        "point_name": "Forced charging",
        "set_val_name": "Disable|Enable",
        "set_val_name_val": "85|170",
    },
    {
        "param_code": "10007",
        "return_value": "170",
        "point_name": "Active power limitation",
        "set_val_name": "Enable|Disable",
        "set_val_name_val": "170|85",
    },
    {
        "param_code": "10008",
        "return_value": "100",
        "point_name": "Active power limit ratio",
        "unit": "%",
        "set_precision": "0.1",
    },
    {
        "param_code": "10012",
        "return_value": "85",
        "point_name": "Feed-in power limitation",
        "set_val_name": "Enable|Disable",
        "set_val_name_val": "170|85",
    },
    {
        "param_code": "10013",
        "return_value": "10",
        "point_name": "Feed-in power limit",
        "unit": "kW",
        "set_precision": "0.01",
    },
    {
        "param_code": "10014",
        "return_value": "100",
        "point_name": "Feed-in power limit ratio",
        "unit": "%",
        "set_precision": "0.1",
    },
    {"param_code": "10067", "return_value": "1"},
    {"param_code": "10068", "return_value": "30"},
    {"param_code": "10069", "return_value": "5"},
    {"param_code": "10070", "return_value": "0"},
    {"param_code": "10071", "return_value": "0", "unit": "%"},
    {"param_code": "10091", "return_value": "10.6", "unit": "kW"},
]


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
def entity_registry_enabled_by_default() -> Generator[None]:
    """Force all entities enabled, bypassing registry-disabled defaults."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock(return_value=True),
    ):
        yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry as produced by the config flow."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Sungrow plant {PS_ID}",
        data=dict(ENTRY_DATA),
        unique_id=PS_ID,
    )


@pytest.fixture
def mock_config_entry_control() -> MockConfigEntry:
    """A config entry with device control enabled."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Sungrow plant {PS_ID}",
        data=dict(ENTRY_DATA),
        options={"enable_control": True},
        unique_id=PS_ID,
    )


def _make_client() -> MagicMock:
    """Build a mock SungrowApiClient with canned responses."""
    client = MagicMock()
    client.async_login = AsyncMock()
    client.async_get_power_station_list = AsyncMock(
        return_value=[dict(p) for p in POWER_STATION_LIST]
    )
    client.async_get_device_list = AsyncMock(return_value=list(DEVICE_LIST))

    async def _realtime(
        device_type: int, ps_key_list: list[str], point_ids: list[str]
    ) -> dict[str, Any]:
        if device_type == DEVICE_TYPE_PLANT:
            return PLANT_REALTIME
        if device_type == DEVICE_TYPE_ENERGY_STORAGE:
            return ESS_REALTIME
        if device_type == DEVICE_TYPE_BATTERY:
            return BATTERY_REALTIME
        return {"device_point_list": []}

    client.async_get_realtime_data = AsyncMock(side_effect=_realtime)

    async def _point_info(device_type: int) -> list[dict[str, Any]]:
        return list(POINT_META.get(device_type, []))

    client.async_get_open_point_info = AsyncMock(side_effect=_point_info)

    client.async_param_setting_check = AsyncMock(return_value=True)
    client.async_read_params = AsyncMock(
        return_value=[dict(row) for row in CONTROL_ROWS]
    )

    async def _write_params(uuid: str, values: dict[str, str]) -> list[dict[str, Any]]:
        return [
            {"param_code": code, "set_value": str(value)}
            for code, value in values.items()
        ]

    client.async_write_params = AsyncMock(side_effect=_write_params)

    async def _minute_history(
        ps_key: str, point_ids: list[str], start: str, end: str, interval: int
    ) -> list[dict[str, Any]]:
        """Synthetic history: 100 Wh/h daily-resetting yield + flat readings."""
        frames = []
        ts_format = "%Y%m%d%H%M%S"
        when = datetime.strptime(start, ts_format)
        end_dt = datetime.strptime(end, ts_format)
        while when < end_dt:
            frames.append(
                {
                    "time_stamp": when.strftime(ts_format),
                    "p83022": str(100.0 * when.hour),  # resets at midnight
                    "p83033": "1500",
                    "p83252": "0.5",  # fraction -> 50 % after scaling
                }
            )
            when += timedelta(minutes=30)
        return frames

    client.async_get_minute_history = AsyncMock(side_effect=_minute_history)
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
