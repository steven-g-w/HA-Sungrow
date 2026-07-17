"""Config flow for the Sungrow iSolarCloud integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import SungrowApiClient, SungrowApiError, SungrowAuthError
from .const import (
    BASE_URLS,
    CONF_APP_KEY,
    CONF_BASE_URL,
    CONF_ENABLE_CONTROL,
    CONF_PS_ID,
    CONF_SCAN_INTERVAL,
    CONF_SECRET_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): SelectSelector(
            SelectSelectorConfig(
                options=BASE_URLS,
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        ),
        vol.Required(CONF_APP_KEY): str,
        vol.Required(CONF_SECRET_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_PS_ID): str,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_APP_KEY): str,
        vol.Required(CONF_SECRET_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class SungrowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Sungrow iSolarCloud."""

    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> str | None:
        """Try to log in and list devices; return an error key or None."""
        client = SungrowApiClient(
            async_get_clientsession(self.hass),
            data[CONF_BASE_URL],
            data[CONF_APP_KEY],
            data[CONF_SECRET_KEY],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
        try:
            await client.async_login()
            await client.async_get_device_list(data[CONF_PS_ID])
        except SungrowAuthError:
            return "invalid_auth"
        except SungrowApiError as err:
            _LOGGER.warning("Validation against iSolarCloud failed: %s", err)
            return "cannot_connect"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial configuration step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(str(user_input[CONF_PS_ID]))
            self._abort_if_unique_id_configured()
            error = await self._async_validate(user_input)
            if error is None:
                return self.async_create_entry(
                    title=f"Sungrow plant {user_input[CONF_PS_ID]}",
                    data=user_input,
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user for fresh credentials."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**reauth_entry.data, **user_input}
            error = await self._async_validate(data)
            if error is None:
                return self.async_update_reload_and_abort(reauth_entry, data=data)
            errors["base"] = error
        suggested = user_input or {
            CONF_APP_KEY: reauth_entry.data.get(CONF_APP_KEY),
            CONF_USERNAME: reauth_entry.data.get(CONF_USERNAME),
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                STEP_REAUTH_SCHEMA, suggested
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SungrowOptionsFlow:
        """Return the options flow handler."""
        return SungrowOptionsFlow()


class SungrowOptionsFlow(OptionsFlow):
    """Options flow: polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=3600,
                        step=30,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Required(
                    CONF_ENABLE_CONTROL,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_CONTROL, False
                    ),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
