"""Caller-selected filtering for market observations."""

import re
from collections.abc import Iterable

from .models import MarketObservation

_CARRIER_NAME_PATTERN = re.compile(r"[A-Za-z0-9]{3}-[A-Za-z0-9]{3}")


def is_carrier_name(name: str) -> bool:
    """Return whether a stripped name matches a confirmed carrier shape."""
    normalized_name = name.strip()
    return len(normalized_name) == 4 or bool(
        _CARRIER_NAME_PATTERN.fullmatch(normalized_name)
    )


def filter_market_observations(
    observations: Iterable[MarketObservation],
    *,
    exclude_carriers: bool = True,
    demand_greater_than: int | None = None,
    require_positive_sell_price: bool = False,
) -> tuple[MarketObservation, ...]:
    """Filter observations using only the caller's selected criteria.

    A demand threshold is strict; unknown demand does not meet an active
    threshold. Positive sell-price filtering is applied only when requested.
    """
    eligible = []
    for observation in observations:
        if exclude_carriers and is_carrier_name(observation.station.name):
            continue
        if demand_greater_than is not None and not (
            observation.demand is not None
            and observation.demand > demand_greater_than
        ):
            continue
        if require_positive_sell_price and not (
            observation.sell_price is not None
            and observation.sell_price > 0
        ):
            continue
        eligible.append(observation)
    return tuple(eligible)
