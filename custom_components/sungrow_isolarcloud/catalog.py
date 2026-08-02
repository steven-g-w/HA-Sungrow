"""Declarative catalog: loads and validates catalog.yaml.

catalog.yaml is the single source of truth for the iSolarCloud→HA mapping:
which device types exist, which measuring points are polled per type (and
how they classify as HA sensors), which parameters are writable, and the
plant-level financial/environmental fields. The rest of the integration is
agnostic of that mapping and only interprets the loaded ``Catalog``.

The catalog carries *facts*; behavior stays in code — API mechanics, the
runtime override of names/units/scaling from ``getOpenPointInfo``, the
``set_precision`` display↔raw conversion for writes, and the heuristics
below for points that return data but are not cataloged.

Schema reference: docs/declarative-catalog-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from homeassistant.components.number import NumberMode
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import load_yaml_dict
import voluptuous as vol

CATALOG_PATH = Path(__file__).parent / "catalog.yaml"


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
    # "sum" or "mean" opts the point into the one-shot statistics backfill.
    backfill: str | None = None


@dataclass(frozen=True)
class EconDef:
    """A financial/environmental plant sensor (unit comes from the API)."""

    name: str
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None


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
    # Fallback label -> raw value mapping, used if the API read-back does
    # not supply set_val_name/set_val_name_val.
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


@dataclass(frozen=True)
class ControlsDef:
    """The writable parameters of a device type."""

    numbers: tuple[NumberDef, ...] = ()
    selects: tuple[SelectDef, ...] = ()
    switches: tuple[SwitchDef, ...] = ()
    times: tuple[TimeDef, ...] = ()

    @property
    def all_param_codes(self) -> tuple[str, ...]:
        """Every param code, de-duplicated, in catalog order."""
        return tuple(
            dict.fromkeys(
                [n.code for n in self.numbers]
                + [s.code for s in self.selects]
                + [s.code for s in self.switches]
                + [c for t in self.times for c in (t.hour_code, t.minute_code)]
            )
        )


@dataclass(frozen=True)
class DeviceTypeDef:
    """One iSolarCloud device type and everything mapped for it."""

    device_type: int
    key: str
    name: str
    synthetic: bool
    problem_sensor: bool
    points: dict[str, PointDef] = field(default_factory=dict)
    controls: ControlsDef | None = None


@dataclass(frozen=True)
class Catalog:
    """The loaded, validated mapping."""

    version: int
    unit_map: dict[str, str]
    device_types: dict[int, DeviceTypeDef]
    economics: dict[str, EconDef]

    @property
    def synthetic_device_type(self) -> int:
        """The device_type of the plant pseudo-device."""
        return next(
            dt for dt, d in self.device_types.items() if d.synthetic
        )

    def points_for(self, device_type: int) -> dict[str, PointDef]:
        """Points polled for a device type ({} when the type is unknown)."""
        definition = self.device_types.get(device_type)
        return definition.points if definition else {}

    def controls_for(self, device_type: int) -> ControlsDef | None:
        """Writable parameters of a device type, or None."""
        definition = self.device_types.get(device_type)
        return definition.controls if definition else None

    def problem_sensor_for(self, device_type: int) -> bool:
        """Whether devices of this type get a Problem binary sensor."""
        definition = self.device_types.get(device_type)
        return bool(definition and definition.problem_sensor)

    def backfill_points(self, kind: str) -> tuple[str, ...]:
        """Plant point ids opted into backfill ("sum" or "mean")."""
        return tuple(
            point_id
            for point_id, definition in self.points_for(
                self.synthetic_device_type
            ).items()
            if definition.backfill == kind
        )

    def resolve_unit(
        self, api_unit: str | None, fallback: str | None
    ) -> str | None:
        """Map an API-reported unit onto an HA unit, else the fallback."""
        if api_unit:
            api_unit = api_unit.strip()
            if api_unit in self.unit_map:
                return self.unit_map[api_unit]
            if api_unit:
                return api_unit
        return fallback

    def infer_point_def(
        self, point_id: str, name: str | None, unit: str | None
    ) -> PointDef:
        """Build a PointDef for a point that is not in the catalog."""
        resolved = self.resolve_unit(unit, None)
        device_class = _INFER_DEVICE_CLASS.get(resolved or "")
        state_class = (
            SensorStateClass.TOTAL_INCREASING
            if device_class is SensorDeviceClass.ENERGY
            else SensorStateClass.MEASUREMENT
        )
        return PointDef(
            name or f"Point {point_id}", resolved, device_class, state_class
        )


# Unit -> device class heuristics for uncataloged points (units here are the
# resolved HA unit strings, i.e. the values of unit_map).
_INFER_DEVICE_CLASS: dict[str, SensorDeviceClass] = {
    "W": SensorDeviceClass.POWER,
    "kW": SensorDeviceClass.POWER,
    "MW": SensorDeviceClass.POWER,
    "Wh": SensorDeviceClass.ENERGY,
    "kWh": SensorDeviceClass.ENERGY,
    "MWh": SensorDeviceClass.ENERGY,
    "°C": SensorDeviceClass.TEMPERATURE,
    "V": SensorDeviceClass.VOLTAGE,
    "A": SensorDeviceClass.CURRENT,
}


def _enum(enum_cls: type, *, allow_none: bool = False) -> callable:
    """Validator coercing a YAML string onto an HA enum value."""

    def check(value: object) -> object:
        if value is None and allow_none:
            return None
        try:
            return enum_cls(value)
        except ValueError as err:
            raise vol.Invalid(
                f"invalid {enum_cls.__name__}: {value!r}"
            ) from err

    return check


_NUMERIC_KEY = vol.Match(r"^\d+$", msg="key must be a numeric string")
_SLUG = vol.Match(r"^[a-z][a-z0-9_]*$", msg="key must be a slug")

_POINT_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Optional("unit", default=None): vol.Maybe(str),
        vol.Optional("device_class", default=None): _enum(
            SensorDeviceClass, allow_none=True
        ),
        vol.Optional("state_class", default="measurement"): _enum(
            SensorStateClass, allow_none=True
        ),
        vol.Optional("scale", default=1.0): vol.Coerce(float),
        vol.Optional("category", default=None): _enum(
            EntityCategory, allow_none=True
        ),
        vol.Optional("backfill", default=None): vol.Maybe(
            vol.In(["sum", "mean"])
        ),
    }
)

_NUMBER_SCHEMA = vol.Schema(
    {
        vol.Required("code"): _NUMERIC_KEY,
        vol.Required("name"): str,
        vol.Required("min"): vol.Coerce(float),
        vol.Required("max"): vol.Coerce(float),
        vol.Required("step"): vol.Coerce(float),
        vol.Optional("unit", default=None): vol.Maybe(str),
        vol.Optional("mode", default="box"): _enum(NumberMode),
        vol.Optional("category", default="config"): _enum(
            EntityCategory, allow_none=True
        ),
    }
)

_SELECT_SCHEMA = vol.Schema(
    {
        vol.Required("code"): _NUMERIC_KEY,
        vol.Required("name"): str,
        vol.Required("options"): vol.All(
            {str: vol.Coerce(str)}, vol.Length(min=1)
        ),
        vol.Optional("category", default=None): _enum(
            EntityCategory, allow_none=True
        ),
    }
)

_SWITCH_SCHEMA = vol.Schema(
    {
        vol.Required("code"): _NUMERIC_KEY,
        vol.Required("name"): str,
        vol.Required("on_value"): vol.Coerce(str),
        vol.Required("off_value"): vol.Coerce(str),
        vol.Optional("category", default="config"): _enum(
            EntityCategory, allow_none=True
        ),
    }
)

_TIME_SCHEMA = vol.Schema(
    {
        vol.Required("key"): _SLUG,
        vol.Required("name"): str,
        vol.Required("hour_code"): _NUMERIC_KEY,
        vol.Required("minute_code"): _NUMERIC_KEY,
        vol.Optional("category", default="config"): _enum(
            EntityCategory, allow_none=True
        ),
    }
)

_CONTROLS_SCHEMA = vol.Schema(
    {
        vol.Optional("numbers", default=[]): [_NUMBER_SCHEMA],
        vol.Optional("selects", default=[]): [_SELECT_SCHEMA],
        vol.Optional("switches", default=[]): [_SWITCH_SCHEMA],
        vol.Optional("times", default=[]): [_TIME_SCHEMA],
    }
)

_DEVICE_TYPE_SCHEMA = vol.Schema(
    {
        vol.Required("key"): _SLUG,
        vol.Required("name"): str,
        vol.Optional("synthetic", default=False): bool,
        vol.Optional("problem_sensor", default=False): bool,
        vol.Optional("points", default={}): {_NUMERIC_KEY: _POINT_SCHEMA},
        vol.Optional("controls", default=None): vol.Maybe(_CONTROLS_SCHEMA),
    }
)

_ECON_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Optional("device_class", default=None): _enum(
            SensorDeviceClass, allow_none=True
        ),
        vol.Optional("state_class", default="measurement"): _enum(
            SensorStateClass, allow_none=True
        ),
    }
)

CATALOG_SCHEMA = vol.Schema(
    {
        vol.Required("version"): 1,
        vol.Optional("unit_map", default={}): {str: str},
        vol.Required("device_types"): vol.All(
            {_NUMERIC_KEY: _DEVICE_TYPE_SCHEMA}, vol.Length(min=1)
        ),
        vol.Optional("economics", default={}): {_SLUG: _ECON_SCHEMA},
    }
)


class CatalogError(Exception):
    """Raised when catalog.yaml is missing or invalid."""


def _build_controls(raw: dict | None) -> ControlsDef | None:
    if raw is None:
        return None
    return ControlsDef(
        numbers=tuple(
            NumberDef(
                code=n["code"],
                name=n["name"],
                min_value=n["min"],
                max_value=n["max"],
                step=n["step"],
                unit=n["unit"],
                entity_category=n["category"],
                mode=n["mode"],
            )
            for n in raw["numbers"]
        ),
        selects=tuple(
            SelectDef(
                code=s["code"],
                name=s["name"],
                options=dict(s["options"]),
                entity_category=s["category"],
            )
            for s in raw["selects"]
        ),
        switches=tuple(
            SwitchDef(
                code=s["code"],
                name=s["name"],
                on_value=s["on_value"],
                off_value=s["off_value"],
                entity_category=s["category"],
            )
            for s in raw["switches"]
        ),
        times=tuple(
            TimeDef(
                key=t["key"],
                name=t["name"],
                hour_code=t["hour_code"],
                minute_code=t["minute_code"],
                entity_category=t["category"],
            )
            for t in raw["times"]
        ),
    )


def _build(raw: dict) -> Catalog:
    """Turn the schema-validated YAML into a Catalog, with cross-checks."""
    device_types: dict[int, DeviceTypeDef] = {}
    for dt_key, dt_raw in raw["device_types"].items():
        device_type = int(dt_key)
        controls = _build_controls(dt_raw["controls"])
        if controls is not None:
            codes = (
                [n.code for n in controls.numbers]
                + [s.code for s in controls.selects]
                + [s.code for s in controls.switches]
            )
            for t in controls.times:
                codes.extend((t.hour_code, t.minute_code))
            duplicates = {c for c in codes if codes.count(c) > 1}
            if duplicates:
                raise CatalogError(
                    f"device type {device_type}: duplicate param codes "
                    f"{sorted(duplicates)}"
                )
        points = {
            point_id: PointDef(
                name=p["name"],
                unit=p["unit"],
                device_class=p["device_class"],
                state_class=p["state_class"],
                scale=p["scale"],
                entity_category=p["category"],
                backfill=p["backfill"],
            )
            for point_id, p in dt_raw["points"].items()
        }
        if not dt_raw["synthetic"] and any(
            p.backfill for p in points.values()
        ):
            raise CatalogError(
                f"device type {device_type}: backfill is only supported on "
                "the synthetic plant type (the history endpoint is "
                "plant-scoped)"
            )
        device_types[device_type] = DeviceTypeDef(
            device_type=device_type,
            key=dt_raw["key"],
            name=dt_raw["name"],
            synthetic=dt_raw["synthetic"],
            problem_sensor=dt_raw["problem_sensor"],
            points=points,
            controls=controls,
        )

    synthetic = [dt for dt, d in device_types.items() if d.synthetic]
    if len(synthetic) != 1:
        raise CatalogError(
            f"exactly one device type must be synthetic; got {synthetic}"
        )

    economics = {
        key: EconDef(
            name=e["name"],
            device_class=e["device_class"],
            state_class=e["state_class"],
        )
        for key, e in raw["economics"].items()
    }
    return Catalog(
        version=raw["version"],
        unit_map=dict(raw["unit_map"]),
        device_types=device_types,
        economics=economics,
    )


def parse_catalog(raw: dict) -> Catalog:
    """Validate and build a Catalog from raw YAML data."""
    try:
        validated = CATALOG_SCHEMA(raw)
    except vol.Invalid as err:
        raise CatalogError(f"catalog.yaml is invalid: {err}") from err
    return _build(validated)


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """Load, validate and cache the shipped catalog (blocking file IO).

    Every failure surfaces as CatalogError. A missing file in particular
    almost always means an incomplete manual install (only the .py files
    were copied), which is worth saying out loud instead of letting a bare
    FileNotFoundError reach the log.
    """
    try:
        raw = load_yaml_dict(str(CATALOG_PATH))
    except FileNotFoundError as err:
        raise CatalogError(
            f"{CATALOG_PATH.name} is missing from {CATALOG_PATH.parent}. "
            "When installing manually, copy the whole "
            "custom_components/sungrow_isolarcloud folder, not just the "
            "Python files."
        ) from err
    except OSError as err:
        raise CatalogError(f"{CATALOG_PATH.name} could not be read: {err}") from err
    except HomeAssistantError as err:
        raise CatalogError(
            f"{CATALOG_PATH.name} could not be parsed: {err}"
        ) from err
    return parse_catalog(raw)
