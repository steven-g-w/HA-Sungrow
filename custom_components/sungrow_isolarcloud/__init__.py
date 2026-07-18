"""The Sungrow iSolarCloud integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SET_TYPE_WRITE, SungrowApiClient, SungrowApiError
from .const import (
    CONF_APP_KEY,
    CONF_BASE_URL,
    CONF_ENABLE_BACKFILL,
    CONF_ENABLE_CONTROL,
    CONF_SECRET_KEY,
    DATA_BACKFILL_DONE,
    DEVICE_TYPE_ENERGY_STORAGE,
    PLATFORMS,
)
from .coordinator import SungrowControlCoordinator, SungrowCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class SungrowRuntimeData:
    """Runtime objects stored on the config entry."""

    coordinator: SungrowCoordinator
    control: SungrowControlCoordinator | None = None


type SungrowConfigEntry = ConfigEntry[SungrowRuntimeData]


async def _async_setup_control(
    hass: HomeAssistant,
    entry: SungrowConfigEntry,
    client: SungrowApiClient,
    coordinator: SungrowCoordinator,
) -> SungrowControlCoordinator | None:
    """Set up the control coordinator if the user opted in and it's supported."""
    device = next(
        (
            d
            for d in coordinator.data.devices.values()
            if d.device_type == DEVICE_TYPE_ENERGY_STORAGE and d.uuid
        ),
        None,
    )
    if device is None:
        _LOGGER.warning(
            "Control is enabled but no energy storage system (device type %s) "
            "with a uuid was found; no control entities will be created",
            DEVICE_TYPE_ENERGY_STORAGE,
        )
        return None
    try:
        supported = await client.async_param_setting_check(
            device.uuid, SET_TYPE_WRITE
        )
    except SungrowApiError as err:
        _LOGGER.warning(
            "Control is enabled but the parameter setting check failed "
            "(the app may lack control permission): %s",
            err,
        )
        return None
    if not supported:
        _LOGGER.warning(
            "Control is enabled but device %s does not support parameter "
            "configuration; no control entities will be created",
            device.ps_key,
        )
        return None
    control = SungrowControlCoordinator(hass, entry, client, device)
    await control.async_config_entry_first_refresh()
    return control


async def async_setup_entry(hass: HomeAssistant, entry: SungrowConfigEntry) -> bool:
    """Set up Sungrow iSolarCloud from a config entry."""
    client = SungrowApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data[CONF_APP_KEY],
        entry.data[CONF_SECRET_KEY],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = SungrowCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    control: SungrowControlCoordinator | None = None
    if entry.options.get(CONF_ENABLE_CONTROL, False):
        control = await _async_setup_control(hass, entry, client, coordinator)

    entry.runtime_data = SungrowRuntimeData(coordinator=coordinator, control=control)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if entry.data.get(CONF_ENABLE_BACKFILL) and not entry.data.get(
        DATA_BACKFILL_DONE
    ):
        entry.async_create_background_task(
            hass,
            _async_run_backfill(hass, entry, coordinator),
            "sungrow_isolarcloud_backfill",
        )
    return True


async def _async_run_backfill(
    hass: HomeAssistant, entry: SungrowConfigEntry, coordinator: SungrowCoordinator
) -> None:
    """Run the one-shot statistics backfill and mark it done."""
    # Imported lazily so installs without backfill never touch recorder.
    from .backfill import async_backfill

    try:
        await async_backfill(hass, coordinator)
    except Exception:
        _LOGGER.exception("Statistics backfill failed")
        return
    # Mark done even across restarts. This triggers one entry reload via the
    # update listener, after which this block is skipped forever.
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, DATA_BACKFILL_DONE: True}
    )


async def _async_update_listener(
    hass: HomeAssistant, entry: SungrowConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SungrowConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
