"""Select platform: enumerated writable parameters (e.g. charge command)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SungrowConfigEntry
from .controls import SELECTS, SelectDef
from .coordinator import SungrowControlCoordinator
from .entity import SungrowControlEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SungrowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities when control is enabled."""
    control = entry.runtime_data.control
    if control is None:
        return
    async_add_entities(
        SungrowParamSelect(control, definition)
        for definition in SELECTS
        if definition.code in (control.data or {})
    )


class SungrowParamSelect(SungrowControlEntity, SelectEntity):
    """A writable enumerated device parameter."""

    def __init__(
        self, coordinator: SungrowControlCoordinator, definition: SelectDef
    ) -> None:
        super().__init__(coordinator, definition.code, definition.name)
        self._definition = definition
        self._attr_entity_category = definition.entity_category

    def _label_to_value(self) -> dict[str, str]:
        """Label -> raw value mapping, preferring the API's enumeration."""
        row = self._row(self._definition.code)
        names = row.get("set_val_name")
        values = row.get("set_val_name_val")
        if names and values:
            labels = str(names).split("|")
            raw_values = str(values).split("|")
            if len(labels) == len(raw_values):
                return dict(zip(labels, raw_values))
        return dict(self._definition.options)

    @property
    def options(self) -> list[str]:
        """Return the selectable labels."""
        return list(self._label_to_value())

    @property
    def current_option(self) -> str | None:
        """Return the label matching the current raw value."""
        value = self._value(self._definition.code)
        if value is None:
            return None
        for label, raw in self._label_to_value().items():
            if raw == value:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        """Write the selected option to the device."""
        mapping = self._label_to_value()
        if option not in mapping:
            raise HomeAssistantError(f"Invalid option {option!r}")
        await self.coordinator.async_write({self._definition.code: mapping[option]})
