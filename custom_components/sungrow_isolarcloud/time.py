"""Time platform: forced charging window start/end times."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SungrowConfigEntry
from .controls import TIMES, TimeDef
from .coordinator import SungrowControlCoordinator
from .entity import SungrowControlEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SungrowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities when control is enabled."""
    control = entry.runtime_data.control
    if control is None:
        return
    data = control.data or {}
    async_add_entities(
        SungrowParamTime(control, definition)
        for definition in TIMES
        if definition.hour_code in data and definition.minute_code in data
    )


class SungrowParamTime(SungrowControlEntity, TimeEntity):
    """A time-of-day parameter composed of hour and minute param codes."""

    def __init__(
        self, coordinator: SungrowControlCoordinator, definition: TimeDef
    ) -> None:
        super().__init__(coordinator, definition.key, definition.name)
        self._definition = definition
        self._attr_entity_category = definition.entity_category

    @property
    def native_value(self) -> time | None:
        """Compose the time from the hour and minute parameters."""
        hour = self._value(self._definition.hour_code)
        minute = self._value(self._definition.minute_code)
        if hour is None or minute is None:
            return None
        try:
            return time(hour=int(float(hour)) % 24, minute=int(float(minute)) % 60)
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        """Write hour and minute in a single parameter task."""
        await self.coordinator.async_write(
            {
                self._definition.hour_code: str(value.hour),
                self._definition.minute_code: str(value.minute),
            }
        )
