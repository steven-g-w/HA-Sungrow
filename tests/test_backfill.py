"""Tests for the one-shot statistics backfill."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.typing import RecorderInstanceGenerator


@pytest.fixture
def mock_recorder_before_hass(
    async_test_recorder: RecorderInstanceGenerator,
) -> None:
    """Prepare the recorder database before the hass fixture starts."""

from custom_components.sungrow_isolarcloud.const import (
    DATA_BACKFILL_DONE,
    DOMAIN,
)

from .conftest import ENTRY_DATA, PLANT_PS_KEY, PS_ID


def _entry_with_backfill() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Sungrow plant {PS_ID}",
        data={**ENTRY_DATA, "enable_backfill": True},
        unique_id=PS_ID,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_backfill_off_by_default(
    recorder_mock: None,
    hass: HomeAssistant,
    mock_api_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Without the option, no history is ever fetched."""
    await _setup(hass, mock_config_entry)
    mock_api_client.async_get_minute_history.assert_not_awaited()
    assert DATA_BACKFILL_DONE not in mock_config_entry.data


async def test_backfill_imports_statistics_once(
    recorder_mock: None,
    hass: HomeAssistant,
    mock_api_client: MagicMock,
) -> None:
    """Backfill imports hourly stats for plant sensors, then never re-runs."""
    entry = _entry_with_backfill()
    with patch("custom_components.sungrow_isolarcloud.backfill.BACKFILL_DAYS", 1):
        await _setup(hass, entry)
        await hass.async_block_till_done(wait_background_tasks=True)
    await async_wait_recording_done(hass)

    assert mock_api_client.async_get_minute_history.await_count > 0
    assert entry.data.get(DATA_BACKFILL_DONE) is True

    registry = er.async_get(hass)
    yield_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{PLANT_PS_KEY}_83022"
    )
    power_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{PLANT_PS_KEY}_83033"
    )
    soc_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{PLANT_PS_KEY}_83252"
    )

    start = dt_util.utcnow() - timedelta(days=2)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        None,
        {yield_id, power_id, soc_id},
        "hour",
        None,
        {"state", "sum", "mean", "min", "max"},
    )

    # Energy: cumulative sum, increasing ~100 Wh per full hour.
    yield_rows = stats[yield_id]
    assert len(yield_rows) >= 12
    sums = [row["sum"] for row in yield_rows]
    assert sums == sorted(sums)
    assert sums[-1] > 0

    # Power: flat 1500 W mean.
    power_rows = stats[power_id]
    assert power_rows and power_rows[0]["mean"] == 1500.0

    # SOC: fraction 0.5 scaled to 50 %.
    soc_rows = stats[soc_id]
    assert soc_rows and soc_rows[0]["mean"] == 50.0

    # Reload: backfill must not run again.
    mock_api_client.async_get_minute_history.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api_client.async_get_minute_history.assert_not_awaited()
