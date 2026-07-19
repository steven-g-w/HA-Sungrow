"""Binary sensor platform: per-device fault/alarm problem indicators.

The realtime responses carry ``dev_fault_status`` alongside the measuring
points (verified live: 1 = fault, 2 = alarm, 4 = normal), so device health
updates on every poll at no extra API cost.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SungrowConfigEntry
from .const import DEVICE_TYPE_PLANT, DOMAIN
from .coordinator import SungrowCoordinator, SungrowDevice

# dev_fault_status values (matches the iSolarCloud API's fault status enum).
FAULT_STATUS_FAULT = 1
FAULT_STATUS_ALARM = 2
FAULT_STATUS_NORMAL = 4

FAULT_STATUS_NAMES = {
    FAULT_STATUS_FAULT: "fault",
    FAULT_STATUS_ALARM: "alarm",
    FAULT_STATUS_NORMAL: "normal",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SungrowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a problem sensor for every device reporting a fault status."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    if data is None:
        return
    entities = []
    for ps_key, device_status in data.status.items():
        device = data.devices.get(ps_key)
        if device is None or device_status.get("dev_fault_status") is None:
            continue
        entities.append(SungrowProblemSensor(coordinator, device))
    async_add_entities(entities)


class SungrowProblemSensor(CoordinatorEntity[SungrowCoordinator], BinarySensorEntity):
    """On when a device reports a fault or alarm."""

    _attr_has_entity_name = True
    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: SungrowCoordinator, device: SungrowDevice
    ) -> None:
        super().__init__(coordinator)
        self._ps_key = device.ps_key
        self._attr_unique_id = f"{device.ps_key}_problem"
        device_info = DeviceInfo(identifiers={(DOMAIN, device.ps_key)})
        if device.device_type != DEVICE_TYPE_PLANT:
            device_info["via_device"] = (DOMAIN, coordinator.plant_ps_key)
        self._attr_device_info = device_info

    def _status(self) -> dict[str, int | None]:
        data = self.coordinator.data
        if data is None:
            return {}
        return data.status.get(self._ps_key, {})

    @property
    def is_on(self) -> bool | None:
        """Return True when the device reports fault or alarm."""
        fault_status = self._status().get("dev_fault_status")
        if fault_status is None:
            return None
        return fault_status in (FAULT_STATUS_FAULT, FAULT_STATUS_ALARM)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw fault and device status."""
        status = self._status()
        fault_status = status.get("dev_fault_status")
        return {
            "fault_status": FAULT_STATUS_NAMES.get(
                fault_status, f"unknown ({fault_status})"
            ),
            "device_status": status.get("dev_status"),
        }

    @property
    def available(self) -> bool:
        """Available while the coordinator reports status for this device."""
        return super().available and bool(self._status())
