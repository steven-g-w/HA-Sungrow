"""Switch platform: binary writable parameters (e.g. forced charging)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SungrowConfigEntry
from .controls import SWITCHES, SwitchDef
from .coordinator import SungrowControlCoordinator
from .entity import SungrowControlEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SungrowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities when control is enabled."""
    control = entry.runtime_data.control
    if control is None:
        return
    async_add_entities(
        SungrowParamSwitch(control, definition)
        for definition in SWITCHES
        if definition.code in (control.data or {})
    )


class SungrowParamSwitch(SungrowControlEntity, SwitchEntity):
    """A writable binary device parameter."""

    def __init__(
        self, coordinator: SungrowControlCoordinator, definition: SwitchDef
    ) -> None:
        super().__init__(coordinator, definition.code, definition.name)
        self._definition = definition
        self._attr_entity_category = definition.entity_category

    def _on_off_values(self) -> tuple[str, str]:
        """(on, off) raw values, preferring the API's enumeration."""
        row = self._row(self._definition.code)
        names = row.get("set_val_name")
        values = row.get("set_val_name_val")
        if names and values:
            labels = [n.strip().lower() for n in str(names).split("|")]
            raw_values = str(values).split("|")
            if len(labels) == len(raw_values):
                mapping = dict(zip(labels, raw_values))
                on = mapping.get("enable") or mapping.get("on")
                off = mapping.get("disable") or mapping.get("off")
                if on and off:
                    return on, off
        return self._definition.on_value, self._definition.off_value

    @property
    def is_on(self) -> bool | None:
        """Return True when the parameter equals the on value."""
        value = self._value(self._definition.code)
        if value is None:
            return None
        return value == self._on_off_values()[0]

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the parameter."""
        await self.coordinator.async_write(
            {self._definition.code: self._on_off_values()[0]}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the parameter."""
        await self.coordinator.async_write(
            {self._definition.code: self._on_off_values()[1]}
        )
