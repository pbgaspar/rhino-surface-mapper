"""Qt-free Surface Mining acquisition, snapshots, and recalculation."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from elite_dangerous.market import (
    CommodityMarketResult,
    CommoditySummaryResult,
    LandableBody,
    MarketIssue,
    MarketObservation,
    commodities_for_planet_types,
    classify_market_freshness,
    fetch_commodity_markets,
    fetch_landable_bodies,
    filter_market_observations,
    is_carrier_name,
    planet_types_for_commodities,
    rank_market_observations,
    resolve_system,
    SpanshError,
    SpanshSystemNotFoundError,
)
from elite_dangerous.market.spansh import (
    ACQUISITION_TIMEOUT,
    AcquisitionCancelled,
    AcquisitionContext,
    AcquisitionDeadlineExceeded,
)


SNAPSHOT_TTL = timedelta(minutes=30)


class SurfaceMiningError(RuntimeError):
    """Base class for user-facing Surface Mining acquisition failures."""


class SystemNotFoundError(SurfaceMiningError):
    """The requested system could not be resolved by Spansh."""


class MarketAcquisitionError(SurfaceMiningError):
    """External acquisition failed after system resolution."""


@dataclass(frozen=True)
class SurfaceMiningSnapshot:
    """Raw system data retained for local recalculation."""

    system_name: str
    system_id64: int
    bodies: tuple[LandableBody, ...]
    commodities: tuple[str, ...]
    market_results: tuple[CommodityMarketResult, ...]
    acquired_at: datetime


@dataclass(frozen=True)
class SurfaceMiningProduct:
    """One selected commodity and its eligible ranked markets."""

    commodity: str
    bodies: tuple[str, ...]
    markets: tuple[MarketObservation, ...]
    summary: object | None = None


@dataclass(frozen=True)
class SurfaceMiningAnalysis:
    """Presentation-neutral recalculation output."""

    system_name: str
    products: tuple[SurfaceMiningProduct, ...]
    issues: tuple[MarketIssue, ...]
    bodies: tuple[LandableBody, ...]
    eligible_market_count: int
    minimum_demand: int


def _market_identity(observation: MarketObservation) -> tuple[str, str, object]:
    """Return a collision-safe identity for one physical station market."""
    station = observation.station
    if station.market_id is not None:
        return station.system_name.casefold(), "id", station.market_id
    return station.system_name.casefold(), "name", station.name.casefold()


def _now(now: datetime | None) -> datetime:
    value = datetime.now(timezone.utc) if now is None else now
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


class SurfaceMiningService:
    """Own session snapshots and apply Surface Mining policies locally."""

    def __init__(self, *, snapshot_ttl: timedelta = SNAPSHOT_TTL,
                 acquire: Callable[[str], SurfaceMiningSnapshot] | None = None):
        if snapshot_ttl < timedelta(0):
            raise ValueError("snapshot_ttl must be non-negative")
        self.snapshot_ttl = snapshot_ttl
        self._snapshots: dict[int, SurfaceMiningSnapshot] = {}
        self._snapshot_names: dict[str, int] = {}
        self._uses_default_acquire = acquire is None
        self._acquire = acquire or self._acquire_snapshot

    def snapshot_for(self, system_name: str, *, now: datetime | None = None,
                     force: bool = False,
                     context: AcquisitionContext | None = None,
                     on_acquisition: Callable[[], None] | None = None) -> SurfaceMiningSnapshot:
        """Return a reusable snapshot or acquire fresh data.

        ``on_acquisition`` runs immediately before a cache miss or forced
        request starts its acquisition.
        """
        requested = system_name.strip()
        if not requested:
            raise ValueError("system name cannot be empty")
        current = _now(now)
        if not force:
            resolved = self._find_cached(requested)
            if resolved is not None and current - resolved.acquired_at < self.snapshot_ttl:
                return resolved
        if on_acquisition is not None:
            on_acquisition()
        try:
            context = context or AcquisitionContext.with_timeout(ACQUISITION_TIMEOUT)
            if self._uses_default_acquire:
                snapshot = self._acquire(requested, context=context)
            else:
                snapshot = self._acquire(requested)
        except SystemNotFoundError:
            raise
        except SurfaceMiningError:
            raise
        except (AcquisitionCancelled, AcquisitionDeadlineExceeded):
            raise
        except Exception as exc:
            raise MarketAcquisitionError("Unable to retrieve market data.") from exc
        self._snapshots[snapshot.system_id64] = snapshot
        self._snapshot_names[requested.casefold()] = snapshot.system_id64
        self._snapshot_names[snapshot.system_name.casefold()] = snapshot.system_id64
        return snapshot

    def analyze(self, snapshot: SurfaceMiningSnapshot, *, top_products: int = 3,
                top_markets: int = 3, minimum_demand: int = 100,
                summaries: CommoditySummaryResult | None = None,
                now: datetime | None = None) -> SurfaceMiningAnalysis:
        """Recalculate all eligible products and markets without network I/O."""
        if not 3 <= top_products <= 10:
            raise ValueError("top_products must be between 3 and 10")
        if not 3 <= top_markets <= 5:
            raise ValueError("top_markets must be between 3 and 5")
        if minimum_demand < 0:
            raise ValueError("minimum_demand must be non-negative")
        current = _now(now)
        summary_by_name = {item.commodity.casefold(): item for item in summaries.summaries} if summaries else {}
        products = []
        issues_by_station: dict[tuple[str, str | None], MarketIssue] = {}
        ranked_by_product: dict[str, tuple[MarketObservation, ...]] = {}
        for result in snapshot.market_results:
            eligible = []
            for observation in result.observations:
                freshness = classify_market_freshness(observation, now=current)
                if freshness == "too_old":
                    key = (observation.station.system_name.casefold(), observation.station.market_id or observation.station.name.casefold())
                    issues_by_station.setdefault(key, MarketIssue(
                        observation.station.name, "Market data is too old.", "too_old"
                    ))
                elif freshness == "age_unknown":
                    key = (observation.station.system_name.casefold(), observation.station.market_id or observation.station.name.casefold())
                    issues_by_station.setdefault(key, MarketIssue(
                        observation.station.name, "Market age is unknown.", "age_unknown"
                    ))
                else:
                    eligible.append(observation)
            filtered = filter_market_observations(
                eligible, exclude_carriers=True,
                demand_greater_than=minimum_demand,
                require_positive_sell_price=True,
            )
            ranked = rank_market_observations(filtered)
            if ranked:
                compatible = planet_types_for_commodities((result.requested_commodity,)).get(result.requested_commodity, frozenset())
                bodies = tuple(body.name for body in snapshot.bodies if body.canonical_planet_type in compatible)
                ranked_by_product[result.requested_commodity] = ranked
                products.append(SurfaceMiningProduct(
                    result.requested_commodity, bodies, ranked[:top_markets],
                    summary_by_name.get(result.requested_commodity.casefold()),
                ))
            for issue in result.issues:
                if not is_carrier_name(issue.station_name):
                    key = (snapshot.system_name.casefold(), issue.station_name.casefold())
                    category = issue.category
                    if category == "other" and issue.message == "Station has no valid market data.":
                        category = "no_valid_data"
                    issues_by_station.setdefault(key, MarketIssue(
                        issue.station_name, issue.message, category
                    ))
        ordered_observations = rank_market_observations(
            observation
            for observations in ranked_by_product.values()
            for observation in observations
        )
        selected_names = []
        seen = set()
        for item in ordered_observations:
            if item.commodity not in seen:
                seen.add(item.commodity)
                selected_names.append(item.commodity)
                if len(selected_names) >= top_products:
                    break
        products_by_name = {item.commodity: item for item in products}
        selected = tuple(products_by_name[name] for name in selected_names)
        eligible_market_count = len({
            _market_identity(observation)
            for observations in ranked_by_product.values()
            for observation in observations
        })
        return SurfaceMiningAnalysis(
            snapshot.system_name, selected, tuple(issues_by_station.values()),
            snapshot.bodies, eligible_market_count, minimum_demand,
        )

    def _find_cached(self, name: str) -> SurfaceMiningSnapshot | None:
        snapshot_id = self._snapshot_names.get(name.casefold())
        return self._snapshots.get(snapshot_id) if snapshot_id is not None else None

    @staticmethod
    def _acquire_snapshot(
        system_name: str,
        *,
        context: AcquisitionContext | None = None,
    ) -> SurfaceMiningSnapshot:
        context = context or AcquisitionContext.with_timeout(ACQUISITION_TIMEOUT)
        try:
            system = resolve_system(system_name, context=context)
        except SpanshSystemNotFoundError as exc:
            raise SystemNotFoundError("System not found.") from exc
        except (AcquisitionCancelled, AcquisitionDeadlineExceeded):
            raise
        except SpanshError as exc:
            raise MarketAcquisitionError("Unable to retrieve market data.") from exc
        except (OSError, ValueError) as exc:
            raise MarketAcquisitionError("Unable to retrieve market data.") from exc
        try:
            bodies = fetch_landable_bodies(system, context=context)
            commodities = commodities_for_planet_types(body.canonical_planet_type for body in bodies)
            results = fetch_commodity_markets(
                system.name, commodities,
                exclude_station=is_carrier_name,
                resolved_system=system,
                context=context,
            )
        except (AcquisitionCancelled, AcquisitionDeadlineExceeded):
            raise
        except Exception as exc:
            raise MarketAcquisitionError("Unable to retrieve market data.") from exc
        return SurfaceMiningSnapshot(
            system.name, system.id64, tuple(bodies), tuple(commodities), tuple(results),
            datetime.now(timezone.utc),
        )
