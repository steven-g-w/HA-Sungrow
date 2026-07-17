# HA-Sungrow — Sungrow iSolarCloud integration for Home Assistant

<p align="center">
  <img src="images/logo.png" alt="HA-Sungrow logo" width="240">
</p>

<p align="center">
  <a href="https://github.com/steven-g-w/HA-Sungrow/releases/latest"><img src="https://img.shields.io/github/v/release/steven-g-w/HA-Sungrow" alt="Latest release"></a>
  <a href="https://github.com/steven-g-w/HA-Sungrow/actions/workflows/validate.yml"><img src="https://github.com/steven-g-w/HA-Sungrow/actions/workflows/validate.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/steven-g-w/HA-Sungrow" alt="License"></a>
</p>

> [!WARNING]
> **Work in progress.** This project is still being built and tested and is
> **not ready for general use**. Expect breaking changes, renamed entities
> and rough edges. Use at your own risk for now.

A custom Home Assistant integration that reads data from — and optionally
controls — a Sungrow solar system through the official
[iSolarCloud OpenAPI](https://developer-api.isolarcloud.com/) (V1 account
login, no OAuth). It creates sensors for plant-level and hybrid-inverter /
battery data such as PV power, load power, battery state of charge and
charging/discharging power, plus opt-in charge/discharge control entities.

## Features

- Config flow (UI) setup — no YAML required
- Plant auto-discovery: the plant ID (`ps_id`) is optional and detected from
  your account when left empty; entries are titled with the plant name
- Automatic discovery of the devices in your plant
- Plant-level sensors (plant power, load power, daily/total yield, feed-in
  and purchased energy, battery SoC, ESS charge/discharge energy, …)
- Hybrid inverter / energy-storage sensors (battery charging/discharging
  power, battery level, battery health, battery temperature, purchased
  power/energy, generation, …)
- Battery/BMS sensors (voltage, current, temperature, SOC, SOH, total
  charge/discharge)
- Optional **device control**, off by default: charge/discharge command and
  power, SOC limits, forced charging schedule (see
  [Device control](#device-control-optional-off-by-default))
- Sensor names and units come from the iSolarCloud point metadata
  (`getOpenPointInfo`) with built-in fallbacks; SOC/SOH ratio points are
  automatically converted from fractions to percentages
- Automatic token renewal and re-authentication flow
- Configurable polling interval (default 5 minutes — the cloud only refreshes
  about that often)

## Prerequisites

1. An [iSolarCloud](https://www.isolarcloud.com/) account that can see your
   plant.
2. A developer application on the
   [Sungrow developer portal](https://developer-api.isolarcloud.com/):
   - Log in to the portal, open **Applications** and click **Create**.
   - Request access *without* OAuth 2.0 (V1). Approval usually takes a couple
     of days.
   - Once approved, open the application details to find your **App key** and
     **Secret key** (used as the `x-access-key` header).
3. *(Optional)* your **plant ID (`ps_id`)**. Normally you can leave this
   empty — the integration discovers it from your account. Provide it only
   if your account has several plants and you don't want the first one; you
   can find it via *Try it* on the *Plant List* call in the developer portal
   documentation, or in the iSolarCloud web UI URL when viewing your plant.

## Installation

### HACS (recommended)

1. In HACS, add this repository
   (`https://github.com/steven-g-w/HA-Sungrow`) as a **custom repository** of
   type *Integration*.
2. Install **Sungrow iSolarCloud** and restart Home Assistant.

### Manual

1. Copy `custom_components/sungrow_isolarcloud` into the
   `custom_components` folder of your Home Assistant configuration directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration** and search for
   **Sungrow iSolarCloud**.
2. Fill in:
   - **API gateway** — pick your region's gateway from the dropdown
     (`https://augateway.isolarcloud.com` for Australia; other regional
     gateways are listed and a custom URL can be typed).
   - **App key** and **Secret key** from your developer application.
   - **iSolarCloud username** and **password**.
   - **Plant ID (`ps_id`)** — optional. Leave it empty and the integration
     finds it from your account automatically (the first plant is used if
     the account has several).
3. Submit — the integration validates the credentials by logging in and
   listing the plant's devices, then creates the sensors.

### Options (Configure button)

Open **Settings → Devices & services → Sungrow iSolarCloud → Configure** to
change, at any time (the integration reloads itself, no restart needed):

- **Polling interval** (default 300 s)
- **Enable device control** (default off — see below)

Credentials, gateway and plant ID are fixed at setup; to change them, remove
and re-add the integration (entities keep their IDs, so dashboards and
history survive). If iSolarCloud rejects the stored credentials, a
re-authentication dialog appears automatically.

## Sensors

Sensors are created for every measuring point that returns a value, grouped
into devices:

- **Plant** (`<ps_id>_11_0_0`): plant power, load power, daily/total yield,
  daily/total feed-in energy, daily/total purchased energy, battery SoC,
  ESS daily/total charge and discharge energy, …
- **Hybrid inverter / energy storage** (device type 14): total DC power,
  daily/total generation, battery charging/discharging power, battery level
  (SoC), battery SOH, battery temperature, purchased power and energy,
  feed-in power and energy, load consumption, …
- **Battery / BMS** (device type 43, e.g. SBR-series): voltage, current,
  temperature, SOC, health, total charge/discharge energy

Points that your plant/app does not expose are simply skipped, and new points
appearing later are added automatically.

Energy sensors use `total_increasing` state class, so they can be used
directly in the Home Assistant **Energy dashboard**.

## Device control (optional, off by default)

The integration can also *control* the hybrid inverter through the OpenAPI's
parameter-setting endpoints. This is **disabled by default** — enable it via
the integration's **Configure** dialog ("Enable device control"). When
enabled (and the device passes the API's support check), these entities are
added to the inverter device:

- **Select**: charging/discharging command (Charge / Discharge / Stop)
- **Number**: charging/discharging power, SOC upper/lower limit (5 % slider
  steps), forced charging target SOC 1/2, max charging/discharging power
- **Switch**: forced charging enable
- **Time**: forced charging window 1/2 start and end times

How it behaves:

- Writes are sent as iSolarCloud parameter tasks to the physical device and
  typically take a few seconds to complete. Unit conversions (the API writes
  in raw register units, e.g. 0.1 % for SOC limits) are handled
  automatically.
- Parameter values are re-read from the device every 30 minutes and
  immediately after each write, so changes made in the iSolarCloud app show
  up in Home Assistant within half an hour.

Use with care — these change how your inverter and battery operate. A
low-risk first test is nudging **SOC upper limit** and checking the value in
the iSolarCloud app.

## Troubleshooting

- **Option/field labels show raw keys (e.g. `enable_control`)** — Home
  Assistant caches integration translations. Fully restart Home Assistant
  after updating the integration, then hard-refresh the browser
  (Ctrl+F5) or reset the companion app's frontend cache.
- **Control entities missing after enabling control** — check the HA log:
  the device must pass the API's parameter-setting support check, and your
  developer application needs control permission on iSolarCloud.
- **Setup fails with "cannot connect"** — verify the gateway matches your
  account's region and that the plant ID (if provided) belongs to this
  account.

## Development

Tests live in `tests/` and run against
[pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component):

```sh
pip install -r requirements_test.txt
pytest
```

`scripts/live_smoke_test.py` exercises the real API end-to-end (login,
device discovery, point metadata, live values). It reads credentials from a
git-ignored `.env` file in the repo root:

```env
BASE_URL=https://augateway.isolarcloud.com
APP_KEY=...
SECRET_KEY=...
USERNAME=...
PASSWORD=...
PS_ID=...
```

CI (GitHub Actions) runs the test suite, [hassfest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
and HACS validation on every push.

## Roadmap

- [x] Control support (charge/discharge scheduling)
- [x] Optional `ps_id` with plant auto-discovery
- [ ] Reconfigure flow for credentials/gateway without re-adding
- [x] Brand icon (self-served from the integration's `brand/` folder;
      shows in the HA UI on Home Assistant 2026.3.0 or newer)
- [ ] More device types (string inverters, meters, chargers)
- [ ] Statistics/history backfill from the cloud

## Credits

Reference material used while building this integration:

- [jsanchezdelvillar/Sungrow-API](https://github.com/jsanchezdelvillar/Sungrow-API)
- [MickMake/GoSungrow](https://github.com/MickMake/GoSungrow)
- [bugjam/pysolarcloud](https://github.com/bugjam/pysolarcloud)

## Disclaimer

This project is not affiliated with Sungrow. Use at your own risk.
