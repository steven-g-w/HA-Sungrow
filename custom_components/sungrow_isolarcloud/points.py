"""Measuring point catalog for the Sungrow iSolarCloud integration.

Point ids are the numeric measuring point identifiers used by the
``getDeviceRealTimeData`` endpoint. The catalog below covers the plant
(device_type 11) and hybrid/energy-storage (device_type 14) points that are
most useful in Home Assistant. When the API returns point metadata
(``point_dict``), the name and unit reported by the server take precedence
over the fallbacks defined here.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)

from .const import DEVICE_TYPE_ENERGY_STORAGE, DEVICE_TYPE_PLANT


@dataclass(frozen=True)
class PointDef:
    """Fallback metadata for a measuring point."""

    name: str
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT


def _power(name: str) -> PointDef:
    return PointDef(
        name,
        UnitOfPower.WATT,
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
    )


def _energy(name: str) -> PointDef:
    return PointDef(
        name,
        UnitOfEnergy.WATT_HOUR,
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
    )


# Plant level (device_type 11, ps_key "<ps_id>_11_0_0").
PLANT_POINTS: dict[str, PointDef] = {
    "83022": _energy("Daily yield"),
    "83024": _energy("Total yield"),
    "83033": _power("PV power"),
    "83106": _power("Load power"),
    "83102": _energy("Daily purchased energy"),
    "83105": _energy("Total purchased energy"),
    "83072": _energy("Daily feed-in energy"),
    "83075": _energy("Total feed-in energy"),
    "83118": _energy("Daily load consumption"),
    "83124": _energy("Total load consumption"),
    "83097": _energy("Daily direct energy consumption"),
    "83100": _energy("Total direct energy consumption"),
    "83252": PointDef(
        "Battery level (SoC)",
        PERCENTAGE,
        SensorDeviceClass.BATTERY,
        SensorStateClass.MEASUREMENT,
    ),
    "83129": PointDef(
        "Battery SoC",
        PERCENTAGE,
        SensorDeviceClass.BATTERY,
        SensorStateClass.MEASUREMENT,
    ),
    "83046": _power("PCS total active power"),
    "83052": _power("Total load active power"),
    "83067": _power("Total PV active power"),
    "83549": _power("Grid active power"),
    "83238": _power("Energy storage active power"),
    "83243": _energy("Daily charge energy"),
    "83244": _energy("Daily discharge energy"),
    "83241": _energy("Total charge energy"),
    "83242": _energy("Total discharge energy"),
    "83025": PointDef(
        "Plant equivalent hours",
        UnitOfTime.HOURS,
        None,
        SensorStateClass.MEASUREMENT,
    ),
}

# Hybrid inverter / energy storage system (device_type 14).
ENERGY_STORAGE_POINTS: dict[str, PointDef] = {
    "13003": _power("Total DC power"),
    "13011": _energy("Daily PV yield"),
    "13112": _energy("Daily feed-in energy"),
    "13119": _power("Total load active power"),
    "13121": _power("Total export active power"),
    "13126": _power("Battery charging power"),
    "13141": PointDef(
        "Battery level (SoC)",
        PERCENTAGE,
        SensorDeviceClass.BATTERY,
        SensorStateClass.MEASUREMENT,
    ),
    "13142": PointDef(
        "Battery state of health",
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
    ),
    "13143": PointDef(
        "Battery temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
    ),
    "13149": _power("Purchased power"),
    "13150": _power("Battery discharging power"),
    "13134": _power("Total active power"),
}

# Points queried per device_type.
DEVICE_TYPE_POINTS: dict[int, dict[str, PointDef]] = {
    DEVICE_TYPE_PLANT: PLANT_POINTS,
    DEVICE_TYPE_ENERGY_STORAGE: ENERGY_STORAGE_POINTS,
}

# Mapping of unit strings returned by the API to Home Assistant units.
API_UNIT_MAP: dict[str, str] = {
    "W": UnitOfPower.WATT,
    "kW": UnitOfPower.KILO_WATT,
    "MW": UnitOfPower.MEGA_WATT,
    "Wh": UnitOfEnergy.WATT_HOUR,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "MWh": UnitOfEnergy.MEGA_WATT_HOUR,
    "%": PERCENTAGE,
    "℃": UnitOfTemperature.CELSIUS,
    "°C": UnitOfTemperature.CELSIUS,
    "h": UnitOfTime.HOURS,
}


def resolve_unit(api_unit: str | None, fallback: str | None) -> str | None:
    """Map an API-reported unit onto an HA unit, falling back to the catalog."""
    if api_unit:
        api_unit = api_unit.strip()
        if api_unit in API_UNIT_MAP:
            return API_UNIT_MAP[api_unit]
        if api_unit:
            return api_unit
    return fallback


def infer_point_def(point_id: str, name: str | None, unit: str | None) -> PointDef:
    """Build a PointDef for a point that is not in the catalog."""
    resolved = resolve_unit(unit, None)
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    if resolved in (UnitOfPower.WATT, UnitOfPower.KILO_WATT, UnitOfPower.MEGA_WATT):
        device_class = SensorDeviceClass.POWER
    elif resolved in (
        UnitOfEnergy.WATT_HOUR,
        UnitOfEnergy.KILO_WATT_HOUR,
        UnitOfEnergy.MEGA_WATT_HOUR,
    ):
        device_class = SensorDeviceClass.ENERGY
        state_class = SensorStateClass.TOTAL_INCREASING
    elif resolved == UnitOfTemperature.CELSIUS:
        device_class = SensorDeviceClass.TEMPERATURE
    return PointDef(name or f"Point {point_id}", resolved, device_class, state_class)
