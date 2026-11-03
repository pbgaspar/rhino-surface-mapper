"""Qt-free Airlift catalog, deployment geometry, and map-coordinate helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from app_paths import application_directory


COVERAGE_RADIUS_KM = 2.0
COVERING_DISTANCE_TOLERANCE_KM = 1e-8
OPERATIONAL_COUNTS = MappingProxyType({
    5: tuple(range(6, 11)),
    7: tuple(range(13, 20)),
})
DEFAULT_DEPLOYMENT_COUNTS = MappingProxyType({5: 10, 7: 19})

_REQUIRED_CONFIGURATION_FIELDS = {
    "target_radius_km",
    "deployment_count",
    "rings",
    "authoritative_coverage_percent",
}
_OPTIONAL_CONFIGURATION_FIELDS = {"covering_radius_km", "covering_status"}
_COVERING_STATUSES = {
    "complete within tolerance",
    "incomplete",
    "boundary case / numerically indeterminate",
}


@dataclass(frozen=True)
class AirliftRing:
    """One equally spaced ring of deployment points, in catalog units."""

    point_count: int
    radius_km: float
    phase_deg: float


@dataclass(frozen=True)
class AirliftConfiguration:
    """Immutable catalog entry for one target radius and deployment count."""

    target_radius_km: int
    deployment_count: int
    rings: tuple[AirliftRing, ...]
    authoritative_coverage_percent: float
    covering_radius_km: float | None = None
    covering_status: str | None = None


@dataclass(frozen=True)
class DeploymentOffset:
    """A numbered deployment offset from the PML centre in local map metres."""

    number: int
    east_m: float
    north_m: float


@dataclass(frozen=True)
class DeploymentPosition:
    """A numbered deployment position in the active map's local coordinates."""

    number: int
    x_m: float
    y_m: float


class LocalMapCoordinates(Protocol):
    """Coordinate operations required from the Qt-free map state."""

    def llxy(self, lat: float, lon: float) -> tuple[float, float]:
        """Convert geographic coordinates to local map metres."""


def catalog_file_path() -> Path:
    """Return the packaged catalog location in source and frozen builds."""
    return (application_directory() / "assets" / "airlift"
            / "deployment_configurations.json")


def _finite_number(value: Any, name: str) -> float:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _positive_integer(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_object(
    value: Any, required: set[str], optional: set[str], name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    keys = set(value)
    if not required <= keys or keys - required - optional:
        raise ValueError(f"{name} has missing or unsupported fields")
    return value


def _expected_covering_status(rho_km: float) -> str:
    difference = rho_km - COVERAGE_RADIUS_KM
    if difference < -COVERING_DISTANCE_TOLERANCE_KM:
        return "complete within tolerance"
    if difference > COVERING_DISTANCE_TOLERANCE_KM:
        return "incomplete"
    return "boundary case / numerically indeterminate"


def load_catalog(
    path: str | Path | None = None,
) -> Mapping[tuple[int, int], AirliftConfiguration]:
    """Load and validate the production catalog, optionally from a test path.

    File-system errors propagate as ``OSError``. Malformed JSON or catalog
    data raises ``ValueError`` with the source path or offending field.
    """
    source = catalog_file_path() if path is None else Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Airlift catalog JSON: {source}") from exc

    if not isinstance(payload, dict) or set(payload) != {"configurations"}:
        raise ValueError("Airlift catalog must contain only a configurations list")
    entries = payload["configurations"]
    if not isinstance(entries, list):
        raise ValueError("Airlift configurations must be a list")

    configurations: dict[tuple[int, int], AirliftConfiguration] = {}
    for index, raw in enumerate(entries):
        name = f"configuration {index}"
        raw = _require_object(
            raw, _REQUIRED_CONFIGURATION_FIELDS,
            _OPTIONAL_CONFIGURATION_FIELDS, name)
        radius_value = _finite_number(
            raw["target_radius_km"], f"{name} target_radius_km")
        if radius_value not in (5.0, 7.0):
            raise ValueError(f"{name} has an unsupported target radius")
        target_radius = int(radius_value)
        count = _positive_integer(
            raw["deployment_count"], f"{name} deployment_count")

        rings_raw = raw["rings"]
        if not isinstance(rings_raw, list) or not rings_raw:
            raise ValueError(f"{name} rings must be a non-empty list")
        rings: list[AirliftRing] = []
        total_ring_points = 0
        for ring_index, ring_value in enumerate(rings_raw):
            ring_name = f"{name} ring {ring_index}"
            ring_value = _require_object(
                ring_value,
                {"point_count", "radius_km", "phase_deg"},
                set(),
                ring_name,
            )
            point_count = _positive_integer(
                ring_value["point_count"], f"{ring_name} point_count")
            ring_radius = _finite_number(
                ring_value["radius_km"], f"{ring_name} radius_km")
            phase = _finite_number(
                ring_value["phase_deg"], f"{ring_name} phase_deg")
            if ring_radius <= 0:
                raise ValueError(f"{ring_name} radius_km must be positive")
            total_ring_points += point_count
            rings.append(AirliftRing(point_count, ring_radius, phase))
        if total_ring_points + 1 != count:
            raise ValueError(f"{name} expanded point count does not equal N")

        coverage = _finite_number(
            raw["authoritative_coverage_percent"],
            f"{name} authoritative_coverage_percent")
        if not 0.0 <= coverage <= 100.0:
            raise ValueError(f"{name} coverage must be within 0..100")

        has_rho = "covering_radius_km" in raw
        has_status = "covering_status" in raw
        if has_rho != has_status:
            raise ValueError(
                f"{name} covering radius and status must be provided together")
        rho: float | None = None
        status: str | None = None
        if has_rho:
            rho = _finite_number(
                raw["covering_radius_km"], f"{name} covering_radius_km")
            status = raw["covering_status"]
            if rho < 0:
                raise ValueError(f"{name} covering_radius_km cannot be negative")
            if not isinstance(status, str) or status not in _COVERING_STATUSES:
                raise ValueError(f"{name} has an invalid covering_status")
            if status != _expected_covering_status(rho):
                raise ValueError(
                    f"{name} covering_status is inconsistent with its radius")

        configuration = AirliftConfiguration(
            target_radius,
            count,
            tuple(rings),
            coverage,
            rho,
            status,
        )
        key = (target_radius, count)
        if key in configurations:
            raise ValueError(f"Duplicate Airlift configuration {key}")
        configurations[key] = configuration

    return MappingProxyType(configurations)


def _configuration_key(target_radius_km: int, deployment_count: int) -> tuple[int, int]:
    radius = _finite_number(target_radius_km, "target_radius_km")
    if radius not in (5.0, 7.0):
        raise ValueError("target_radius_km must be 5 or 7")
    count = _positive_integer(deployment_count, "deployment_count")
    return int(radius), count


def get_configuration(
    catalog: Mapping[tuple[int, int], AirliftConfiguration],
    target_radius_km: int,
    deployment_count: int,
) -> AirliftConfiguration:
    """Return any catalog configuration, including reference-only entries."""
    key = _configuration_key(target_radius_km, deployment_count)
    try:
        return catalog[key]
    except KeyError as exc:
        raise KeyError(f"No Airlift catalog configuration for {key}") from exc


def is_operational_configuration(
    target_radius_km: int, deployment_count: int,
) -> bool:
    """Return whether a valid radius/count pair is allowed by current policy."""
    radius, count = _configuration_key(target_radius_km, deployment_count)
    return count in OPERATIONAL_COUNTS[radius]


def get_operational_configuration(
    catalog: Mapping[tuple[int, int], AirliftConfiguration],
    target_radius_km: int,
    deployment_count: int,
) -> AirliftConfiguration:
    """Return an operational choice, rejecting valid reference-only entries."""
    key = _configuration_key(target_radius_km, deployment_count)
    if key[1] not in OPERATIONAL_COUNTS[key[0]]:
        raise ValueError(f"Airlift configuration {key} is not operational")
    return get_configuration(catalog, *key)


def get_default_configuration(
    catalog: Mapping[tuple[int, int], AirliftConfiguration],
    target_radius_km: int,
) -> AirliftConfiguration:
    """Return the approved operational default for a supported radius."""
    radius, _ = _configuration_key(target_radius_km, 1)
    return get_operational_configuration(
        catalog, radius, DEFAULT_DEPLOYMENT_COUNTS[radius])


def expand_deployment_offsets(
    configuration: AirliftConfiguration,
) -> tuple[DeploymentOffset, ...]:
    """Expand the implicit centre and rings into north-oriented metre offsets.

    A +90-degree Cartesian rotation maps catalog +x (0 degrees) to north;
    catalog +y (90 degrees) consequently maps to west in RSM's east/north axes.
    """
    if (not isinstance(configuration.deployment_count, int)
            or isinstance(configuration.deployment_count, bool)
            or configuration.deployment_count <= 0):
        raise ValueError("deployment_count must be a positive integer")

    offsets = [DeploymentOffset(1, 0.0, 0.0)]
    for ring in configuration.rings:
        point_count = _positive_integer(ring.point_count, "point_count")
        radius_km = _finite_number(ring.radius_km, "radius_km")
        phase_deg = _finite_number(ring.phase_deg, "phase_deg")
        if radius_km <= 0:
            raise ValueError("radius_km must be positive")
        for index in range(point_count):
            angle = math.radians(phase_deg + 360.0 * index / point_count)
            catalog_x = radius_km * math.cos(angle)
            catalog_y = radius_km * math.sin(angle)
            offsets.append(DeploymentOffset(
                len(offsets) + 1,
                -catalog_y * 1000.0,
                catalog_x * 1000.0,
            ))
    if len(offsets) != configuration.deployment_count:
        raise ValueError("expanded point count does not equal deployment_count")
    if any(not math.isfinite(value)
           for offset in offsets
           for value in (offset.east_m, offset.north_m)):
        raise ValueError("expanded deployment offsets must be finite")
    return tuple(offsets)


def deployment_positions(
    configuration: AirliftConfiguration,
    pml_center_lat: float,
    pml_center_lon: float,
    coordinates: LocalMapCoordinates,
) -> tuple[DeploymentPosition, ...]:
    """Place offsets around a PML centre using the map state's ``llxy`` helper."""
    latitude = _finite_number(pml_center_lat, "pml_center_lat")
    longitude = _finite_number(pml_center_lon, "pml_center_lon")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("pml_center_lat must be within -90..90")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("pml_center_lon must be within -180..180")

    origin_x, origin_y = coordinates.llxy(latitude, longitude)
    origin_x = _finite_number(origin_x, "PML map x")
    origin_y = _finite_number(origin_y, "PML map y")
    return tuple(
        DeploymentPosition(
            offset.number,
            origin_x + offset.east_m,
            origin_y + offset.north_m,
        )
        for offset in expand_deployment_offsets(configuration)
    )


__all__ = [
    "AirliftConfiguration",
    "AirliftRing",
    "COVERAGE_RADIUS_KM",
    "DEFAULT_DEPLOYMENT_COUNTS",
    "DeploymentOffset",
    "DeploymentPosition",
    "LocalMapCoordinates",
    "OPERATIONAL_COUNTS",
    "catalog_file_path",
    "deployment_positions",
    "expand_deployment_offsets",
    "get_configuration",
    "get_default_configuration",
    "get_operational_configuration",
    "is_operational_configuration",
    "load_catalog",
]
