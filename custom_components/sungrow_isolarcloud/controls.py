"""Writable parameter catalog for the Sungrow iSolarCloud integration.

Param codes are the ``param_code`` values of the ``paramSetting`` endpoint,
verified live against a SH10RT hybrid inverter. Read-back responses include
the authoritative name, unit, precision and (for enumerations) the mapping of
labels to raw values (``set_val_name`` / ``set_val_name_val``), which entities
prefer over the fallbacks defined here.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberMode
from homeassistant.const import EntityCategory


@dataclass(frozen=True)
class NumberDef:
    """A numeric device parameter."""

    code: str
    name: str
    min_value: float
    max_value: float
    step: float
    unit: str | None = None
    entity_category: EntityCategory | None = EntityCategory.CONFIG
    mode: NumberMode = NumberMode.BOX


@dataclass(frozen=True)
class SelectDef:
    """An enumerated device parameter."""

    code: str
    name: str
    # Fallback label -> raw value mapping, used if the API read-back does not
    # supply set_val_name/set_val_name_val.
    options: dict[str, str]
    entity_category: EntityCategory | None = None


@dataclass(frozen=True)
class SwitchDef:
    """A binary device parameter."""

    code: str
    name: str
    on_value: str
    off_value: str
    entity_category: EntityCategory | None = EntityCategory.CONFIG


@dataclass(frozen=True)
class TimeDef:
    """A time-of-day parameter split into hour and minute param codes."""

    key: str
    name: str
    hour_code: str
    minute_code: str
    entity_category: EntityCategory | None = EntityCategory.CONFIG


NUMBERS: tuple[NumberDef, ...] = (
    NumberDef("10001", "SOC upper limit", 50, 100, 5, "%", mode=NumberMode.SLIDER),
    NumberDef("10002", "SOC lower limit", 0, 50, 5, "%", mode=NumberMode.SLIDER),
    NumberDef(
        "10005",
        "Charging/discharging power",
        0,
        30,
        0.01,
        "kW",
        entity_category=None,
    ),
    NumberDef(
        "10071",
        "Forced charging target SOC 1",
        0,
        100,
        5,
        "%",
        mode=NumberMode.SLIDER,
    ),
    NumberDef(
        "10076",
        "Forced charging target SOC 2",
        0,
        100,
        5,
        "%",
        mode=NumberMode.SLIDER,
    ),
    NumberDef("10091", "Max charging power", 0, 30, 0.01, "kW"),
    NumberDef("10092", "Max discharging power", 0, 30, 0.01, "kW"),
)

SELECTS: tuple[SelectDef, ...] = (
    SelectDef(
        "10004",
        "Charging/discharging command",
        # Verified live: Charge|Discharge|Stop = 170|187|204.
        {"Charge": "170", "Discharge": "187", "Stop": "204"},
    ),
)

SWITCHES: tuple[SwitchDef, ...] = (
    # Verified live: Disable|Enable = 85|170.
    SwitchDef("10065", "Forced charging", on_value="170", off_value="85"),
)

TIMES: tuple[TimeDef, ...] = (
    TimeDef(
        "forced_charging_1_start", "Forced charging 1 start", "10067", "10068"
    ),
    TimeDef("forced_charging_1_end", "Forced charging 1 end", "10069", "10070"),
    TimeDef(
        "forced_charging_2_start", "Forced charging 2 start", "10072", "10073"
    ),
    TimeDef("forced_charging_2_end", "Forced charging 2 end", "10074", "10075"),
)

ALL_PARAM_CODES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [n.code for n in NUMBERS]
        + [s.code for s in SELECTS]
        + [s.code for s in SWITCHES]
        + [c for t in TIMES for c in (t.hour_code, t.minute_code)]
    )
)
