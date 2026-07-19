"""Measuring point catalog for the Sungrow iSolarCloud integration.

The catalog determines *which* points are polled per device type and carries
Home Assistant metadata (device class, state class) plus fallback names and
units. Authoritative names and units are fetched at runtime from the
``getOpenPointInfo`` endpoint (verified live against a SH10RT + SBR256
system); the fallbacks below match that endpoint's output.

Values are returned in ``storage_unit`` (W, Wh, ℃, V, A, …). Ratio points
such as SOC/SOH have an empty storage unit and a ``show_unit`` of ``%`` —
the raw value is a 0..1 fraction and must be scaled by 100.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfMass,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)

from .const import (
    DEVICE_TYPE_BATTERY,
    DEVICE_TYPE_COMM_MODULE,
    DEVICE_TYPE_ENERGY_STORAGE,
    DEVICE_TYPE_PLANT,
)


@dataclass(frozen=True)
class PointDef:
    """HA metadata and fallbacks for a measuring point."""

    name: str
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    # Multiplier applied to the raw value when the API's point metadata is
    # unavailable (e.g. SOC fractions -> percent).
    scale: float = 1.0
    entity_category: EntityCategory | None = None


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


def _soc(name: str) -> PointDef:
    return PointDef(
        name,
        PERCENTAGE,
        SensorDeviceClass.BATTERY,
        SensorStateClass.MEASUREMENT,
        scale=100,
    )


def _ratio(name: str) -> PointDef:
    return PointDef(
        name,
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
        scale=100,
    )


# Plant level (device_type 11, ps_key "<ps_id>_11_0_0").
PLANT_POINTS: dict[str, PointDef] = {
    "83022": _energy("Plant daily yield"),
    "83024": _energy("Plant total yield"),
    "83033": _power("Plant power"),
    "83106": _power("Load power"),
    "83072": _energy("Feed-in energy today"),
    "83075": _energy("Total feed-in energy"),
    "83102": _energy("Energy purchased today"),
    "83105": _energy("Total purchased energy"),
    "83097": _energy("Daily PV energy consumed by loads"),
    "83100": _energy("Total PV energy consumed by loads"),
    "83118": _energy("Daily load consumption"),
    "83124": _energy("Total load consumption"),
    "83252": _soc("Battery level (SOC)"),
    "83322": _energy("ESS daily charge"),
    "83323": _energy("ESS daily discharge"),
    "83324": _energy("ESS total charge"),
    "83325": _energy("ESS total discharge"),
    "83326": _power("ESS active power"),
    "83327": PointDef(
        "ESS remaining energy",
        UnitOfEnergy.WATT_HOUR,
        SensorDeviceClass.ENERGY_STORAGE,
        SensorStateClass.MEASUREMENT,
    ),
    "83328": _power("Grid active power"),
    "83329": _power("PV active power"),
    "83330": _power("Load active power"),
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
    "13011": _power("Total active power"),
    "13112": _energy("Daily generation"),
    "13134": _energy("Total generation"),
    "13116": _energy("Daily PV energy consumed by loads"),
    "13137": _energy("Total PV energy consumed by loads"),
    "13119": _power("Load power"),
    "13121": _power("Feed-in power"),
    "13122": _energy("Feed-in energy today"),
    "13126": _power("Battery charging power"),
    "13150": _power("Battery discharging power"),
    "13141": _soc("Battery level (SOC)"),
    "13142": _ratio("Battery SOH"),
    "13143": PointDef(
        "Battery temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
    ),
    "13149": _power("Grid energy purchasing power"),
    "13147": _energy("Energy purchased today"),
    "13148": _energy("Total purchased energy"),
    "13028": _energy("Battery charge today"),
    "13029": _energy("Battery discharge today"),
    "13035": _energy("Total battery discharge"),
    "13199": _energy("Daily load consumption"),
    "13130": _energy("Total load consumption"),
}

# Battery / BMS (device_type 43).
BATTERY_POINTS: dict[str, PointDef] = {
    "58601": PointDef(
        "Battery voltage",
        UnitOfElectricPotential.VOLT,
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
    ),
    "58602": PointDef(
        "Battery current",
        UnitOfElectricCurrent.AMPERE,
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
    ),
    "58603": PointDef(
        "Battery temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
    ),
    "58604": _soc("Battery SOC"),
    "58605": _ratio("Battery health"),
    "58606": _energy("Total battery charge"),
    "58607": _energy("Total battery discharge"),
    # Cell-level diagnostics: voltage spread between the strongest and
    # weakest cell is an early indicator of pack degradation.
    "58610": PointDef(
        "Max cell voltage",
        UnitOfElectricPotential.MILLIVOLT,
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "58612": PointDef(
        "Min cell voltage",
        UnitOfElectricPotential.MILLIVOLT,
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "58614": PointDef(
        "Max module temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "58616": PointDef(
        "Min module temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}

# Communication module (device_type 22, WiNet-S / cellular dongles).
# Verified live: WLAN signal strength reports dBm (e.g. -53). Points a
# given module doesn't report simply create no entities.
COMM_MODULE_POINTS: dict[str, PointDef] = {
    "23014": PointDef(
        "WLAN signal strength",
        SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        SensorDeviceClass.SIGNAL_STRENGTH,
        SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Cellular signal; unit/format varies by module, so no device class or
    # state class (some modules may report non-numeric values).
    "23001": PointDef(
        "Wireless signal strength",
        None,
        None,
        None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "23006": PointDef(
        "Restart count",
        None,
        None,
        SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}

# Points queried per device_type.
DEVICE_TYPE_POINTS: dict[int, dict[str, PointDef]] = {
    DEVICE_TYPE_PLANT: PLANT_POINTS,
    DEVICE_TYPE_ENERGY_STORAGE: ENERGY_STORAGE_POINTS,
    DEVICE_TYPE_BATTERY: BATTERY_POINTS,
    DEVICE_TYPE_COMM_MODULE: COMM_MODULE_POINTS,
}

@dataclass(frozen=True)
class EconDef:
    """Metadata for a financial/environmental plant sensor.

    Values come from getPowerStationList fields shaped like
    ``{"unit": "AUD", "value": "14062"}``; the unit (currency or kg) is
    taken from the API response.
    """

    name: str
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None


ECON_DEFS: dict[str, EconDef] = {
    "today_income": EconDef(
        "Income today", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL
    ),
    "year_income": EconDef(
        "Income this year", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL
    ),
    "total_income": EconDef(
        "Total income", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL
    ),
    "co2_reduce": EconDef(
        "CO2 reduction today",
        SensorDeviceClass.WEIGHT,
        SensorStateClass.TOTAL_INCREASING,
    ),
    "co2_reduce_total": EconDef(
        "Total CO2 reduction",
        SensorDeviceClass.WEIGHT,
        SensorStateClass.TOTAL_INCREASING,
    ),
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
    "H": UnitOfTime.HOURS,
    "V": UnitOfElectricPotential.VOLT,
    "mV": UnitOfElectricPotential.MILLIVOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "kg": UnitOfMass.KILOGRAMS,
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
    elif resolved == UnitOfElectricPotential.VOLT:
        device_class = SensorDeviceClass.VOLTAGE
    elif resolved == UnitOfElectricCurrent.AMPERE:
        device_class = SensorDeviceClass.CURRENT
    return PointDef(name or f"Point {point_id}", resolved, device_class, state_class)
