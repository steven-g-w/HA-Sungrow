"""Data update coordinator for the Sungrow iSolarCloud integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SungrowApiClient, SungrowApiError, SungrowAuthError
from .const import (
    CONF_PS_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_TYPE_PLANT,
    DOMAIN,
)
from .points import DEVICE_TYPE_POINTS

_LOGGER = logging.getLogger(__name__)


@dataclass
class SungrowDevice:
    """A device (or the plant itself) discovered on iSolarCloud."""

    ps_key: str
    device_type: int
    name: str
    model: str | None = None
    serial: str | None = None


@dataclass
class PointValue:
    """A single measuring point reading."""

    point_id: str
    value: float | str | None
    name: str | None = None
    unit: str | None = None


@dataclass
class SungrowData:
    """Coordinator data: devices and their point readings."""

    devices: dict[str, SungrowDevice] = field(default_factory=dict)
    points: dict[str, dict[str, PointValue]] = field(default_factory=dict)


def _clean_value(raw: Any) -> float | str | None:
    """Normalise a point value returned by the API."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if text in ("", "--", "null", "None"):
        return None
    try:
        return float(text)
    except ValueError:
        return text


class SungrowCoordinator(DataUpdateCoordinator[SungrowData]):
    """Polls iSolarCloud for real-time data of all supported devices."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: SungrowApiClient
    ) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.ps_id: str = str(entry.data[CONF_PS_ID])
        self._devices: dict[str, SungrowDevice] | None = None

    @property
    def plant_ps_key(self) -> str:
        """ps_key of the plant pseudo-device."""
        return f"{self.ps_id}_11_0_0"

    async def _async_discover_devices(self) -> dict[str, SungrowDevice]:
        """Fetch the device list and add the plant pseudo-device."""
        devices: dict[str, SungrowDevice] = {
            self.plant_ps_key: SungrowDevice(
                ps_key=self.plant_ps_key,
                device_type=DEVICE_TYPE_PLANT,
                name=f"Plant {self.ps_id}",
            )
        }
        for raw in await self.client.async_get_device_list(self.ps_id):
            ps_key = raw.get("ps_key")
            device_type = raw.get("device_type")
            if not ps_key or device_type is None:
                continue
            device_type = int(device_type)
            if device_type == DEVICE_TYPE_PLANT:
                continue  # already covered by the pseudo-device
            name = (
                raw.get("device_name")
                or raw.get("type_name")
                or f"Device {ps_key}"
            )
            devices[str(ps_key)] = SungrowDevice(
                ps_key=str(ps_key),
                device_type=device_type,
                name=str(name),
                model=raw.get("device_model_code") or raw.get("device_model"),
                serial=raw.get("device_sn") or raw.get("sn"),
            )
        _LOGGER.debug(
            "Discovered %d device(s) for plant %s: %s",
            len(devices),
            self.ps_id,
            {k: v.device_type for k, v in devices.items()},
        )
        return devices

    async def _async_update_data(self) -> SungrowData:
        try:
            if self._devices is None:
                self._devices = await self._async_discover_devices()

            points: dict[str, dict[str, PointValue]] = {}
            for device_type, catalog in DEVICE_TYPE_POINTS.items():
                ps_keys = [
                    d.ps_key
                    for d in self._devices.values()
                    if d.device_type == device_type
                ]
                if not ps_keys:
                    continue
                result = await self.client.async_get_realtime_data(
                    device_type, ps_keys, list(catalog)
                )
                self._merge_result(points, result)
            return SungrowData(devices=dict(self._devices), points=points)
        except SungrowAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SungrowApiError as err:
            raise UpdateFailed(str(err)) from err

    def _merge_result(
        self, points: dict[str, dict[str, PointValue]], result: dict[str, Any]
    ) -> None:
        """Parse a getDeviceRealTimeData result into the points mapping."""
        # Optional metadata about each point (name/unit), present when the
        # server honours is_get_point_dict.
        meta: dict[str, dict[str, Any]] = {}
        for entry in result.get("point_dict") or []:
            if isinstance(entry, dict) and entry.get("point_id") is not None:
                meta[str(entry["point_id"])] = entry

        for item in result.get("device_point_list") or []:
            device_point = item.get("device_point") if isinstance(item, dict) else None
            if not isinstance(device_point, dict):
                device_point = item if isinstance(item, dict) else None
            if not device_point:
                continue
            ps_key = str(device_point.get("ps_key") or "")
            if not ps_key:
                continue
            readings = points.setdefault(ps_key, {})
            for key, raw in device_point.items():
                if not key.startswith("p") or not key[1:].isdigit():
                    continue
                point_id = key[1:]
                point_meta = meta.get(point_id, {})
                readings[point_id] = PointValue(
                    point_id=point_id,
                    value=_clean_value(raw),
                    name=point_meta.get("point_name"),
                    unit=point_meta.get("point_unit") or point_meta.get("unit"),
                )
