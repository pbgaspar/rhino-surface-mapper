"""Immutable market data and result models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .commodities import canonical_commodity_name, normalize_name

LandingPad = Literal["L", "M", "S"]


def _commodity_key(name: str) -> str:
    """Return a comparison key honoring aliases without collapsing empty keys."""
    canonical = canonical_commodity_name(name)
    comparison_name = canonical if canonical is not None else name
    normalized = normalize_name(comparison_name)
    return normalized if normalized else comparison_name.casefold()


def _require_tuple(value: object, field_name: str) -> None:
    """Ensure frozen result objects do not retain mutable collections."""
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")


@dataclass(frozen=True)
class Station:
    """Station identity and pad capability used by market observations."""

    name: str
    market_id: str | None
    system_name: str
    is_planetary: bool | None
    max_landing_pad: LandingPad | None


@dataclass(frozen=True)
class MarketObservation:
    """A commodity price and volume observation at one station."""

    station: Station
    commodity: str
    sell_price: int | None
    demand: int | None
    supply: int | None
    market_updated_at: datetime | None
    station_updated_at: datetime | None


@dataclass(frozen=True)
class MarketIssue:
    """A recoverable issue that occurred while obtaining market results."""

    station_name: str
    message: str


@dataclass(frozen=True)
class CommodityMarketResult:
    """Observations and recoverable issues for one requested commodity."""

    requested_commodity: str
    observations: tuple[MarketObservation, ...]
    issues: tuple[MarketIssue, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.observations, "observations")
        _require_tuple(self.issues, "issues")

    @property
    def missing(self) -> tuple[str, ...]:
        """Return the requested name when no matching observation exists."""
        requested_key = _commodity_key(self.requested_commodity)
        if any(
            _commodity_key(item.commodity) == requested_key
            for item in self.observations
        ):
            return ()
        return (self.requested_commodity,)

    @property
    def is_complete(self) -> bool:
        """Whether the requested commodity was observed without issues."""
        return not self.missing and not self.issues


@dataclass(frozen=True)
class CommodityPriceSummary:
    """Provider-independent global price and demand summary for a commodity."""

    commodity: str
    average_sell: int | None
    maximum_sell: int | None
    total_demand: int | None


@dataclass(frozen=True)
class CommoditySummaryResult:
    """Returned global summaries, missing requested names, and recoverable issues."""

    requested: tuple[str, ...]
    summaries: tuple[CommodityPriceSummary, ...]
    issues: tuple[MarketIssue, ...] = ()

    def __post_init__(self) -> None:
        _require_tuple(self.requested, "requested")
        _require_tuple(self.summaries, "summaries")
        _require_tuple(self.issues, "issues")

    @property
    def missing(self) -> tuple[str, ...]:
        """Return requested names absent from summaries, in request order."""
        returned = {_commodity_key(summary.commodity) for summary in self.summaries}
        missing = []
        seen = set()
        for commodity in self.requested:
            key = _commodity_key(commodity)
            if key not in returned and key not in seen:
                missing.append(commodity)
                seen.add(key)
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        """Whether all requested commodities have summaries and no issues occurred."""
        return not self.missing and not self.issues
