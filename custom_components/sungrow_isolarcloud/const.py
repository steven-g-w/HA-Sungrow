"""Constants for the Sungrow iSolarCloud integration."""

from __future__ import annotations

DOMAIN = "sungrow_isolarcloud"

CONF_APP_KEY = "app_key"
CONF_SECRET_KEY = "secret_key"
CONF_PS_ID = "ps_id"
CONF_BASE_URL = "base_url"

DEFAULT_BASE_URL = "https://augateway.isolarcloud.com"

# Known iSolarCloud OpenAPI gateways. The dropdown in the config flow is
# built from this list (custom values are also allowed).
BASE_URLS: list[str] = [
    "https://augateway.isolarcloud.com",  # Australia
    "https://gateway.isolarcloud.com",  # China
    "https://gateway.isolarcloud.com.hk",  # International
    "https://gateway.isolarcloud.eu",  # Europe
]

CONF_SCAN_INTERVAL = "scan_interval"
# iSolarCloud updates cloud data roughly every 5 minutes; polling faster
# than that returns the same values.
DEFAULT_SCAN_INTERVAL = 300
MIN_SCAN_INTERVAL = 60

# device_type values used by the iSolarCloud OpenAPI.
DEVICE_TYPE_INVERTER = 1
DEVICE_TYPE_PLANT = 11
DEVICE_TYPE_ENERGY_STORAGE = 14

PLATFORMS: list[str] = ["sensor"]
