"""Spansh acquisition and mapping for one system commodity market."""

from datetime import datetime, timezone
from typing import Any

import requests

from .commodities import canonical_commodity_name, normalize_name
from .models import (
    CommodityMarketResult,
    LandingPad,
    MarketIssue,
    MarketObservation,
    Station,
)

_BASE_URL = "https://spansh.co.uk/api"
_REQUEST_TIMEOUT = 25
_SYSTEM_PAGE_SIZE = 100


class SpanshError(RuntimeError):
    """A fatal Spansh failure prevented a trustworthy system-level result."""


def fetch_commodity_market(
    system_name: str,
    commodity_name: str,
    *,
    session: requests.Session | None = None,
) -> CommodityMarketResult:
    """Fetch one commodity's observations across a Spansh system.

    An injected session is reused and remains caller-owned. Recoverable station
    failures are returned as issues; failures that prevent trustworthy system
    discovery raise :class:`SpanshError`.
    """
    if session is not None:
        return _fetch_with_session(session, system_name, commodity_name)

    owned_session = requests.Session()
    try:
        return _fetch_with_session(owned_session, system_name, commodity_name)
    finally:
        owned_session.close()


def _fetch_with_session(
    session: requests.Session,
    requested_system: str,
    requested_commodity: str,
) -> CommodityMarketResult:
    system_id = _find_system_id(session, requested_system)
    if system_id is None:
        raise SpanshError(f"System {requested_system!r} was not found by exact name.")

    system_record = _fetch_record(session, "GET", f"/system/{system_id}")
    actual_system = system_record.get("name")
    if (
        not isinstance(actual_system, str)
        or actual_system.casefold() != requested_system.casefold()
    ):
        raise SpanshError("Spansh system detail did not match the requested system.")

    try:
        stations, discovery_issues = _collect_stations(system_record)
    except ValueError as exc:
        raise SpanshError("Spansh returned an unusable system station listing.") from exc

    canonical_requested = canonical_commodity_name(requested_commodity)
    requested_key = normalize_name(canonical_requested or requested_commodity)
    observations = []
    issues = list(discovery_issues)

    for market_id, discovery_record in stations.items():
        station_name = _station_name(discovery_record)
        if not _is_market_candidate(discovery_record):
            continue

        numeric_id = _usable_market_id(market_id)
        if numeric_id is None:
            issues.append(MarketIssue(station_name, "Station has no usable market_id."))
            continue

        try:
            record = _fetch_record(session, "GET", f"/station/{numeric_id}")
            detail_system = record.get("system_name")
            if (
                not isinstance(detail_system, str)
                or detail_system.casefold() != requested_system.casefold()
            ):
                raise ValueError("Station detail belongs to a different or unknown system.")
            if record.get("has_market") is False:
                continue

            station = _map_station(record, numeric_id)
            market = record.get("market")
            if not isinstance(market, list):
                raise ValueError("Station detail has no valid market list.")
            station_observations, malformed_rows = _map_matching_rows(
                market,
                station,
                requested_commodity,
                canonical_requested,
                requested_key,
                record,
            )
            observations.extend(station_observations)
            issues.extend(malformed_rows)
        except (SpanshError, ValueError, TypeError, KeyError) as exc:
            issues.append(MarketIssue(station_name, str(exc)))

    result_commodity = canonical_requested or requested_commodity
    return CommodityMarketResult(result_commodity, tuple(observations), tuple(issues))


def _find_system_id(session: requests.Session, requested_name: str) -> str | int | None:
    page = 0
    seen_ids: set[str] = set()

    while True:
        payload = _request_json(
            session,
            "POST",
            "/systems/search",
            json={
                "filters": {"name": {"value": requested_name}},
                "size": _SYSTEM_PAGE_SIZE,
                "page": page,
            },
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
        exact_match: str | int | None = None
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
                exact_match = identifier
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
) -> dict[str, Any]:
    payload = _request_json(session, method, path)
    record = payload.get("record")
    if not isinstance(record, dict):
        raise SpanshError(f"Spansh response for {path} has no usable record.")
    return record


def _request_json(
    session: requests.Session,
    method: str,
    path: str,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        response = session.request(
            method,
            _BASE_URL + path,
            timeout=_REQUEST_TIMEOUT,
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


def _map_matching_rows(
    market: list[Any],
    station: Station,
    requested_commodity: str,
    canonical_requested: str | None,
    requested_key: str,
    station_record: dict[str, Any],
) -> tuple[list[MarketObservation], list[MarketIssue]]:
    observations = []
    issues = []
    for row in market:
        if not isinstance(row, dict):
            issues.append(MarketIssue(station.name, "Market contains a malformed row."))
            continue
        raw_name = row.get("commodity")
        if not isinstance(raw_name, str) or not raw_name:
            issues.append(MarketIssue(station.name, "Market row has no usable commodity name."))
            continue
        if not _commodity_matches(
            raw_name,
            requested_commodity,
            canonical_requested,
            requested_key,
        ):
            continue

        try:
            sell_price = _optional_integer(row.get("sell_price"), "sell_price")
            demand = _optional_integer(row.get("demand"), "demand")
            supply = _optional_integer(row.get("supply"), "supply")
        except ValueError as exc:
            issues.append(MarketIssue(station.name, f"Malformed data for {raw_name!r}: {exc}"))
            continue
        observations.append(
            MarketObservation(
                station=station,
                commodity=canonical_requested or raw_name,
                sell_price=sell_price,
                demand=demand,
                supply=supply,
                market_updated_at=_parse_utc(station_record.get("market_updated_at")),
                station_updated_at=_parse_utc(station_record.get("updated_at")),
            )
        )
    return observations, issues


def _commodity_matches(
    raw_name: str,
    requested_name: str,
    canonical_requested: str | None,
    requested_key: str,
) -> bool:
    if canonical_requested is not None:
        return canonical_commodity_name(raw_name) == canonical_requested
    raw_key = normalize_name(raw_name)
    if requested_key and raw_key:
        return raw_key == requested_key
    return raw_name.casefold() == requested_name.casefold()


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
