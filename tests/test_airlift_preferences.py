"""Tests for Airlift preference validation independent of Qt."""

import pytest

from airlift_preferences import (
    AIRLIFT_DEPLOYMENT_COUNT_KEY,
    AIRLIFT_FADE_SECONDS_KEY,
    AIRLIFT_RADIUS_KEY,
    DEFAULT_AIRLIFT_FADE_SECONDS,
    DEFAULT_AIRLIFT_PREFERENCES,
    normalize_airlift_preferences,
    validate_airlift_preferences,
)


def test_defaults_and_fade_range():
    assert dict(DEFAULT_AIRLIFT_PREFERENCES) == {
        AIRLIFT_RADIUS_KEY: 5,
        AIRLIFT_DEPLOYMENT_COUNT_KEY: 10,
        AIRLIFT_FADE_SECONDS_KEY: 5,
    }
    for fade_seconds in (0, 10):
        normalized = normalize_airlift_preferences({
            AIRLIFT_FADE_SECONDS_KEY: fade_seconds,
        })
        assert normalized[AIRLIFT_FADE_SECONDS_KEY] == fade_seconds


@pytest.mark.parametrize(
    ("preferences", "expected_radius", "expected_count"),
    [
        ({AIRLIFT_RADIUS_KEY: 5, AIRLIFT_DEPLOYMENT_COUNT_KEY: 6}, 5, 6),
        ({AIRLIFT_RADIUS_KEY: 5, AIRLIFT_DEPLOYMENT_COUNT_KEY: 10}, 5, 10),
        ({AIRLIFT_RADIUS_KEY: 7, AIRLIFT_DEPLOYMENT_COUNT_KEY: 13}, 7, 13),
        ({AIRLIFT_RADIUS_KEY: 7, AIRLIFT_DEPLOYMENT_COUNT_KEY: 19}, 7, 19),
        ({AIRLIFT_RADIUS_KEY: 7}, 7, 19),
        ({AIRLIFT_RADIUS_KEY: 5}, 5, 10),
    ],
)
def test_valid_preferences_and_missing_count(preferences, expected_radius, expected_count):
    normalized = normalize_airlift_preferences(preferences)
    assert normalized[AIRLIFT_RADIUS_KEY] == expected_radius
    assert normalized[AIRLIFT_DEPLOYMENT_COUNT_KEY] == expected_count
    validate_airlift_preferences(normalized)


@pytest.mark.parametrize(
    ("radius", "count", "expected_radius", "expected_count"),
    [
        (5, 11, 5, 10),
        (7, 20, 7, 19),
        (7, 21, 7, 19),
        (6, 10, 5, 10),
        (True, 10, 5, 10),
        (5, True, 5, 10),
        (7, 10, 7, 19),
        (None, 19, 5, 10),
    ],
)
def test_invalid_radius_or_nonoperational_pair_recovers(
    radius, count, expected_radius, expected_count,
):
    normalized = normalize_airlift_preferences({
        AIRLIFT_RADIUS_KEY: radius,
        AIRLIFT_DEPLOYMENT_COUNT_KEY: count,
    })
    assert normalized[AIRLIFT_RADIUS_KEY] == expected_radius
    assert normalized[AIRLIFT_DEPLOYMENT_COUNT_KEY] == expected_count
    validate_airlift_preferences(normalized)


@pytest.mark.parametrize("fade_seconds", [-1, 11, True, 4.0, "4", None])
def test_invalid_fade_recovers_to_conservative_product_default(fade_seconds):
    normalized = normalize_airlift_preferences({
        AIRLIFT_FADE_SECONDS_KEY: fade_seconds,
    })
    assert normalized[AIRLIFT_FADE_SECONDS_KEY] == DEFAULT_AIRLIFT_FADE_SECONDS


def test_validation_rejects_reference_configuration_and_bool():
    for radius, count in ((5, 11), (7, 20), (7, 21), (True, 10), (7, True)):
        with pytest.raises(ValueError):
            validate_airlift_preferences({
                AIRLIFT_RADIUS_KEY: radius,
                AIRLIFT_DEPLOYMENT_COUNT_KEY: count,
                AIRLIFT_FADE_SECONDS_KEY: 5,
            })
