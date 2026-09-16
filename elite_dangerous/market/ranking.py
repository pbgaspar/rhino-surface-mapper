"""Deterministic ranking for station market observations."""

from collections.abc import Iterable

from .models import MarketObservation

_PAD_RANK = {"L": 3, "M": 2, "S": 1}


def _ranking_key(observation: MarketObservation) -> tuple[bool, int, bool, int, int]:
    """Build descending criteria with unknown values after known values."""
    price = observation.sell_price
    demand = observation.demand
    pad_rank = _PAD_RANK.get(observation.station.max_landing_pad, 0)
    return (
        price is None,
        -(price if price is not None else 0),
        demand is None,
        -(demand if demand is not None else 0),
        -pad_rank,
    )


def rank_market_observations(
    observations: Iterable[MarketObservation],
) -> tuple[MarketObservation, ...]:
    """Order by sell price, demand, then pad capability, all descending.

    Unknown values rank after known values for their criterion. Python's
    stable sort preserves input order for observations with identical keys.
    """
    return tuple(sorted(observations, key=_ranking_key))
