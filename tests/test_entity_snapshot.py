"""Golden snapshot of every entity and device the integration creates.

Pins entity identity (unique_id), classification (device class, state class,
entity category, unit), capabilities and state values against a committed
JSON fixture, so refactors of the catalog/mapping layer can prove behavior
is unchanged entity-by-entity. Regenerate deliberately after an intended
change with:

    UPDATE_SNAPSHOT=1 pytest tests/test_entity_snapshot.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sungrow_isolarcloud.const import DOMAIN

SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "entity_snapshot.json"


def _collect(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    """Dump all registry entries, states and devices for the entry."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    entities: dict[str, Any] = {}
    for reg in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        state = hass.states.get(reg.entity_id)
        entities[f"{reg.domain}:{reg.unique_id}"] = {
            "entity_id": reg.entity_id,
            "original_name": reg.original_name,
            "original_device_class": reg.original_device_class,
            "unit_of_measurement": reg.unit_of_measurement,
            "entity_category": reg.entity_category,
            "capabilities": reg.capabilities,
            "state": state.state if state else None,
            "attributes": dict(state.attributes) if state else None,
        }

    devices: dict[str, Any] = {}
    device_ids: dict[str, str] = {}
    for dev in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        identifier = sorted(dev.identifiers)[0][1]
        device_ids[dev.id] = identifier
    for dev in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        identifier = device_ids[dev.id]
        devices[identifier] = {
            "name": dev.name,
            "manufacturer": dev.manufacturer,
            "model": dev.model,
            "serial_number": dev.serial_number,
            "via_device": device_ids.get(dev.via_device_id),
        }

    return {"entities": entities, "devices": devices}


async def test_entity_snapshot(
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry_control: MockConfigEntry,
    entity_registry_enabled_by_default: None,
) -> None:
    """Every created entity and device matches the committed snapshot."""
    mock_config_entry_control.add_to_hass(hass)
    assert await hass.config_entries.async_setup(
        mock_config_entry_control.entry_id
    )
    await hass.async_block_till_done()

    # Round-trip through JSON to normalise enums/tuples to plain values.
    collected = json.loads(
        json.dumps(
            _collect(hass, mock_config_entry_control),
            default=str,
            sort_keys=True,
        )
    )

    if os.environ.get("UPDATE_SNAPSHOT"):
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(collected, indent=2, sort_keys=True) + "\n"
        )
        return

    assert SNAPSHOT_PATH.exists(), (
        "Snapshot missing; generate it with UPDATE_SNAPSHOT=1 pytest "
        "tests/test_entity_snapshot.py"
    )
    expected = json.loads(SNAPSHOT_PATH.read_text())

    assert set(collected["entities"]) == set(expected["entities"])
    for key, expected_entity in expected["entities"].items():
        assert collected["entities"][key] == expected_entity, (
            f"Entity {key} diverged from snapshot"
        )
    assert collected["devices"] == expected["devices"]
