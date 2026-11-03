"""Validation and recovery for persisted Airlift preferences."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from airlift import (
    DEFAULT_DEPLOYMENT_COUNTS,
    OPERATIONAL_COUNTS,
    is_operational_configuration,
)


AIRLIFT_RADIUS_KEY = "airlift_radius_km"
AIRLIFT_DEPLOYMENT_COUNT_KEY = "airlift_deployment_count"
AIRLIFT_FADE_SECONDS_KEY = "airlift_fade_seconds"

DEFAULT_AIRLIFT_RADIUS_KM = 5
DEFAULT_AIRLIFT_FADE_SECONDS = 5
AIRLIFT_FADE_SECONDS_RANGE = (0, 10)

DEFAULT_AIRLIFT_PREFERENCES = MappingProxyType({
    AIRLIFT_RADIUS_KEY: DEFAULT_AIRLIFT_RADIUS_KM,
    AIRLIFT_DEPLOYMENT_COUNT_KEY:
        DEFAULT_DEPLOYMENT_COUNTS[DEFAULT_AIRLIFT_RADIUS_KM],
    AIRLIFT_FADE_SECONDS_KEY: DEFAULT_AIRLIFT_FADE_SECONDS,
})

AIRLIFT_PREFERENCE_KEYS = frozenset(DEFAULT_AIRLIFT_PREFERENCES)


def _valid_radius(value: Any) -> bool:
    return type(value) is int and value in OPERATIONAL_COUNTS


def _valid_count(value: Any, radius: int) -> bool:
    return (type(value) is int
            and is_operational_configuration(radius, value))


def _valid_fade_seconds(value: Any) -> bool:
    low, high = AIRLIFT_FADE_SECONDS_RANGE
    return type(value) is int and low <= value <= high


def normalize_airlift_preferences(
    preferences: Mapping[str, Any],
) -> dict[str, int]:
    """Return valid Airlift preference values, recovering invalid fields safely.

    An invalid or missing radius uses the global R=5 default. A deployment
    count invalid for that recovered/selected radius uses that radius's
    operational default. Fade duration independently falls back to 5 seconds.
    """
    radius = preferences.get(AIRLIFT_RADIUS_KEY)
    if not _valid_radius(radius):
        radius = DEFAULT_AIRLIFT_RADIUS_KM

    count = preferences.get(AIRLIFT_DEPLOYMENT_COUNT_KEY)
    if not _valid_count(count, radius):
        count = DEFAULT_DEPLOYMENT_COUNTS[radius]

    fade_seconds = preferences.get(AIRLIFT_FADE_SECONDS_KEY)
    if not _valid_fade_seconds(fade_seconds):
        fade_seconds = DEFAULT_AIRLIFT_FADE_SECONDS

    return {
        AIRLIFT_RADIUS_KEY: radius,
        AIRLIFT_DEPLOYMENT_COUNT_KEY: count,
        AIRLIFT_FADE_SECONDS_KEY: fade_seconds,
    }


def validate_airlift_preferences(preferences: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` unless all Airlift preference fields form a valid set."""
    radius = preferences.get(AIRLIFT_RADIUS_KEY)
    count = preferences.get(AIRLIFT_DEPLOYMENT_COUNT_KEY)
    fade_seconds = preferences.get(AIRLIFT_FADE_SECONDS_KEY)
    if not _valid_radius(radius):
        raise ValueError(f"{AIRLIFT_RADIUS_KEY} must be 5 or 7")
    if not _valid_count(count, radius):
        raise ValueError(
            f"{AIRLIFT_DEPLOYMENT_COUNT_KEY} is not operational for radius {radius}")
    if not _valid_fade_seconds(fade_seconds):
        low, high = AIRLIFT_FADE_SECONDS_RANGE
        raise ValueError(f"{AIRLIFT_FADE_SECONDS_KEY} must be in {low}..{high}")


__all__ = [
    "AIRLIFT_DEPLOYMENT_COUNT_KEY",
    "AIRLIFT_FADE_SECONDS_KEY",
    "AIRLIFT_FADE_SECONDS_RANGE",
    "AIRLIFT_PREFERENCE_KEYS",
    "AIRLIFT_RADIUS_KEY",
    "DEFAULT_AIRLIFT_FADE_SECONDS",
    "DEFAULT_AIRLIFT_PREFERENCES",
    "DEFAULT_AIRLIFT_RADIUS_KM",
    "normalize_airlift_preferences",
    "validate_airlift_preferences",
]
