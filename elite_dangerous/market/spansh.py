"""Spansh acquisition and mapping for system commodity markets."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic, perf_counter
from typing import Any

import requests

from .commodities import canonical_commodity_name
from .models import (
    CommodityMarketResult,
    LandableBody,
    LandingPad,
    MarketIssue,
    MarketObservation,
    Station,
    _commodity_key,
)

_BASE_URL = "https://spansh.co.uk/api"
_REQUEST_TIMEOUT = 25
ACQUISITION_TIMEOUT = 30.0
_SYSTEM_PAGE_SIZE = 100
_BODY_PAGE_SIZE = 100
_CANONICAL_PLANET_TYPES_BY_SUBTYPE = {
    "High metal content world": "High metal content",
    "Metal-rich body": "Metal Rich",
    "Rocky body": "Rocky",
    "Rocky Ice world": "Rocky Ice",
    "Icy body": "Icy",
}


class SpanshError(RuntimeError):
    """A fatal Spansh failure prevented a trustworthy system-level result."""


class AcquisitionCancelled(SpanshError):
    """A cooperative acquisition cancellation was requested."""


class AcquisitionDeadlineExceeded(SpanshError):
    """The complete acquisition operation exceeded its deadline."""


@dataclass
class AcquisitionContext:
    """Monotonic deadline and cooperative cancellation state for one operation."""

    deadline: float | None = None
    cancelled: bool = False
    clock: Callable[[], float] = monotonic

    @classmethod
    def with_timeout(cls, timeout: float = ACQUISITION_TIMEOUT, *, clock=monotonic):
        return cls(clock() + timeout, clock=clock)

    def cancel(self) -> None:
        self.cancelled = True

    def check(self) -> None:
        if self.cancelled:
            raise AcquisitionCancelled("Surface Mining acquisition was cancelled.")
        if self.deadline is not None and self.clock() >= self.deadline:
            raise AcquisitionDeadlineExceeded("Surface Mining acquisition deadline exceeded.")

    def remaining(self) -> float | None:
        if self.cancelled:
            raise AcquisitionCancelled("Surface Mining acquisition was cancelled.")
        if self.deadline is None:
            return None
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise AcquisitionDeadlineExceeded("Surface Mining acquisition deadline exceeded.")
        return remaining


class SpanshSystemNotFoundError(SpanshError):
    """The exact requested system was not returned by Spansh."""


@dataclass(frozen=True)
class ResolvedSystem:
    """Exact Spansh system identity reusable across related acquisitions."""

    name: str
    id64: str | int


@dataclass
class MarketDiagnostics:
    """Optional acquisition counters and timings for live diagnostics."""

    market_candidates: int = 0
    carriers_excluded: int = 0
    excluded_carrier_names: list[str] | None = None
    invalid_market_ids: int = 0
    station_requests_attempted: int = 0
    station_requests_succeeded: int = 0
    station_requests_failed: int = 0
    station_http_elapsed: float = 0.0
    system_detail_elapsed: float = 0.0
    dump_requests_attempted: int = 0
    dump_requests_succeeded: int = 0
    dump_requests_failed: int = 0
    dump_http_elapsed: float = 0.0
    dump_station_records: int = 0
    dump_market_records: int = 0
    slowest_station_requests: list[tuple[str, float]] | None = None

    def __post_init__(self) -> None:
        if self.excluded_carrier_names is None:
            self.excluded_carrier_names = []
        if self.slowest_station_requests is None:
            self.slowest_station_requests = []

    def record_station(self, name: str, elapsed: float, succeeded: bool) -> None:
        self.station_http_elapsed += elapsed
        if succeeded:
            self.station_requests_succeeded += 1
        else:
            self.station_requests_failed += 1
        self.slowest_station_requests.append((name, elapsed))
        self.slowest_station_requests.sort(key=lambda item: item[1], reverse=True)
        del self.slowest_station_requests[5:]


def resolve_system(
    system_name: str,
    *,
    session: requests.Session | None = None,
    context: AcquisitionContext | None = None,
) -> ResolvedSystem:
    """Resolve an exact system name to its reusable Spansh identity."""
    if session is not None:
        return _resolve_system_with_session(session, system_name, context=context)

    owned_session = requests.Session()
    try:
        return _resolve_system_with_session(owned_session, system_name, context=context)
    finally:
        owned_session.close()


def fetch_landable_planet_subtypes(
    system: ResolvedSystem,
    *,
    session: requests.Session | None = None,
    context: AcquisitionContext | None = None,
) -> tuple[str, ...]:
    """Return unique subtypes from explicitly landable planets in a system."""
    if not isinstance(system, ResolvedSystem):
        raise TypeError("system must be a ResolvedSystem")
    if session is not None:
        return _fetch_landable_planet_subtypes_with_session(session, system, context=context)

    owned_session = requests.Session()
    try:
        return _fetch_landable_planet_subtypes_with_session(owned_session, system, context=context)
    finally:
        owned_session.close()


def fetch_landable_bodies(
    system: ResolvedSystem,
    *,
    session: requests.Session | None = None,
    context: AcquisitionContext | None = None,
) -> tuple[LandableBody, ...]:
    """Return eligible landable planets with confirmed canonical types."""
    if not isinstance(system, ResolvedSystem):
        raise TypeError("system must be a ResolvedSystem")
    if session is not None:
        return _fetch_landable_bodies_with_session(session, system, context=context)

    owned_session = requests.Session()
    try:
        return _fetch_landable_bodies_with_session(owned_session, system, context=context)
    finally:
        owned_session.close()


def canonical_planet_types_from_spansh(
    subtypes: Iterable[str],
) -> tuple[str, ...]:
    """Map confirmed Spansh subtypes to unique canonical RSM planet types."""
    if isinstance(subtypes, (str, bytes)):
        raise TypeError("subtypes must be an iterable of subtype names")
    mapped = set()
    for subtype in subtypes:
        if not isinstance(subtype, str):
            raise TypeError("subtype names must be strings")
        canonical = _CANONICAL_PLANET_TYPES_BY_SUBTYPE.get(subtype)
        if canonical is not None:
            mapped.add(canonical)
    return tuple(
        canonical
        for canonical in _CANONICAL_PLANET_TYPES_BY_SUBTYPE.values()
        if canonical in mapped
    )


def fetch_commodity_market(
    system_name: str,
    commodity_name: str,
    *,
    session: requests.Session | None = None,
    exclude_station: Callable[[str], bool] | None = None,
    resolved_system: ResolvedSystem | None = None,
    diagnostics: MarketDiagnostics | None = None,
    context: AcquisitionContext | None = None,
) -> CommodityMarketResult:
    """Fetch one commodity's observations across a Spansh system."""
    return fetch_commodity_markets(
        system_name,
        (commodity_name,),
        session=session,
        exclude_station=exclude_station,
        resolved_system=resolved_system,
        diagnostics=diagnostics,
        context=context,
    )[0]


def fetch_commodity_markets(
    system_name: str,
    commodity_names: Iterable[str],
    *,
    session: requests.Session | None = None,
    exclude_station: Callable[[str], bool] | None = None,
    resolved_system: ResolvedSystem | None = None,
    diagnostics: MarketDiagnostics | None = None,
    context: AcquisitionContext | None = None,
) -> tuple[CommodityMarketResult, ...]:
    """Fetch several commodity results in one Spansh system traversal.

    An injected session is reused and remains caller-owned. Recoverable station
    failures are returned as issues; failures that prevent trustworthy system
    discovery raise :class:`SpanshError`. Duplicate commodity identities are
    returned once, in their first requested order.
    """
    if isinstance(commodity_names, (str, bytes)):
        raise TypeError("commodity_names must be an iterable of commodity names")
    requested_names = tuple(commodity_names)
    if any(not isinstance(name, str) for name in requested_names):
        raise TypeError("commodity names must be strings")

    requested_by_key: dict[str, str] = {}
    for name in requested_names:
        canonical = canonical_commodity_name(name)
        requested_by_key.setdefault(
            _commodity_key(canonical or name),
            canonical or name,
        )

    if not requested_by_key:
        return ()

    if session is not None:
        return _fetch_commodities_with_session(
            session,
            system_name,
            requested_by_key,
            exclude_station=exclude_station,
            resolved_system=resolved_system,
            diagnostics=diagnostics,
            context=context,
        )

    owned_session = requests.Session()
    try:
        return _fetch_commodities_with_session(
            owned_session,
            system_name,
            requested_by_key,
            exclude_station=exclude_station,
            resolved_system=resolved_system,
            diagnostics=diagnostics,
            context=context,
        )
    finally:
        owned_session.close()


def _fetch_commodities_with_session(
    session: requests.Session,
    requested_system: str,
    requested_by_key: dict[str, str],
    *,
    exclude_station: Callable[[str], bool] | None,
    resolved_system: ResolvedSystem | None,
    diagnostics: MarketDiagnostics | None,
    context: AcquisitionContext | None,
) -> tuple[CommodityMarketResult, ...]:
    if context is not None:
        context.check()
    system = resolved_system or _resolve_system_with_session(
        session, requested_system, context=context
    )
    if system.name.casefold() != requested_system.casefold():
        raise ValueError("resolved_system does not match the requested system")

    system_started = perf_counter()
    try:
        system_record = _fetch_record(
            session, "GET", f"/system/{system.id64}", context=context
        )
    finally:
        if diagnostics is not None:
            diagnostics.system_detail_elapsed = perf_counter() - system_started
    actual_system = system_record.get("name")
    if (
        not isinstance(actual_system, str)
        or actual_system.casefold() != requested_system.casefold()
    ):
        raise SpanshError("Spansh system detail did not match the requested system.")

    dump_started = perf_counter()
    if diagnostics is not None:
        diagnostics.dump_requests_attempted += 1
    try:
        dump_system = _fetch_dump_system(session, system.id64, context=context)
        dump_stations, discovery_issues = _collect_dump_stations(
            dump_system,
            requested_system,
            exclude_station=exclude_station,
            diagnostics=diagnostics,
        )
        if diagnostics is not None:
            diagnostics.dump_station_records = _count_dump_stations(dump_system)
            diagnostics.dump_market_records = sum(
                isinstance(record.get("market"), dict)
                for record in dump_stations.values()
            )
    except SpanshError:
        if diagnostics is not None:
            diagnostics.dump_requests_failed += 1
        raise
    except ValueError as exc:
        if diagnostics is not None:
            diagnostics.dump_requests_failed += 1
        raise SpanshError("Spansh returned an unusable system dump.") from exc
    else:
        if diagnostics is not None:
            diagnostics.dump_requests_succeeded += 1
    finally:
        if diagnostics is not None:
            diagnostics.dump_http_elapsed = perf_counter() - dump_started

    observations_by_key: dict[str, list[MarketObservation]] = {
        key: [] for key in requested_by_key
    }
    issues_by_key: dict[str, list[MarketIssue]] = {
        key: list(discovery_issues) for key in requested_by_key
    }

    def add_shared_issue(issue: MarketIssue) -> None:
        for commodity_issues in issues_by_key.values():
            commodity_issues.append(issue)

    for market_id, record in dump_stations.items():
        station_name = _station_name(record)

        numeric_id = _usable_market_id(market_id)
        if numeric_id is None:
            if diagnostics is not None:
                diagnostics.invalid_market_ids += 1
            add_shared_issue(
                MarketIssue(station_name, "Station has no usable market_id.")
            )
            continue

        try:
            station = _map_station(record, numeric_id)
            market = record.get("market")
            if not isinstance(market, list):
                raise ValueError("Station detail has no valid market list.")
            station_observations, row_issues, shared_row_issues = _map_requested_rows(
                market,
                station,
                requested_by_key,
                record,
            )
            for key, mapped in station_observations.items():
                observations_by_key[key].extend(mapped)
            for key, mapped_issues in row_issues.items():
                issues_by_key[key].extend(mapped_issues)
            for issue in shared_row_issues:
                add_shared_issue(issue)
        except (SpanshError, ValueError, TypeError, KeyError) as exc:
            add_shared_issue(MarketIssue(station_name, str(exc)))

    return tuple(
        CommodityMarketResult(
            requested_commodity=commodity,
            observations=tuple(observations_by_key[key]),
            issues=tuple(issues_by_key[key]),
        )
        for key, commodity in requested_by_key.items()
    )


def _resolve_system_with_session(
    session: requests.Session,
    requested_name: str,
    *,
    context: AcquisitionContext | None = None,
) -> ResolvedSystem:
    system = _find_system(session, requested_name, context=context)
    if system is None:
        raise SpanshSystemNotFoundError(
            f"System {requested_name!r} was not found by exact name."
        )
    return system


def _fetch_landable_planet_subtypes_with_session(
    session: requests.Session,
    system: ResolvedSystem,
    *,
    context: AcquisitionContext | None = None,
) -> tuple[str, ...]:
    seen: set[str] = set()
    subtypes = []
    for item in _fetch_landable_body_rows_with_session(session, system, context=context):
        subtype = item.get("subtype")
        if isinstance(subtype, str) and subtype not in seen:
            seen.add(subtype)
            subtypes.append(subtype)
    return tuple(subtypes)


def _fetch_landable_body_rows_with_session(
    session: requests.Session,
    system: ResolvedSystem,
    *,
    context: AcquisitionContext | None = None,
) -> tuple[dict[str, Any], ...]:
    page = 0
    seen_ids: set[str] = set()
    rows: list[dict[str, Any]] = []

    while True:
        if context is not None:
            context.check()
        payload = _request_json(
            session,
            "POST",
            "/bodies/search",
            json={
                "filters": {
                    "system_id64": {"value": str(system.id64)},
                    "is_landable": {"value": True},
                    "type": {"value": ["Planet"]},
                },
                "sort": [],
                "size": _BODY_PAGE_SIZE,
                "page": page,
            },
            context=context,
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise SpanshError("Spansh body search response has no results list.")
        count = payload.get("count")
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count < 0
        ):
            raise SpanshError("Spansh body search response has an invalid result count.")
        if count is not None and count < len(results):
            raise SpanshError("Spansh body search result count is inconsistent.")

        page_ids = set()
        for item in results:
            if not isinstance(item, dict):
                raise SpanshError("Spansh body search contains an invalid result.")
            identifier = item.get("id64")
            usable_identifier = (
                isinstance(identifier, int)
                and not isinstance(identifier, bool)
                and identifier >= 0
            ) or (isinstance(identifier, str) and identifier.isdecimal())
            if not usable_identifier:
                raise SpanshError("Spansh body search result has no usable id64.")
            page_ids.add(str(identifier))
            if str(item.get("system_id64")) != str(system.id64):
                raise SpanshError("Spansh body search returned a body from another system.")
            if item.get("is_landable") is not True or item.get("type") != "Planet":
                continue
            subtype = item.get("subtype")
            name = item.get("name")
            if isinstance(subtype, str) and isinstance(name, str) and name:
                rows.append(item)

        if not results:
            if count is not None and len(seen_ids) < count:
                raise SpanshError(
                    "Spansh body search ended before its reported result count."
                )
            return tuple(rows)
        if page_ids.issubset(seen_ids):
            raise SpanshError("Spansh repeated a body search page before completion.")
        seen_ids.update(page_ids)
        if count is not None and len(seen_ids) >= count:
            return tuple(rows)
        if count is None and len(results) < _BODY_PAGE_SIZE:
            return tuple(rows)
        page += 1


def _fetch_landable_bodies_with_session(
    session: requests.Session,
    system: ResolvedSystem,
    *,
    context: AcquisitionContext | None = None,
) -> tuple[LandableBody, ...]:
    rows = _fetch_landable_body_rows_with_session(session, system, context=context)
    bodies = []
    for item in rows:
        subtype = item.get("subtype")
        canonical = _CANONICAL_PLANET_TYPES_BY_SUBTYPE.get(subtype)
        if canonical is not None:
            bodies.append(LandableBody(item["name"], canonical))
    return tuple(bodies)


def _find_system(
    session: requests.Session,
    requested_name: str,
    *,
    context: AcquisitionContext | None = None,
) -> ResolvedSystem | None:
    page = 0
    seen_ids: set[str] = set()

    while True:
        if context is not None:
            context.check()
        payload = _request_json(
            session,
            "POST",
            "/systems/search",
            json={
                "filters": {"name": {"value": requested_name}},
                "size": _SYSTEM_PAGE_SIZE,
                "page": page,
            },
            context=context,
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise SpanshError("Spansh system search response has no results list.")

        count = payload.get("count")
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count < 0
        ):
            raise SpanshError("Spansh system search response has an invalid result count.")
        if count is not None and count < len(results):
            raise SpanshError("Spansh system search result count is inconsistent.")

        page_ids = set()
        exact_match: ResolvedSystem | None = None
        for item in results:
            if not isinstance(item, dict):
                raise SpanshError("Spansh system search contains an invalid result.")
            name = item.get("name")
            identifier = item.get("id64")
            usable_identifier = (
                isinstance(identifier, int)
                and not isinstance(identifier, bool)
                and identifier >= 0
            ) or (isinstance(identifier, str) and identifier.isdecimal())
            if not isinstance(name, str) or not usable_identifier:
                raise SpanshError("Spansh system search result has no usable name or id64.")
            page_ids.add(str(identifier))
            if name.casefold() == requested_name.casefold():
                exact_match = ResolvedSystem(name, identifier)
                break

        if exact_match is not None:
            return exact_match
        if not results:
            if count is not None and len(seen_ids) < count:
                raise SpanshError(
                    "Spansh system search ended before its reported result count."
                )
            return None
        if page_ids.issubset(seen_ids):
            raise SpanshError("Spansh repeated a system search page before search completion.")

        seen_ids.update(page_ids)
        if count is not None and len(seen_ids) >= count:
            return None
        if count is None and len(results) < _SYSTEM_PAGE_SIZE:
            return None
        page += 1


def _collect_stations(
    system_record: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], tuple[MarketIssue, ...]]:
    stations: dict[str, dict[str, Any]] = {}
    issues = []

    def visit(node: dict[str, Any]) -> None:
        station_records = node.get("stations", [])
        bodies = node.get("bodies", [])
        if not isinstance(station_records, list) or not isinstance(bodies, list):
            raise ValueError("System station or body listing is not a list.")
        for station in station_records:
            if not isinstance(station, dict):
                issues.append(MarketIssue("<unknown station>", "Invalid station discovery record."))
                continue
            market_id = station.get("market_id")
            if market_id is None:
                if _is_market_candidate(station):
                    issues.append(
                        MarketIssue(
                            _station_name(station),
                            "Station has no usable market_id.",
                        )
                    )
                continue
            key = str(market_id)
            stations[key] = station
        for body in bodies:
            if not isinstance(body, dict):
                raise ValueError("System body listing contains an invalid record.")
            visit(body)

    visit(system_record)
    return stations, tuple(issues)


def _collect_dump_stations(
    dump_system: dict[str, Any],
    requested_system: str,
    *,
    exclude_station: Callable[[str], bool] | None,
    diagnostics: MarketDiagnostics | None,
) -> tuple[dict[str, dict[str, Any]], tuple[MarketIssue, ...]]:
    """Adapt recursively nested dump stations to the market mapper shape."""
    name = dump_system.get("name")
    if not isinstance(name, str) or name.casefold() != requested_system.casefold():
        raise SpanshError("Spansh dump system did not match the requested system.")

    stations: dict[str, dict[str, Any]] = {}
    issues: list[MarketIssue] = []

    def visit(node: dict[str, Any]) -> None:
        station_records = node.get("stations", [])
        bodies = node.get("bodies", [])
        if not isinstance(station_records, list) or not isinstance(bodies, list):
            raise ValueError("Spansh dump station or body listing is not a list.")
        for raw_station in station_records:
            if not isinstance(raw_station, dict):
                issues.append(MarketIssue("<unknown station>", "Invalid dump station record."))
                continue
            station_name = _station_name(raw_station)
            if diagnostics is not None:
                diagnostics.market_candidates += 1
            if exclude_station is not None and exclude_station(station_name):
                if diagnostics is not None:
                    diagnostics.carriers_excluded += 1
                    diagnostics.excluded_carrier_names.append(station_name)
                continue
            station_id = raw_station.get("id")
            numeric_id = _usable_market_id(str(station_id)) if station_id is not None else None
            if numeric_id is None:
                issues.append(MarketIssue(station_name, "Station has no usable market_id."))
                continue
            market = raw_station.get("market")
            if not isinstance(market, dict):
                issues.append(MarketIssue(station_name, "Station has no valid market data."))
                continue
            commodities = market.get("commodities")
            if not isinstance(commodities, list):
                issues.append(MarketIssue(station_name, "Station market has no valid commodity list."))
                continue
            pads = raw_station.get("landingPads")
            if pads is not None and not isinstance(pads, dict):
                issues.append(MarketIssue(station_name, "Station has invalid landing-pad data."))
                continue
            stations[str(numeric_id)] = _adapt_dump_station(
                raw_station, requested_system, market, pads or {}
            )
        for body in bodies:
            if not isinstance(body, dict):
                raise ValueError("Spansh dump body listing contains an invalid record.")
            visit(body)

    visit(dump_system)
    return stations, tuple(issues)


def _adapt_dump_station(
    raw_station: dict[str, Any],
    system_name: str,
    market: dict[str, Any],
    pads: dict[str, Any],
) -> dict[str, Any]:
    """Translate one dump station into the existing station-detail shape."""
    commodity_rows = market.get("commodities")
    if not isinstance(commodity_rows, list):
        commodity_rows = []
    return {
        "name": raw_station.get("name"),
        "system_name": system_name,
        "market_id": raw_station.get("id"),
        "is_planetary": None,
        "has_large_pad": _positive_pad_count(pads.get("large")),
        "large_pads": pads.get("large"),
        "medium_pads": pads.get("medium"),
        "small_pads": pads.get("small"),
        "market_updated_at": market.get("updateTime"),
        "updated_at": raw_station.get("updateTime"),
        "market": [
            row
            if not isinstance(row, dict)
            else {
                "commodity": row.get("name"),
                "sell_price": row.get("sellPrice"),
                "demand": row.get("demand"),
                "supply": row.get("supply"),
            }
            for row in commodity_rows
        ],
    }


def _positive_pad_count(value: Any) -> bool:
    """Return whether a dump large-pad count represents capability."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _count_dump_stations(node: dict[str, Any]) -> int:
    """Count station records recursively for aggregate diagnostics."""
    stations = node.get("stations", [])
    bodies = node.get("bodies", [])
    if not isinstance(stations, list) or not isinstance(bodies, list):
        return 0
    return len(stations) + sum(
        _count_dump_stations(body)
        for body in bodies
        if isinstance(body, dict)
    )


def _is_market_candidate(record: dict[str, Any]) -> bool:
    services = record.get("services", [])
    return record.get("has_market") is True or (
        isinstance(services, list) and "Market" in services
    )


def _station_name(record: dict[str, Any]) -> str:
    name = record.get("name")
    return name if isinstance(name, str) and name else "<unknown station>"


def _usable_market_id(market_id: str) -> int | None:
    value = market_id.strip()
    if not value.isdecimal():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _fetch_record(
    session: requests.Session,
    method: str,
    path: str,
    *,
    context: AcquisitionContext | None = None,
) -> dict[str, Any]:
    payload = _request_json(session, method, path, context=context)
    record = payload.get("record")
    if not isinstance(record, dict):
        raise SpanshError(f"Spansh response for {path} has no usable record.")
    return record


def _fetch_dump_system(
    session: requests.Session,
    system_id64: str | int,
    *,
    context: AcquisitionContext | None = None,
) -> dict[str, Any]:
    """Fetch and validate the aggregate system dump envelope."""
    payload = _request_json(session, "GET", f"/dump/{system_id64}", context=context)
    system = payload.get("system")
    if not isinstance(system, dict):
        raise SpanshError("Spansh dump response has no usable system record.")
    return system


def _request_json(
    session: requests.Session,
    method: str,
    path: str,
    context: AcquisitionContext | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    timeout = _REQUEST_TIMEOUT
    if context is not None:
        remaining = context.remaining()
        if remaining <= 0:
            context.check()
        timeout = min(timeout, remaining)
    try:
        response = session.request(
            method,
            _BASE_URL + path,
            timeout=timeout,
            **kwargs,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SpanshError(f"Spansh request {method} {path} failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise SpanshError(f"Spansh response for {path} is not an object.")
    return payload


def _map_station(record: dict[str, Any], market_id: int) -> Station:
    name = record.get("name")
    system_name = record.get("system_name")
    if not isinstance(name, str) or not name or not isinstance(system_name, str):
        raise ValueError("Station detail has no usable station or system name.")
    is_planetary = record.get("is_planetary")
    if is_planetary is not None and not isinstance(is_planetary, bool):
        raise ValueError("Station detail has an invalid planetary flag.")

    return Station(
        name=name,
        market_id=str(market_id),
        system_name=system_name,
        is_planetary=is_planetary,
        max_landing_pad=_max_landing_pad(record),
    )


def _max_landing_pad(record: dict[str, Any]) -> LandingPad | None:
    if record.get("has_large_pad") is True:
        return "L"
    for field, size in (("large_pads", "L"), ("medium_pads", "M"), ("small_pads", "S")):
        count = record.get(field)
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            return size
    return None


def _map_requested_rows(
    market: list[Any],
    station: Station,
    requested_by_key: dict[str, str],
    station_record: dict[str, Any],
) -> tuple[
    dict[str, list[MarketObservation]],
    dict[str, list[MarketIssue]],
    list[MarketIssue],
]:
    observations: dict[str, list[MarketObservation]] = {
        key: [] for key in requested_by_key
    }
    issues: dict[str, list[MarketIssue]] = {key: [] for key in requested_by_key}
    shared_issues: list[MarketIssue] = []
    for row in market:
        if not isinstance(row, dict):
            shared_issues.append(
                MarketIssue(station.name, "Market contains a malformed row.")
            )
            continue
        raw_name = row.get("commodity")
        if not isinstance(raw_name, str) or not raw_name:
            shared_issues.append(
                MarketIssue(station.name, "Market row has no usable commodity name.")
            )
            continue
        key = _commodity_key(raw_name)
        if key not in requested_by_key:
            continue

        try:
            sell_price = _optional_integer(row.get("sell_price"), "sell_price")
            demand = _optional_integer(row.get("demand"), "demand")
            supply = _optional_integer(row.get("supply"), "supply")
        except ValueError as exc:
            issues[key].append(
                MarketIssue(station.name, f"Malformed data for {raw_name!r}: {exc}")
            )
            continue
        canonical = canonical_commodity_name(raw_name)
        observations[key].append(
            MarketObservation(
                station=station,
                commodity=canonical or raw_name,
                sell_price=sell_price,
                demand=demand,
                supply=supply,
                market_updated_at=_parse_utc(station_record.get("market_updated_at")),
                station_updated_at=_parse_utc(station_record.get("updated_at")),
            )
        )
    return observations, issues, shared_issues


def _optional_integer(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer or None.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    raise ValueError(f"{field_name} must be an integer or None.")


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None
