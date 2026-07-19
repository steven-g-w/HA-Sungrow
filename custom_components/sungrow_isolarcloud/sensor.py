"""Sensor platform for the Sungrow iSolarCloud integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SungrowConfigEntry
from .const import DEVICE_TYPE_PLANT, DOMAIN
from .coordinator import PointValue, SungrowCoordinator, SungrowDevice
from .points import (
    DEVICE_TYPE_POINTS,
    ECON_DEFS,
    PointDef,
    infer_point_def,
    resolve_unit,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SungrowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    known: set[tuple[str, str]] = set()

    @callback
    def _sync_entities() -> None:
        """Add entities for any point that has produced a value."""
        new_entities: list[SungrowPointSensor] = []
        data = coordinator.data
        if data is None:
            return
        for ps_key, readings in data.points.items():
            device = data.devices.get(ps_key)
            if device is None:
                continue
            for point_id, reading in readings.items():
                if (ps_key, point_id) in known or reading.value is None:
                    continue
                known.add((ps_key, point_id))
                new_entities.append(
                    SungrowPointSensor(coordinator, device, point_id, reading)
                )
        for key, econ in data.economics.items():
            marker = (coordinator.plant_ps_key, f"econ_{key}")
            if marker in known or econ.value is None:
                continue
            known.add(marker)
            new_entities.append(SungrowEconSensor(coordinator, key))
        if new_entities:
            # Plant entities first so the plant device exists in the registry
            # before child devices reference it via via_device.
            new_entities.sort(
                key=lambda entity: entity.device_type != DEVICE_TYPE_PLANT
            )
            _LOGGER.debug("Adding %d Sungrow sensor(s)", len(new_entities))
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class SungrowPointSensor(CoordinatorEntity[SungrowCoordinator], SensorEntity):
    """A sensor for one measuring point of one device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SungrowCoordinator,
        device: SungrowDevice,
        point_id: str,
        reading: PointValue,
    ) -> None:
        super().__init__(coordinator)
        self._ps_key = device.ps_key
        self._point_id = point_id
        self.device_type = device.device_type
        self._attr_unique_id = f"{device.ps_key}_{point_id}"

        catalog = DEVICE_TYPE_POINTS.get(device.device_type, {})
        point_def: PointDef | None = catalog.get(point_id)
        if point_def is None:
            point_def = infer_point_def(point_id, reading.name, reading.unit)

        # Prefer the name/unit reported by the API's point dictionary; fall
        # back to the local catalog.
        self._attr_name = reading.name or point_def.name
        self._attr_native_unit_of_measurement = resolve_unit(
            reading.unit, point_def.unit
        )
        self._attr_device_class = point_def.device_class
        self._attr_state_class = point_def.state_class

        device_info = DeviceInfo(
            identifiers={(DOMAIN, device.ps_key)},
            name=device.name,
            manufacturer="Sungrow",
        )
        if device.model:
            device_info["model"] = str(device.model)
        if device.serial:
            device_info["serial_number"] = str(device.serial)
        if device.device_type != DEVICE_TYPE_PLANT:
            device_info["via_device"] = (DOMAIN, coordinator.plant_ps_key)
        self._attr_device_info = device_info

    @property
    def _reading(self) -> PointValue | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.points.get(self._ps_key, {}).get(self._point_id)

    @property
    def native_value(self) -> float | str | None:
        """Return the current point value."""
        reading = self._reading
        return reading.value if reading else None

    @property
    def available(self) -> bool:
        """Sensor is available while the coordinator succeeds and has data."""
        return super().available and self._reading is not None


class SungrowEconSensor(CoordinatorEntity[SungrowCoordinator], SensorEntity):
    """A financial/environmental plant sensor (income, CO2 reduction)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SungrowCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        definition = ECON_DEFS[key]
        self._attr_unique_id = f"{coordinator.plant_ps_key}_econ_{key}"
        self._attr_name = definition.name
        self._attr_device_class = definition.device_class
        self._attr_state_class = definition.state_class
        econ = (coordinator.data.economics if coordinator.data else {}).get(key)
        # Currency codes (AUD, EUR, ...) pass through resolve_unit unchanged;
        # kg maps to the HA mass unit.
        self._attr_native_unit_of_measurement = resolve_unit(
            econ.unit if econ else None, None
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.plant_ps_key)}
        )
        self.device_type = DEVICE_TYPE_PLANT

    @property
    def native_value(self) -> float | None:
        """Return the current figure."""
        data = self.coordinator.data
        econ = data.economics.get(self._key) if data else None
        return econ.value if econ else None

    @property
    def available(self) -> bool:
        """Available while the plant list provides the figure."""
        data = self.coordinator.data
        return super().available and bool(data and self._key in data.economics)
