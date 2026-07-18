"""One-shot import of historical plant data into HA long-term statistics.

Runs once, in the background, right after the integration is first set up
with the backfill option enabled. It fetches minute-level plant history from
iSolarCloud and imports it as hourly statistics for the already-created
sensor entities, so the Energy dashboard and statistics graphs show data
from before the integration was installed.

Energy counters (daily-resetting Wh values) are imported as cumulative
``sum`` statistics; power/SOC readings as hourly ``mean``/``min``/``max``.
A statistic that already has any recorded rows is skipped entirely — sums
imported underneath existing rows would corrupt the Energy dashboard, and
this situation only occurs when re-adding a previously used entry.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api import SungrowApiError
from .const import (
    BACKFILL_CHUNK_HOURS,
    BACKFILL_DAYS,
    BACKFILL_MINUTE_INTERVAL,
    DEVICE_TYPE_PLANT,
    DOMAIN,
)
from .coordinator import SungrowCoordinator
from .points import DEVICE_TYPE_POINTS, resolve_unit

_LOGGER = logging.getLogger(__name__)

TS_FORMAT = "%Y%m%d%H%M%S"

# Plant-level (device_type 11) points to import. Daily-resetting energy
# counters become 'sum' statistics; instantaneous readings become 'mean'.
ENERGY_POINTS: tuple[str, ...] = ("83022", "83072", "83102", "83118")
MEASUREMENT_POINTS: tuple[str, ...] = ("83033", "83106", "83252")
ALL_BACKFILL_POINTS: tuple[str, ...] = ENERGY_POINTS + MEASUREMENT_POINTS


def _parse_ts(raw: str) -> datetime | None:
    """Parse an API timestamp (plant-local) into an aware local datetime.

    The API reports timestamps in the plant's local time; we interpret them
    in Home Assistant's configured timezone, which matches for the typical
    "HA runs where the plant is" install.
    """
    try:
        naive = datetime.strptime(str(raw), TS_FORMAT)
    except ValueError:
        return None
    return naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


async def _has_existing_statistics(hass: HomeAssistant, statistic_id: str) -> bool:
    """Return True if any statistics rows already exist for the id."""
    last = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"state", "sum"}
    )
    return bool(last)


async def async_backfill(
    hass: HomeAssistant, coordinator: SungrowCoordinator
) -> None:
    """Fetch plant history and import it as hourly statistics."""
    client = coordinator.client
    ps_key = coordinator.plant_ps_key
    registry = er.async_get(hass)

    # Map point id -> entity_id of the existing sensor.
    entity_ids: dict[str, str] = {}
    for point_id in ALL_BACKFILL_POINTS:
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{ps_key}_{point_id}"
        )
        if entity_id:
            entity_ids[point_id] = entity_id
    if not entity_ids:
        _LOGGER.warning("Backfill: no matching sensor entities found; skipping")
        return

    # 1) Collect samples: point_id -> [(local datetime, float value)]
    samples: dict[str, list[tuple[datetime, float]]] = {p: [] for p in entity_ids}
    end = dt_util.now().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=BACKFILL_DAYS)
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(hours=BACKFILL_CHUNK_HOURS), end)
        try:
            frames = await client.async_get_minute_history(
                ps_key,
                list(entity_ids),
                chunk_start.strftime(TS_FORMAT),
                chunk_end.strftime(TS_FORMAT),
                BACKFILL_MINUTE_INTERVAL,
            )
        except SungrowApiError as err:
            _LOGGER.warning(
                "Backfill: history request %s-%s failed (%s); continuing",
                chunk_start,
                chunk_end,
                err,
            )
            frames = []
        for frame in frames:
            when = _parse_ts(frame.get("time_stamp"))
            if when is None:
                continue
            for point_id in entity_ids:
                raw = frame.get(f"p{point_id}")
                value = coordinator._build_point_value(
                    point_id, raw, DEVICE_TYPE_PLANT
                ).value
                if isinstance(value, float):
                    samples[point_id].append((when, value))
        chunk_start = chunk_end
        # Be gentle with the API; this loop runs a few hundred times.
        await asyncio.sleep(0.3)

    # 2) Build and import hourly statistics per point.
    imported = 0
    for point_id, entity_id in entity_ids.items():
        series = sorted(samples[point_id])
        if not series:
            _LOGGER.debug("Backfill: no history for point %s; skipping", point_id)
            continue
        if await _has_existing_statistics(hass, entity_id):
            _LOGGER.warning(
                "Backfill: %s already has statistics; skipping to avoid "
                "corrupting existing data",
                entity_id,
            )
            continue
        # Resolve the unit exactly like the sensor platform does (API
        # metadata first, catalog fallback) — the statistic's unit must
        # match the sensor's, or recorder's unit conversion skews values.
        catalog_def = DEVICE_TYPE_POINTS[DEVICE_TYPE_PLANT].get(point_id)
        unit = resolve_unit(
            coordinator._build_point_value(point_id, "0", DEVICE_TYPE_PLANT).unit,
            catalog_def.unit if catalog_def else None,
        )
        is_energy = point_id in ENERGY_POINTS
        stats = (
            _energy_stats(series) if is_energy else _measurement_stats(series)
        )
        if not stats:
            continue
        metadata = StatisticMetaData(
            has_mean=not is_energy,
            has_sum=is_energy,
            name=None,
            source="recorder",
            statistic_id=entity_id,
            unit_of_measurement=unit,
        )
        async_import_statistics(hass, metadata, stats)
        imported += 1
        _LOGGER.debug(
            "Backfill: imported %d hourly rows for %s", len(stats), entity_id
        )
    _LOGGER.info(
        "Backfill finished: imported statistics for %d of %d sensors "
        "(%d days of history)",
        imported,
        len(entity_ids),
        BACKFILL_DAYS,
    )


def _hour_of(when: datetime) -> datetime:
    return when.replace(minute=0, second=0, microsecond=0)


def _energy_stats(series: list[tuple[datetime, float]]) -> list[StatisticData]:
    """Hourly cumulative-sum stats from a daily-resetting energy counter.

    Deltas between consecutive samples are clamped to >= 0 so the midnight
    reset (counter drops back to 0) contributes nothing instead of a
    negative step.
    """
    hourly_delta: dict[datetime, float] = {}
    hourly_last_state: dict[datetime, float] = {}
    previous: float | None = None
    for when, value in series:
        hour = _hour_of(when)
        if previous is not None:
            hourly_delta[hour] = hourly_delta.get(hour, 0.0) + max(
                0.0, value - previous
            )
        else:
            hourly_delta.setdefault(hour, 0.0)
        hourly_last_state[hour] = value
        previous = value
    stats: list[StatisticData] = []
    running_sum = 0.0
    for hour in sorted(hourly_delta):
        running_sum += hourly_delta[hour]
        stats.append(
            StatisticData(
                start=hour,
                state=hourly_last_state[hour],
                sum=running_sum,
            )
        )
    return stats


def _measurement_stats(
    series: list[tuple[datetime, float]],
) -> list[StatisticData]:
    """Hourly mean/min/max stats from instantaneous readings."""
    buckets: dict[datetime, list[float]] = {}
    for when, value in series:
        buckets.setdefault(_hour_of(when), []).append(value)
    stats: list[StatisticData] = []
    for hour in sorted(buckets):
        values = buckets[hour]
        stats.append(
            StatisticData(
                start=hour,
                mean=sum(values) / len(values),
                min=min(values),
                max=max(values),
            )
        )
    return stats
