# Contributing

Thanks for helping improve HA-Sungrow. This guide covers the development
setup, how to run the tests, and — most usefully — how to **add support
for new sensors, controls and device types**, which is normally a
config-only change.

## Table of contents

- [Development setup](#development-setup)
- [Running the tests](#running-the-tests)
- [Live smoke test](#live-smoke-test-against-your-own-system)
- [Adding a new sensor](#adding-a-new-sensor)
- [Adding a new control](#adding-a-new-control)
- [Adding a whole new device type](#adding-a-whole-new-device-type)
- [Project layout](#project-layout)
- [Coding conventions](#coding-conventions)
- [Submitting a pull request](#submitting-a-pull-request)
- [Cutting a release](#cutting-a-release-maintainers)

## Development setup

Python **3.13** is what CI uses; 3.12+ should work locally.

```sh
git clone https://github.com/steven-g-w/HA-Sungrow
cd HA-Sungrow
python -m venv .venv
# Linux/macOS:  source .venv/bin/activate
# Windows:      .venv\Scripts\activate
pip install -r requirements_test.txt
```

That pulls in
[pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component),
which brings its own pinned Home Assistant — you do **not** need a
separate HA install to develop or run the tests.

## Running the tests

```sh
pytest              # whole suite
pytest tests/test_catalog.py -q     # just the catalog validation
```

Two test files are worth knowing about before you change anything:

- **`tests/test_catalog.py`** — validates the shipped `catalog.yaml` and
  the loader's error handling. If you edit the catalog and get a
  `CatalogError`, this is where the rules live.
- **`tests/test_entity_snapshot.py`** — a **golden snapshot** of every
  entity and device the integration creates (unique ID, name, device
  class, state class, unit, category, state). It is the safety net that
  proves a refactor didn't silently change anyone's entities.

When you *intentionally* add or change entities, the snapshot will fail.
Regenerate it and **review the diff** before committing:

```sh
UPDATE_SNAPSHOT=1 pytest tests/test_entity_snapshot.py
git diff tests/fixtures/entity_snapshot.json
```

The diff should contain only what you meant to change. Note the snapshot
deliberately does not pin `entity_id` slugs — those depend on
platform-setup ordering for identically-named entities; identity is the
`unique_id`.

CI (GitHub Actions) runs the test suite,
[hassfest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
and HACS validation on every push.

## Live smoke test against your own system

`scripts/live_smoke_test.py` exercises the real API end-to-end (login,
device discovery, point metadata, live values) and prints every point
your hardware reports next to its catalog name — the fastest way to
discover point IDs worth adding.

It reads credentials from a git-ignored `.env` file in the repo root
(see [getting-credentials.md](getting-credentials.md) for how to obtain
these):

```env
BASE_URL=https://augateway.isolarcloud.com
APP_KEY=...
SECRET_KEY=...
USERNAME=...
PASSWORD=...
PS_ID=...
```

```sh
python scripts/live_smoke_test.py
```

Points your system reports that aren't in the catalog are printed as
`<not in catalog>` — those are exactly the candidates for the next
section.

> [!WARNING]
> Never paste real keys, tokens, plant IDs or account names into issues,
> pull requests or test fixtures. `.env` is git-ignored; keep it that way.

## Adding a new sensor

All mapping lives in **`custom_components/sungrow_isolarcloud/catalog.yaml`**
— the single source of truth. No Python changes are needed.

1. Find the point ID with the live smoke test (or the developer portal's
   `getOpenPointInfo` docs).
2. Add it under the right `device_types.<type>.points` block:

```yaml
device_types:
  "14":                       # hybrid inverter / ESS
    points:
      "13121":
        name: Feed-in power   # fallback; the API's point_name wins at runtime
        unit: W               # fallback; the API's storage_unit wins
        device_class: power   # SensorDeviceClass value — API never supplies this
        state_class: measurement
```

Field reference:

| Field | Default | Notes |
|---|---|---|
| `name` | required | Fallback only — `getOpenPointInfo`'s `point_name` takes precedence |
| `unit` | `null` | Fallback only — the API's `storage_unit` takes precedence |
| `device_class` | `null` | HA `SensorDeviceClass`; never supplied by the API |
| `state_class` | `measurement` | Use `total_increasing` for energy counters; explicit `null` for non-numeric |
| `scale` | `1.0` | Fallback multiplier when point metadata is unavailable (e.g. `100` for 0..1 ratios) |
| `category` | `null` | `diagnostic` or `config` to keep it out of the main device view |
| `backfill` | absent | `sum`/`mean` — plant points only, see below |

3. Run `pytest`, regenerate the snapshot, review the diff.

A few conventions worth following:

- **Energy counters** get `device_class: energy` +
  `state_class: total_increasing` so they work in the Energy dashboard.
- **Ratio points** (SOC, SOH, PR) come back as 0..1 fractions — set
  `unit: "%"` and `scale: 100`. At runtime the scaling is detected from
  the API metadata (`storage_unit` empty + `show_unit` `%`); `scale` is
  the fallback for when that metadata is unavailable.
- **Diagnostics** (signal strength, cell voltages, restart counts) should
  set `category: diagnostic`.
- `backfill: sum` (daily-resetting energy counters) or `backfill: mean`
  (instantaneous readings) opts a point into the one-shot statistics
  import. Only valid on the plant type — the history endpoint is
  plant-scoped, and the loader rejects it elsewhere.

## Adding a new control

⚠️ Controls **write to physical hardware**. Only add parameters you have
verified on real equipment, and say which model you verified against in
the PR.

Add to the device type's `controls` block. Four entity kinds are
supported:

```yaml
    controls:
      numbers:
        - code: "10001"
          name: SOC upper limit
          min: 50
          max: 100
          step: 5
          unit: "%"
          mode: slider        # or box (default)
          category: config    # null puts it in the main device controls
      selects:
        - code: "10004"
          name: Charging/discharging command
          options:            # fallback; the API's set_val_name wins
            Charge: "170"
            Discharge: "187"
            Stop: "204"
      switches:
        - code: "10065"
          name: Forced charging
          on_value: "170"
          off_value: "85"
      times:                  # a time-of-day split across two param codes
        - key: forced_charging_1_start
          name: Forced charging 1 start
          hour_code: "10067"
          minute_code: "10068"
```

Things the runtime handles for you, so don't encode them in the catalog:

- **Unit conversion on write.** The API writes in units of
  `set_precision` (0.1 for SOC percentages, 0.01 for kW). Declare `min`,
  `max` and `step` in *display* units; the coordinator converts.
- **Enum labels.** If the read-back supplies `set_val_name` /
  `set_val_name_val`, those win over your `options` map.
- **Gating.** Control entities appear only when the user enables control,
  the device passes `paramSettingCheck`, and the param code comes back in
  the read-back — and they are registered **disabled by default**, so each
  must be explicitly enabled.

## Adding a whole new device type

Also config-only — discovery and entity creation are generic. Add a
top-level entry keyed by the iSolarCloud `device_type` number:

```yaml
device_types:
  "1":                        # string inverter
    key: string_inverter      # stable slug for logs/diagnostics
    name: String inverter
    problem_sensor: true      # create the fault/alarm binary sensor
    points:
      "13003": { name: Total DC power, unit: W, device_class: power,
                 state_class: measurement }
```

`synthetic: true` marks the plant pseudo-device (built from `ps_id`
rather than the device list) — exactly one device type may set it, so
you won't be adding another.

## Project layout

```
custom_components/sungrow_isolarcloud/
  catalog.yaml     ← the mapping: points, controls, units, economics
  catalog.py       ← loader + schema validation + typed dataclasses
  api.py           ← iSolarCloud OpenAPI client (auth, retries, tasks)
  coordinator.py   ← polling, value cleaning, scaling, parameter writes
  sensor.py, binary_sensor.py, number.py, select.py, switch.py, time.py
  backfill.py      ← one-shot statistics import
  config_flow.py   ← UI setup and options
docs/              ← this guide, credentials guide, design docs, release notes
scripts/           ← live_smoke_test.py
tests/
```

The important boundary: **`catalog.yaml` holds facts, code holds
behavior.** API mechanics, ratio scaling, `set_precision` conversion,
entity lifecycles and the heuristics for uncataloged points stay in
Python. See
[declarative-catalog-design.md](declarative-catalog-design.md) for the
full rationale and schema.

## Coding conventions

- Match the surrounding style: 4-space indent, double quotes, ~79-column
  lines, `from __future__ import annotations`, full type hints.
- Every module, class and public function gets a docstring.
- Comments explain **why**, not what — and when a value was confirmed
  against real hardware, say so (e.g. `# Verified live: Charge|Discharge|
  Stop = 170|187|204`). Those annotations are why the catalog is YAML
  rather than JSON.
- Keep `pyflakes` clean: `python -m pyflakes custom_components tests scripts`.
- Never log or commit credentials, tokens or plant IDs.

## Submitting a pull request

1. Branch off `main`.
2. Make the change; add or update tests.
3. Run `pytest` and regenerate the entity snapshot if entities changed,
   reviewing the diff.
4. Open a PR describing **what hardware you verified against** (model,
   firmware if relevant) for any catalog or control change — this project
   depends on live verification, since Sungrow's API docs don't cover HA
   semantics.

Bug reports are welcome too: include your inverter/battery model, the
Home Assistant version, and the relevant log lines with credentials
redacted.

## Cutting a release (maintainers)

1. Bump `version` in `custom_components/sungrow_isolarcloud/manifest.json`.
2. Write release notes at `docs/releases/vX.Y.Z.md` — lead with any
   breaking or behavior-changing warning.
3. Commit and push to `main`.
4. Run the **Release** workflow (Actions → Release → Run workflow) with
   the tag `vX.Y.Z`. It verifies the manifest version matches the tag,
   then creates the tag and GitHub release from your notes file.
