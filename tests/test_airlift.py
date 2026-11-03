"""Qt-free tests for the Airlift catalog and map-coordinate foundation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from airlift import (
    AirliftConfiguration,
    AirliftRing,
    COVERAGE_RADIUS_KM,
    DEFAULT_DEPLOYMENT_COUNTS,
    OPERATIONAL_COUNTS,
    deployment_positions,
    expand_deployment_offsets,
    get_configuration,
    get_default_configuration,
    get_operational_configuration,
    is_operational_configuration,
    load_catalog,
)
from mapper_core import MapperState


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_KEYS = (
    {(5, count) for count in range(6, 12)}
    | {(7, count) for count in range(13, 22)}
)
EXPECTED_OPERATIONAL_KEYS = (
    {(5, count) for count in range(6, 11)}
    | {(7, count) for count in range(13, 20)}
)


@pytest.fixture
def catalog():
    return load_catalog()


def test_catalog_keys_defaults_and_operational_policy(catalog):
    assert set(catalog) == EXPECTED_KEYS
    assert {
        (radius, count)
        for radius, counts in OPERATIONAL_COUNTS.items()
        for count in counts
    } == EXPECTED_OPERATIONAL_KEYS
    assert DEFAULT_DEPLOYMENT_COUNTS == {5: 10, 7: 19}
    assert get_default_configuration(catalog, 5).deployment_count == 10
    assert get_default_configuration(catalog, 7).deployment_count == 19
    assert all(
        is_operational_configuration(radius, count)
        for radius, count in EXPECTED_OPERATIONAL_KEYS
    )


def test_reference_configurations_load_but_are_not_operational(catalog):
    for key in ((5, 11), (7, 20), (7, 21)):
        assert get_configuration(catalog, *key).deployment_count == key[1]
        assert not is_operational_configuration(*key)
        with pytest.raises(ValueError, match="not operational"):
            get_operational_configuration(catalog, *key)


def test_all_catalog_entries_expand_deterministically_with_centre(catalog):
    for key, configuration in catalog.items():
        first = expand_deployment_offsets(configuration)
        assert len(first) == configuration.deployment_count == key[1]
        assert first[0].number == 1
        assert first[0].east_m == 0.0
        assert first[0].north_m == 0.0
        assert first == expand_deployment_offsets(configuration)


@pytest.mark.parametrize(
    ("phase_deg", "expected_east_m", "expected_north_m"),
    [(0.0, 0.0, 1000.0), (90.0, -1000.0, 0.0)],
)
def test_fixed_orientation_maps_catalog_axes_to_rsm_axes(
    phase_deg, expected_east_m, expected_north_m,
):
    configuration = AirliftConfiguration(
        5, 2, (AirliftRing(1, 1.0, phase_deg),), 0.0)

    point = expand_deployment_offsets(configuration)[1]

    assert point.east_m == pytest.approx(expected_east_m, abs=1e-12)
    assert point.north_m == pytest.approx(expected_north_m, abs=1e-12)


def test_known_authoritative_coverage_values_are_preserved(catalog):
    assert catalog[(5, 10)].authoritative_coverage_percent == pytest.approx(
        99.964163115565, rel=0.0, abs=1e-12)
    assert catalog[(7, 19)].authoritative_coverage_percent == 100.0
    assert COVERAGE_RADIUS_KM == 2.0


def test_deployment_positions_are_relative_to_pml_using_mapper_coordinates(catalog):
    state = MapperState()
    state.center_lat = 38.01
    state.center_lon = -9.02
    state.radius = 6_371_000.0
    pml_lat, pml_lon = 38.0, -9.0
    origin = state.llxy(pml_lat, pml_lon)

    points = deployment_positions(catalog[(5, 6)], pml_lat, pml_lon, state)

    assert (points[0].x_m, points[0].y_m) == pytest.approx(origin)
    assert points[1].x_m == pytest.approx(origin[0], abs=1e-10)
    assert points[1].y_m == pytest.approx(origin[1] + 3370.0, abs=1e-9)
    assert len(points) == 6
    assert state.llxy(*state.xyll(points[1].x_m, points[1].y_m)) == pytest.approx(
        (points[1].x_m, points[1].y_m))


@pytest.mark.parametrize(
    ("radius", "count", "error"),
    [
        (6, 6, ValueError),
        (True, 6, ValueError),
        (5, True, ValueError),
        (5, 5, KeyError),
        (7, 22, KeyError),
    ],
)
def test_invalid_catalog_lookups_fail_explicitly(catalog, radius, count, error):
    with pytest.raises(error):
        get_configuration(catalog, radius, count)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(extra=True),
        lambda data: data["configurations"][0].update(target_radius_km=True),
        lambda data: data["configurations"][0].update(deployment_count=True),
        lambda data: data["configurations"][0]["rings"][0].update(point_count=True),
        lambda data: data["configurations"][0]["rings"][0].update(radius_km=0),
        lambda data: data["configurations"][0]["rings"][0].update(phase_deg=float("nan")),
        lambda data: data["configurations"][0].update(authoritative_coverage_percent=101),
        lambda data: data["configurations"][0].update(covering_status="incomplete"),
        lambda data: data["configurations"][5].update(covering_status="incomplete"),
        lambda data: data["configurations"].append(data["configurations"][0].copy()),
    ],
)
def test_malformed_catalog_data_is_rejected(tmp_path, mutate, catalog):
    source = json.loads(
        (ROOT / "assets" / "airlift" / "deployment_configurations.json")
        .read_text(encoding="utf-8"))
    mutate(source)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError):
        load_catalog(path)


def test_module_imports_without_a_qt_dependency():
    script = """
import builtins
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.startswith(("PySide", "PyQt")):
        raise AssertionError(f"Unexpected Qt import: {name}")
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import airlift
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
