"""Number platform: writable numeric parameters of the hybrid inverter."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SungrowConfigEntry
from .controls import NUMBERS, NumberDef
from .coordinator import SungrowControlCoordinator
from .entity import SungrowControlEntity, format_param_value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SungrowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities when control is enabled."""
    control = entry.runtime_data.control
    if control is None:
        return
    async_add_entities(
        SungrowParamNumber(control, definition)
        for definition in NUMBERS
        if definition.code in (control.data or {})
    )


class SungrowParamNumber(SungrowControlEntity, NumberEntity):
    """A writable numeric device parameter."""

    def __init__(
        self, coordinator: SungrowControlCoordinator, definition: NumberDef
    ) -> None:
        super().__init__(coordinator, definition.code, definition.name)
        self._definition = definition
        self._attr_mode = definition.mode
        self._attr_native_min_value = definition.min_value
        self._attr_native_max_value = definition.max_value
        self._attr_native_step = definition.step
        self._attr_entity_category = definition.entity_category
        row = self._row(definition.code)
        self._attr_native_unit_of_measurement = (
            row.get("unit") or definition.unit or None
        )

    @property
    def native_value(self) -> float | None:
        """Return the current parameter value."""
        value = self._value(self._definition.code)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Write the parameter to the device."""
        await self.coordinator.async_write(
            {
                self._definition.code: format_param_value(
                    value, self._definition.step
                )
            }
        )
