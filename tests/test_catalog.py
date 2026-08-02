"""Tests for the declarative catalog loader."""

from __future__ import annotations

from collections.abc import Generator
import copy
from pathlib import Path

import pytest

from custom_components.sungrow_isolarcloud import catalog as catalog_module
from custom_components.sungrow_isolarcloud.catalog import (
    CatalogError,
    load_catalog,
    parse_catalog,
)


def _minimal_raw() -> dict:
    """A minimal valid catalog for schema-violation tests."""
    return {
        "version": 1,
        "unit_map": {"W": "W"},
        "device_types": {
            "11": {
                "key": "plant",
                "name": "Plant",
                "synthetic": True,
                "problem_sensor": True,
                "points": {
                    "83022": {
                        "name": "Daily yield",
                        "unit": "Wh",
                        "device_class": "energy",
                        "state_class": "total_increasing",
                        "backfill": "sum",
                    }
                },
            },
            "14": {
                "key": "energy_storage",
                "name": "ESS",
                "points": {
                    "13141": {
                        "name": "SOC",
                        "unit": "%",
                        "device_class": "battery",
                        "scale": 100,
                    }
                },
                "controls": {
                    "numbers": [
                        {
                            "code": "10001",
                            "name": "SOC upper limit",
                            "min": 50,
                            "max": 100,
                            "step": 5,
                            "unit": "%",
                            "mode": "slider",
                        }
                    ],
                    "switches": [
                        {
                            "code": "10065",
                            "name": "Forced charging",
                            "on_value": "170",
                            "off_value": "85",
                        }
                    ],
                },
            },
        },
        "economics": {
            "today_income": {
                "name": "Income today",
                "device_class": "monetary",
                "state_class": "total",
            }
        },
    }


def test_shipped_catalog_loads() -> None:
    """The catalog shipped with the integration loads and is coherent."""
    load_catalog.cache_clear()
    catalog = load_catalog()
    assert catalog.version == 1
    assert catalog.synthetic_device_type == 11
    assert set(catalog.device_types) == {11, 14, 43, 22}
    # Spot-check known definitions against live-verified values.
    daily_yield = catalog.points_for(11)["83022"]
    assert daily_yield.name == "Plant daily yield"
    assert daily_yield.unit == "Wh"
    assert daily_yield.device_class == "energy"
    assert daily_yield.state_class == "total_increasing"
    assert daily_yield.backfill == "sum"
    soc = catalog.points_for(14)["13141"]
    assert soc.scale == 100
    controls = catalog.controls_for(14)
    assert controls is not None
    soc_upper = next(n for n in controls.numbers if n.code == "10001")
    assert (soc_upper.min_value, soc_upper.max_value, soc_upper.step) == (
        50,
        100,
        5,
    )
    command = next(s for s in controls.selects if s.code == "10004")
    assert command.options == {
        "Charge": "170",
        "Discharge": "187",
        "Stop": "204",
    }
    assert "10001" in controls.all_param_codes
    assert "10067" in controls.all_param_codes  # time hour code
    assert catalog.controls_for(11) is None
    assert catalog.problem_sensor_for(11)
    assert not catalog.problem_sensor_for(999)
    assert set(catalog.economics) == {
        "today_income",
        "year_income",
        "total_income",
        "co2_reduce",
        "co2_reduce_total",
    }
    assert catalog.backfill_points("sum") == (
        "83022",
        "83072",
        "83102",
        "83118",
    )
    assert catalog.backfill_points("mean") == ("83033", "83106", "83252")


@pytest.fixture
def catalog_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path]:
    """Point the loader at a throwaway path with a cleared cache."""
    path = tmp_path / "catalog.yaml"
    monkeypatch.setattr(catalog_module, "CATALOG_PATH", path)
    load_catalog.cache_clear()
    yield path
    load_catalog.cache_clear()


def test_missing_catalog_file_is_actionable(catalog_path: Path) -> None:
    """A missing catalog.yaml raises CatalogError, not FileNotFoundError.

    This is the incomplete-manual-install case (only the .py files were
    copied), so the message must say what to do about it.
    """
    assert not catalog_path.exists()
    with pytest.raises(CatalogError) as excinfo:
        load_catalog()
    message = str(excinfo.value)
    assert "catalog.yaml is missing" in message
    assert "copy the whole" in message.lower()
    assert isinstance(excinfo.value.__cause__, FileNotFoundError)


def test_unparseable_catalog_file(catalog_path: Path) -> None:
    """Malformed YAML raises CatalogError rather than a raw YAML error."""
    catalog_path.write_text("version: 1\n  device_types: oops\n")
    with pytest.raises(CatalogError, match="could not be parsed"):
        load_catalog()


def test_empty_catalog_file(catalog_path: Path) -> None:
    """An empty file fails schema validation with a CatalogError."""
    catalog_path.write_text("")
    with pytest.raises(CatalogError, match="invalid"):
        load_catalog()


def test_parse_minimal() -> None:
    """The minimal raw catalog builds."""
    catalog = parse_catalog(_minimal_raw())
    assert catalog.synthetic_device_type == 11
    assert catalog.controls_for(14).all_param_codes == ("10001", "10065")


def test_resolve_unit_and_inference() -> None:
    """Unit mapping and uncataloged-point inference."""
    catalog = load_catalog()
    assert catalog.resolve_unit("℃", None) == "°C"
    assert catalog.resolve_unit("AUD", None) == "AUD"  # pass-through
    assert catalog.resolve_unit(None, "Wh") == "Wh"
    inferred = catalog.infer_point_def("99999", None, "kWh")
    assert inferred.name == "Point 99999"
    assert inferred.device_class == "energy"
    assert inferred.state_class == "total_increasing"
    assert catalog.infer_point_def("1", "X", "W").device_class == "power"


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda raw: raw["device_types"]["11"]["points"]["83022"].update(
                state_class="total_increasin"
            ),
            "SensorStateClass",
        ),
        (
            lambda raw: raw["device_types"]["11"]["points"]["83022"].update(
                device_class="not_a_class"
            ),
            "SensorDeviceClass",
        ),
        (
            lambda raw: raw["device_types"]["14"]["controls"]["numbers"][
                0
            ].update(mode="dial"),
            "NumberMode",
        ),
        (
            lambda raw: raw["device_types"].__setitem__(
                "abc", raw["device_types"]["14"]
            ),
            "numeric",
        ),
        (lambda raw: raw.update(version=2), "version"),
    ],
)
def test_invalid_catalog_rejected(mutate, match: str) -> None:
    """Schema violations raise CatalogError with a pointed message."""
    raw = copy.deepcopy(_minimal_raw())
    mutate(raw)
    with pytest.raises(CatalogError, match=match):
        parse_catalog(raw)


def test_duplicate_param_code_rejected() -> None:
    """The same param code twice in one controls block is rejected."""
    raw = copy.deepcopy(_minimal_raw())
    raw["device_types"]["14"]["controls"]["switches"][0]["code"] = "10001"
    with pytest.raises(CatalogError, match="duplicate param codes"):
        parse_catalog(raw)


def test_backfill_outside_plant_rejected() -> None:
    """backfill on a non-synthetic device type is rejected."""
    raw = copy.deepcopy(_minimal_raw())
    raw["device_types"]["14"]["points"]["13141"]["backfill"] = "mean"
    with pytest.raises(CatalogError, match="backfill"):
        parse_catalog(raw)


def test_exactly_one_synthetic_required() -> None:
    """Zero or two synthetic device types are rejected."""
    raw = copy.deepcopy(_minimal_raw())
    raw["device_types"]["11"]["synthetic"] = False
    del raw["device_types"]["11"]["points"]["83022"]["backfill"]
    with pytest.raises(CatalogError, match="synthetic"):
        parse_catalog(raw)
    raw = copy.deepcopy(_minimal_raw())
    raw["device_types"]["14"]["synthetic"] = True
    with pytest.raises(CatalogError, match="synthetic"):
        parse_catalog(raw)
