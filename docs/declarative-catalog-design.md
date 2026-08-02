# Design: a declarative catalog as the single source of truth

**Status:** proposed
**Scope:** `custom_components/sungrow_isolarcloud`

## Summary

Today the mapping "iSolarCloud API → HA devices/entities" is spread across
several Python modules. This document proposes consolidating it into **one
declarative configuration file** (`catalog.yaml`) shipped inside the
integration, with a small typed loader. All platform and coordinator code
becomes agnostic of *which* device types, points and parameters exist — it
only interprets the catalog. Adding support for a new sensor, control or
whole device type then means **editing one YAML file, zero Python**.

Feasibility verdict: **yes, with a clear boundary.** The existing code
already treats the catalogs as opaque lookup tables (the coordinator
iterates `DEVICE_TYPE_POINTS`, the platforms iterate `NUMBERS`/`SELECTS`/…),
so the data can move out of Python without changing any algorithm. What must
*stay* in code is behavior: API mechanics, ratio scaling, `set_precision`
conversion, entity lifecycles, and heuristics for uncataloged points.

## Current state (what would move)

| Data | Lives today | Consumed by |
|---|---|---|
| Per-device-type point catalogs (point_id → name, unit, device/state class, scale, category) | `points.py` `PLANT_POINTS` / `ENERGY_STORAGE_POINTS` / `BATTERY_POINTS` / `COMM_MODULE_POINTS` | coordinator (what to poll), sensor (how to classify) |
| Device-type registry | `points.py` `DEVICE_TYPE_POINTS`, `const.py` `DEVICE_TYPE_*` | coordinator, `__init__` |
| Economics fields (income/CO2) | `points.py` `ECON_DEFS` | coordinator, sensor |
| API-unit → HA-unit map | `points.py` `API_UNIT_MAP` | sensor, backfill |
| Writable parameters (numbers/selects/switches/times) | `controls.py` `NUMBERS` / `SELECTS` / `SWITCHES` / `TIMES` / `ALL_PARAM_CODES` | control coordinator, number/select/switch/time platforms |
| Backfill point selection (sum vs mean) | `backfill.py` `ENERGY_POINTS` / `MEASUREMENT_POINTS` | backfill |
| Fault-status enum | `binary_sensor.py` `FAULT_STATUS_*` | binary_sensor |

What stays in code (behavior, not mapping):

- API client mechanics (`api.py`): auth, retries, task polling, chunking
- Value cleaning and ratio detection from `getOpenPointInfo` metadata
  (`storage_unit`/`show_unit` → ×100) — driven by the *live API*, not config
- `set_precision` display↔raw conversion for writes
- `infer_point_def()` heuristics for points that return data but are not in
  the catalog
- Entity lifecycles: lazy sensor creation, disabled-by-default controls,
  `via_device` wiring, unique-id construction

## Goals

1. One file describes every device type, point and parameter the
   integration knows about.
2. Platform/coordinator code contains **no** point IDs, param codes or
   device-type numbers.
3. Adding a new point/control/device type requires only a catalog edit.
4. Identical runtime behavior after migration: same unique IDs, same entity
   names, same units, same polling.
5. Fail fast: an invalid catalog aborts setup with a precise error message.

## Non-goals

- User-editable mapping in `/config` (possible later; see *Future work*).
- Changing what the API metadata (`getOpenPointInfo`, param read-backs)
  overrides at runtime — live names/units keep winning over the catalog.
- Describing *behavior* in YAML (no expressions, no conditionals).

## Proposed design

### File location and format

`custom_components/sungrow_isolarcloud/catalog.yaml`, shipped with the
integration (add `catalog.yaml` to the package; HACS/manifest need no
change — non-Python files in the component directory are installed as-is).

YAML over JSON: the current Python catalogs carry many inline comments that
document live-verified facts ("Charge|Discharge|Stop = 170|187|204,
verified on SH10RT"); losing them would hurt maintainability, and JSON has
no comments. HA bundles PyYAML, and `homeassistant.util.yaml.load_yaml`
is the sanctioned loader. The file is read **once per config entry setup**
in an executor job (file IO must not block the event loop) and cached in
`hass.data` so multi-plant installs parse it once.

### Loader

New module `catalog.py`:

- Frozen dataclasses mirroring today's `PointDef`, `NumberDef`, `SelectDef`,
  `SwitchDef`, `TimeDef`, `EconDef`, plus new `DeviceTypeDef` and `Catalog`
  roots.
- A voluptuous schema validates the raw YAML; enum-valued strings are
  resolved against the real HA enums (`SensorDeviceClass("energy")`,
  `SensorStateClass("total_increasing")`, `EntityCategory("diagnostic")`,
  `NumberMode("slider")`) so a typo like `state_class: total_increasin`
  fails setup with a line-referenced error instead of silently degrading.
- The loaded `Catalog` object exposes the same shapes consumers use today:
  `catalog.points_for(device_type)`, `catalog.device_types`,
  `catalog.controls.all_param_codes`, `catalog.unit_map`,
  `catalog.economics`, `catalog.backfill_points`.

### Proposed schema

Top-level keys: `version`, `unit_map`, `device_types`, `economics`.

```yaml
# catalog.yaml — single source of truth for the API→HA mapping.
version: 1

# API unit string -> HA unit constant (values are the literal HA unit
# strings; unmapped API units pass through verbatim, e.g. currency codes).
unit_map:
  "W": "W"
  "kW": "kW"
  "Wh": "Wh"
  "kWh": "kWh"
  "%": "%"
  "℃": "°C"
  "°C": "°C"
  "h": "h"
  "V": "V"
  "mV": "mV"
  "A": "A"
  "kg": "kg"

# Keyed by iSolarCloud device_type number (string keys — YAML ints would
# work too, but strings keep leading-zero safety and match API payloads).
device_types:
  "11":
    key: plant                # stable slug, used in logs/diagnostics
    name: Plant
    synthetic: true           # pseudo-device: built from ps_id as
                              # "<ps_id>_11_0_0", not from getDeviceList
    problem_sensor: true      # create the fault/alarm binary_sensor
    points:
      "83022":
        name: Plant daily yield
        unit: Wh
        device_class: energy          # SensorDeviceClass value
        state_class: total_increasing # SensorStateClass value
        backfill: sum                 # opt-in to history import: sum|mean
      "83033":
        name: Plant power
        unit: W
        device_class: power
        state_class: measurement
        backfill: mean
      "83252":
        name: Battery level (SOC)
        unit: "%"
        device_class: battery
        state_class: measurement
        scale: 100            # fallback ×100 when getOpenPointInfo is down
        backfill: mean
      # ... remaining plant points

  "14":
    key: energy_storage
    name: Hybrid inverter / energy storage
    problem_sensor: true
    points:
      "13126":
        name: Battery charging power
        unit: W
        device_class: power
        state_class: measurement
      "13142":
        name: Battery SOH
        unit: "%"
        state_class: measurement
        scale: 100
      # ... remaining ESS points

    # Writable parameters (paramSetting API). Presence of a `controls`
    # block marks this device type as controllable; the runtime still
    # gates on the enable_control option + paramSettingCheck + read-back.
    controls:
      numbers:
        - code: "10001"
          name: SOC upper limit
          min: 50
          max: 100
          step: 5
          unit: "%"
          mode: slider          # NumberMode; default box
          category: config      # EntityCategory; `null` = primary control
        - code: "10005"
          name: Charging/discharging power
          min: 0
          max: 30
          step: 0.01
          unit: kW
          category: null
        # ...
      selects:
        - code: "10004"
          name: Charging/discharging command
          options:              # fallback label->raw map; API's
            Charge: "170"       # set_val_name(_val) still wins at runtime
            Discharge: "187"
            Stop: "204"
      switches:
        - code: "10065"
          name: Forced charging
          on_value: "170"
          off_value: "85"
      times:
        - key: forced_charging_1_start
          name: Forced charging 1 start
          hour_code: "10067"
          minute_code: "10068"
        # ...

  "43":
    key: battery
    name: Battery / BMS
    problem_sensor: true
    points:
      "58604": { name: Battery SOC, unit: "%", device_class: battery,
                 state_class: measurement, scale: 100 }
      "58610": { name: Max cell voltage, unit: mV, device_class: voltage,
                 state_class: measurement, category: diagnostic }
      # ...

  "22":
    key: comm_module
    name: Communication module
    problem_sensor: true
    points:
      "23014": { name: WLAN signal strength, unit: dBm,
                 device_class: signal_strength, state_class: measurement,
                 category: diagnostic }
      "23001": { name: Wireless signal strength, category: diagnostic,
                 state_class: null }   # explicit null: non-numeric values
      "23006": { name: Restart count, state_class: total_increasing,
                 category: diagnostic }

# Plant-list financial/environmental fields (getPowerStationList rows
# shaped {"unit": ..., "value": ...}). Unit always comes from the API.
economics:
  today_income:     { name: Income today,        device_class: monetary, state_class: total }
  year_income:      { name: Income this year,    device_class: monetary, state_class: total }
  total_income:     { name: Total income,        device_class: monetary, state_class: total }
  co2_reduce:       { name: CO2 reduction today, device_class: weight,   state_class: total_increasing }
  co2_reduce_total: { name: Total CO2 reduction, device_class: weight,   state_class: total_increasing }
```

Field reference (points):

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | str | required | Fallback entity name (API `point_name` wins) |
| `unit` | str/null | `null` | Fallback unit (API `storage_unit` wins) |
| `device_class` | str/null | `null` | `SensorDeviceClass` value |
| `state_class` | str/null | `measurement` | `SensorStateClass` value; explicit `null` disables |
| `scale` | number | `1.0` | Fallback multiplier when point metadata is unavailable |
| `category` | str/null | `null` | `EntityCategory` value (`diagnostic`/`config`) |
| `backfill` | `sum`/`mean` | absent | Include in the one-shot statistics import |

Validation rules enforced by the loader:

- `device_types` keys and point keys must be numeric strings; duplicate
  param codes across `numbers`/`selects`/`switches`/`times` are rejected.
- Exactly one device type may set `synthetic: true` (the plant).
- `backfill` is only valid on the synthetic plant type (the history
  endpoint is plant-scoped today) — relaxing this later is a loader change,
  not a schema change.
- Every enum string must round-trip through its HA enum.

### Code changes per consumer

Each consumer swaps its import of a Python constant for a `Catalog` lookup;
no logic changes:

| Consumer | Today | After |
|---|---|---|
| `__init__.py` | — | load catalog once, stash on `entry.runtime_data` |
| `coordinator.py` | `DEVICE_TYPE_POINTS[dt]`, `ECON_DEFS` | `catalog.points_for(dt)`, `catalog.economics` |
| `sensor.py` | `DEVICE_TYPE_POINTS`, `ECON_DEFS`, `resolve_unit` | same lookups on `catalog`; `resolve_unit` takes `catalog.unit_map` |
| `binary_sensor.py` | implicit (any device with status) | additionally gated by `problem_sensor: true` |
| `number/select/switch/time.py` | `NUMBERS`/`SELECTS`/`SWITCHES`/`TIMES` | `catalog.controls_for(dt).numbers` etc. |
| control setup in `__init__.py` | hardcoded `DEVICE_TYPE_ENERGY_STORAGE` | "first device whose type has a `controls` block" |
| `backfill.py` | `ENERGY_POINTS`/`MEASUREMENT_POINTS` | `catalog.backfill_points` (`sum` vs `mean` from the field) |
| `points.py` / `controls.py` | catalogs + helpers | deleted; `PointDef` dataclass, `resolve_unit`, `infer_point_def` move to `catalog.py` |

`const.py` keeps only true constants (domain, defaults, intervals, API
paths); the `DEVICE_TYPE_*` numbers disappear from code entirely.

### Identity and migration safety

Unique IDs are derived exclusively from API identifiers
(`{ps_key}_{point_id}`, `{ps_key}_ctl_{code}`, `{plant}_econ_{key}`,
`{ps_key}_problem`) — none of them embed catalog data. Moving the catalog
to YAML therefore **cannot** orphan existing entities, history or Energy
dashboard configuration, as long as point IDs / param codes are copied
verbatim. Names may only change where the API metadata was already
overriding the catalog (no visible change).

## Migration plan

1. **Generate** `catalog.yaml` mechanically from the current Python
   catalogs (a throwaway script serializes `DEVICE_TYPE_POINTS`,
   `ECON_DEFS`, `API_UNIT_MAP`, `NUMBERS`, `SELECTS`, `SWITCHES`, `TIMES`,
   `ENERGY_POINTS`/`MEASUREMENT_POINTS`), carrying comments over by hand.
2. **Add the loader** (`catalog.py` + voluptuous schema) with a **parity
   test**: load the YAML and assert deep-equality against the existing
   Python constants. This test is the migration's safety net.
3. **Swap consumers** one platform at a time (sensor → binary_sensor →
   controls → backfill), keeping the parity test green.
4. **Delete** the Python catalogs and the parity test's old-side imports;
   keep a schema-validation test (the catalog must load cleanly) and a
   golden test asserting a few known entities' attributes.

Each step is releasable; the riskiest diff (step 3) contains no data,
only mechanical lookups.

## Testing

- `test_catalog.py`: YAML loads; schema violations raise with useful
  messages (bad enum, duplicate code, non-numeric point id).
- Existing platform tests keep passing unchanged — they assert entity
  attributes, which is exactly the invariant the migration must preserve.
- Transitional parity test (step 2–3), deleted at step 4.

## Future work (enabled by this design, not part of it)

- **User overrides:** merge an optional
  `/config/sungrow_isolarcloud/catalog.yaml` over the shipped one, so
  users can add points for unsupported hardware without a fork — the
  strongest argument for this whole design.
- **Per-model catalogs:** the schema's `device_types` map could gain
  model-conditional sections if Sungrow models diverge on param codes.
- **Contributed device types:** a PR adding e.g. string inverters
  (device_type 1) or meters becomes a YAML-only change reviewable by
  non-Python contributors.

## Alternatives considered

- **JSON instead of YAML** — no comments; the live-verified annotations in
  today's catalogs are worth keeping next to the data. Rejected.
- **Python `EntityDescription` tuples (HA-core style)** — idiomatic, but
  keeps the mapping in code and fails goal 3 (YAML-only contributions,
  future user overrides). Rejected.
- **Fetch the whole catalog from `getOpenPointInfo` at runtime** — the API
  lists points but not HA semantics (device/state class, control limits,
  enum labels); a local catalog remains necessary. The runtime metadata
  keeps its current role: overriding names/units/scaling.
