"""Shared entity base for Sungrow control entities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SungrowControlCoordinator


class SungrowControlEntity(CoordinatorEntity[SungrowControlCoordinator]):
    """Base for entities backed by a writable device parameter.

    Control entities are registered disabled: even with the control option
    on, each entity must be explicitly enabled by the user before Home
    Assistant can write to the inverter through it.
    """

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: SungrowControlCoordinator, key: str, name: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.ps_key}_ctl_{key}"
        self._attr_name = name
        # Attach to the same registry device as the ESS sensors.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.ps_key)}
        )

    def _row(self, code: str) -> dict[str, Any]:
        """Return the cached parameter row for a param code."""
        return (self.coordinator.data or {}).get(code, {})

    def _value(self, code: str) -> str | None:
        """Return the cached raw value for a param code."""
        value = self._row(code).get("return_value")
        if value in (None, "", "--"):
            return None
        return str(value)


def format_param_value(value: float, step: float) -> str:
    """Format a numeric value for the paramSetting API."""
    if float(step).is_integer():
        return str(int(round(value)))
    return f"{value:g}"
