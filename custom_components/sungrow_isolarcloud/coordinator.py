"""Data update coordinators for the Sungrow iSolarCloud integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SungrowApiClient, SungrowApiError, SungrowAuthError
from .const import (
    CONF_PS_ID,
    CONF_SCAN_INTERVAL,
    CONTROL_REFRESH_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_TYPE_PLANT,
    DOMAIN,
)
from .controls import ALL_PARAM_CODES
from .points import DEVICE_TYPE_POINTS, PointDef

_LOGGER = logging.getLogger(__name__)


@dataclass
class SungrowDevice:
    """A device (or the plant itself) discovered on iSolarCloud."""

    ps_key: str
    device_type: int
    name: str
    model: str | None = None
    serial: str | None = None
    uuid: str | None = None


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
        # Point metadata (name/units) per device type, fetched once from
        # getOpenPointInfo. Maps device_type -> point_id -> metadata row.
        self._point_meta: dict[int, dict[str, dict[str, Any]]] | None = None

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
            uuid = raw.get("uuid")
            devices[str(ps_key)] = SungrowDevice(
                ps_key=str(ps_key),
                device_type=device_type,
                name=str(name),
                model=raw.get("device_model_code") or raw.get("device_model"),
                serial=raw.get("device_sn") or raw.get("sn"),
                uuid=str(uuid) if uuid is not None else None,
            )
        _LOGGER.debug(
            "Discovered %d device(s) for plant %s: %s",
            len(devices),
            self.ps_id,
            {k: v.device_type for k, v in devices.items()},
        )
        return devices

    async def _async_fetch_point_meta(
        self, device_types: set[int]
    ) -> dict[int, dict[str, dict[str, Any]]]:
        """Fetch authoritative point names/units per device type.

        Failures are tolerated (the catalog fallbacks are used instead), but
        auth errors propagate.
        """
        meta: dict[int, dict[str, dict[str, Any]]] = {}
        for device_type in device_types:
            try:
                rows = await self.client.async_get_open_point_info(device_type)
            except SungrowAuthError:
                raise
            except SungrowApiError as err:
                _LOGGER.warning(
                    "Could not fetch point metadata for device type %s "
                    "(falling back to built-in names/units): %s",
                    device_type,
                    err,
                )
                meta[device_type] = {}
                continue
            meta[device_type] = {
                str(row["point_id"]): row
                for row in rows
                if row.get("point_id") is not None
            }
            _LOGGER.debug(
                "Fetched %d point metadata rows for device type %s",
                len(meta[device_type]),
                device_type,
            )
        return meta

    async def _async_update_data(self) -> SungrowData:
        try:
            if self._devices is None:
                self._devices = await self._async_discover_devices()
            device_types = {
                d.device_type
                for d in self._devices.values()
                if d.device_type in DEVICE_TYPE_POINTS
            }
            if self._point_meta is None:
                self._point_meta = await self._async_fetch_point_meta(device_types)

            points: dict[str, dict[str, PointValue]] = {}
            for device_type in device_types:
                catalog = DEVICE_TYPE_POINTS[device_type]
                ps_keys = [
                    d.ps_key
                    for d in self._devices.values()
                    if d.device_type == device_type
                ]
                result = await self.client.async_get_realtime_data(
                    device_type, ps_keys, list(catalog)
                )
                self._merge_result(points, result, device_type)
            return SungrowData(devices=dict(self._devices), points=points)
        except SungrowAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SungrowApiError as err:
            raise UpdateFailed(str(err)) from err

    def _build_point_value(
        self, point_id: str, raw: Any, device_type: int
    ) -> PointValue:
        """Combine a raw reading with metadata into a PointValue."""
        value = _clean_value(raw)
        meta = (self._point_meta or {}).get(device_type, {}).get(point_id)
        name: str | None = None
        unit: str | None = None
        scale = 1.0
        if meta is not None:
            name = meta.get("point_name")
            storage_unit = (meta.get("storage_unit") or "").strip()
            show_unit = (meta.get("show_unit") or "").strip()
            if not storage_unit and show_unit == "%":
                # Ratio points (SOC, SOH, PR) are 0..1 fractions.
                unit = "%"
                scale = 100.0
            else:
                unit = storage_unit or None
        else:
            catalog_def: PointDef | None = DEVICE_TYPE_POINTS.get(
                device_type, {}
            ).get(point_id)
            if catalog_def is not None:
                scale = catalog_def.scale
        if isinstance(value, float) and scale != 1.0:
            value = round(value * scale, 10)
        return PointValue(point_id=point_id, value=value, name=name, unit=unit)

    def _merge_result(
        self,
        points: dict[str, dict[str, PointValue]],
        result: dict[str, Any],
        device_type: int,
    ) -> None:
        """Parse a getDeviceRealTimeData result into the points mapping."""
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
                readings[point_id] = self._build_point_value(
                    point_id, raw, device_type
                )


class SungrowControlCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Reads (and writes) device parameters via paramSetting tasks.

    Data maps param_code -> the parameter row returned by the API
    (return_value, point_name, unit, set_precision, set_val_name, ...).
    Each refresh spawns a cloud-to-device task, so the interval is long;
    writes update the cache immediately from the task result.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SungrowApiClient,
        device: SungrowDevice,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_control",
            update_interval=timedelta(seconds=CONTROL_REFRESH_INTERVAL),
        )
        self.client = client
        self.device = device
        self.uuid: str = str(device.uuid)
        self.ps_key: str = device.ps_key
        # paramSetting tasks must not overlap (reads and writes share the
        # device channel).
        self._task_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            async with self._task_lock:
                rows = await self.client.async_read_params(
                    self.uuid, list(ALL_PARAM_CODES)
                )
        except SungrowAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SungrowApiError as err:
            raise UpdateFailed(str(err)) from err
        data = dict(self.data or {})
        for row in rows:
            code = row.get("param_code")
            if code is not None:
                data[str(code)] = row
        return data

    async def async_write(self, values: dict[str, str]) -> None:
        """Write parameters to the device and update the cache."""
        _LOGGER.debug("Writing device parameters: %s", values)
        try:
            async with self._task_lock:
                rows = await self.client.async_write_params(self.uuid, values)
        except SungrowAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SungrowApiError as err:
            raise HomeAssistantError(
                f"Failed to write parameters {list(values)}: {err}"
            ) from err
        data = dict(self.data or {})
        for row in rows:
            code = row.get("param_code")
            if code is None:
                continue
            code = str(code)
            merged = {**data.get(code, {}), **row}
            # Write results carry the new value in set_value; keep
            # return_value (what entities read) in sync.
            set_value = row.get("set_value")
            if set_value not in (None, ""):
                merged["return_value"] = set_value
            data[code] = merged
        # Fall back to the requested values for params the result omitted.
        for code, value in values.items():
            row = data.setdefault(str(code), {"param_code": str(code)})
            if str(row.get("return_value", "")) != str(value) and (
                str(code) not in {str(r.get("param_code")) for r in rows}
            ):
                row["return_value"] = str(value)
        self.async_set_updated_data(data)
