import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import requests

from elite_dangerous.market import (
    AcquisitionCancelled,
    AcquisitionContext,
    AcquisitionDeadlineExceeded,
    ResolvedSystem,
    SpanshError,
    LandableBody,
    MarketDiagnostics,
    canonical_planet_types_from_spansh,
    fetch_commodity_market,
    fetch_commodity_markets,
    fetch_landable_planet_subtypes,
    fetch_landable_bodies,
    resolve_system,
)
from elite_dangerous.market.spansh import _request_json

BASE_URL = "https://spansh.co.uk/api"


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, routes):
        self.routes = {key: list(value) for key, value in routes.items()}
        self.calls = []
        self.closed = False
        self.close_count = 0

    def request(self, method, url, *, timeout, **kwargs):
        path = url.removeprefix(BASE_URL)
        self.calls.append((method, path, timeout, kwargs))
        result = self.routes[(method, path)].pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True
        self.close_count += 1


class CancelAfterFirstRequestSession(FakeSession):
    def __init__(self, routes, context):
        super().__init__(routes)
        self.context = context

    def request(self, method, url, *, timeout, **kwargs):
        result = super().request(method, url, timeout=timeout, **kwargs)
        self.context.cancel()
        return result


def response(payload):
    return FakeResponse(payload)


def search_page(results, count):
    return response({"results": results, "count": count})


def search_result(name="Kappa", identifier=42):
    return {"name": name, "id64": identifier}


def station(name, market_id, **fields):
    return {"name": name, "market_id": market_id, **fields}


def station_detail(name, *, market=None, **fields):
    result = {
        "name": name,
        "market_id": 123,
        "system_name": "Kappa",
        "is_planetary": False,
        "has_market": True,
        "market": [] if market is None else market,
        "updated_at": None,
        "market_updated_at": None,
        **fields,
    }
    return {"record": result}


def dump_station(name, station_id=123, *, commodities=None, **fields):
    return {
        "name": name,
        "id": station_id,
        "landingPads": {"large": 1, "medium": 2, "small": 3},
        "updateTime": "2026-09-16T12:30:00Z",
        "market": {
            "commodities": [] if commodities is None else commodities,
            "updateTime": "2026-09-16T12:30:00Z",
        },
        **fields,
    }


def setup_session(
    *,
    system_record=None,
    pages=None,
    details=None,
    body_pages=None,
    dump_system=None,
):
    pages = pages if pages is not None else [search_page([search_result()], 1)]
    system_record = system_record if system_record is not None else {
        "name": "Kappa",
        "stations": [],
        "bodies": [],
    }
    routes = {
        ("POST", "/systems/search"): pages,
        ("GET", "/system/42"): [response({"record": system_record})],
    }
    detail_by_id = {}
    for market_id, detail in (details or {}).items():
        values = detail if isinstance(detail, list) else [detail]
        detail_by_id[str(market_id)] = values[0]
    dump_system = dump_system or _dump_system_from_discovery(system_record, detail_by_id)
    routes[("GET", "/dump/42")] = [response({"system": dump_system})]
    if body_pages is not None:
        routes[("POST", "/bodies/search")] = body_pages
    return FakeSession(routes)


def _dump_system_from_discovery(system_record, detail_by_id):
    """Build a dump-shaped fixture while retaining existing test scenarios."""
    def convert(node):
        converted = dict(node)
        converted["stations"] = []
        for discovered in node.get("stations", []):
            station_id = str(discovered.get("market_id"))
            detail = detail_by_id.get(station_id)
            if isinstance(detail, Exception):
                converted["stations"].append({
                    "name": discovered.get("name"),
                    "id": discovered.get("market_id"),
                    "market": {"commodities": "invalid", "updateTime": None},
                })
                continue
            if isinstance(detail, dict) and isinstance(detail.get("record"), dict):
                record = detail["record"]
                rows = []
                for row in record.get("market", []):
                    if isinstance(row, dict):
                        rows.append({
                            "name": row.get("commodity"),
                            "sellPrice": row.get("sell_price"),
                            "demand": row.get("demand"),
                            "supply": row.get("supply"),
                        })
                converted["stations"].append({
                    "name": record.get("name", discovered.get("name")),
                    "id": discovered.get("market_id"),
                    "landingPads": {
                        "large": 1 if record.get("has_large_pad") else 0,
                        "medium": record.get("medium_pads", 0),
                        "small": record.get("small_pads", 0),
                    },
                    "updateTime": record.get("updated_at"),
                    "market": {
                        "commodities": rows,
                        "updateTime": record.get("market_updated_at"),
                    },
                })
            else:
                converted["stations"].append({
                    "name": discovered.get("name"),
                    "id": discovered.get("market_id"),
                    "landingPads": {},
                    "market": {"commodities": [], "updateTime": None},
                })
        converted["bodies"] = [convert(body) for body in node.get("bodies", [])]
        return converted

    return convert(system_record)


class SpanshMarketTests(unittest.TestCase):
    def test_context_limits_each_request_timeout(self):
        session = FakeSession({("GET", "/system/42"): [FakeResponse({"record": {}})]})
        context = AcquisitionContext(deadline=96.0, clock=lambda: 90.0)

        _request_json(session, "GET", "/system/42", context=context)

        self.assertEqual(session.calls[0][2], 6.0)

    def test_remaining_uses_one_clock_read_for_deadline_decision(self):
        readings = iter((90.0, 96.0))
        context = AcquisitionContext(deadline=100.0, clock=lambda: next(readings))

        self.assertEqual(context.remaining(), 10.0)

    def test_context_prevents_request_after_deadline_or_cancellation(self):
        expired = FakeSession({})
        with self.assertRaises(AcquisitionDeadlineExceeded):
            _request_json(expired, "GET", "/system/42",
                          context=AcquisitionContext(deadline=10.0, clock=lambda: 10.0))
        self.assertEqual(expired.calls, [])

        cancelled = FakeSession({})
        context = AcquisitionContext(deadline=100.0, clock=lambda: 0.0)
        context.cancel()
        with self.assertRaises(AcquisitionCancelled):
            _request_json(cancelled, "GET", "/system/42", context=context)
        self.assertEqual(cancelled.calls, [])

    def test_system_pagination_stops_before_second_request_after_cancellation(self):
        context = AcquisitionContext(deadline=100.0, clock=lambda: 0.0)
        session = CancelAfterFirstRequestSession({
            ("POST", "/systems/search"): [
                search_page([search_result("Sol", 43)], 2),
                search_page([search_result()], 2),
            ],
        }, context)

        with self.assertRaises(AcquisitionCancelled):
            resolve_system("Kappa", session=session, context=context)
        self.assertEqual(len(session.calls), 1)

    def test_body_pagination_stops_before_second_request_after_cancellation(self):
        context = AcquisitionContext(deadline=100.0, clock=lambda: 0.0)
        session = CancelAfterFirstRequestSession({
            ("POST", "/bodies/search"): [
                response({"results": [{
                    "id64": 1, "system_id64": 42, "is_landable": True,
                    "type": "Planet", "subtype": "Rocky body", "name": "Kappa 2",
                }], "count": 2}),
            ],
        }, context)

        with self.assertRaises(AcquisitionCancelled):
            fetch_landable_bodies(ResolvedSystem("Kappa", 42), session=session, context=context)
        self.assertEqual(len(session.calls), 1)

    def test_deadline_between_pages_prevents_the_next_request(self):
        readings = iter((0.0, 0.0, 10.0))
        context = AcquisitionContext(deadline=10.0, clock=lambda: next(readings))
        session = FakeSession({
            ("POST", "/systems/search"): [
                search_page([search_result("Sol", 43)], 2),
                search_page([search_result()], 2),
            ],
        })

        with self.assertRaises(AcquisitionDeadlineExceeded):
            resolve_system("Kappa", session=session, context=context)
        self.assertEqual(len(session.calls), 1)
    def test_dump_market_mapping_avoids_station_requests(self):
        session = setup_session(
            system_record={"name": "Kappa", "stations": [], "bodies": []}
        )
        session.routes[("GET", "/dump/42")] = [response({
            "system": {
                "name": "Kappa",
                "stations": [dump_station("Market", commodities=[{
                    "name": "Platinum",
                    "sellPrice": 725,
                    "demand": 30,
                    "supply": 40,
                }])],
                "bodies": [],
            }
        })]

        result = fetch_commodity_market("Kappa", "Platinum", session=session)

        observation = result.observations[0]
        self.assertEqual(observation.station.name, "Market")
        self.assertEqual(observation.station.market_id, "123")
        self.assertEqual(observation.station.max_landing_pad, "L")
        self.assertIsNone(observation.station.is_planetary)
        self.assertEqual(observation.sell_price, 725)
        self.assertEqual(observation.demand, 30)
        self.assertEqual(observation.supply, 40)
        self.assertEqual(
            observation.market_updated_at,
            datetime(2026, 9, 16, 12, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            [call[1] for call in session.calls if call[0] == "GET"],
            ["/system/42", "/dump/42"],
        )

    def test_resolve_system_returns_reusable_exact_identity(self):
        session = setup_session(pages=[search_page([search_result("KAPPA")], 1)])

        system = resolve_system("Kappa", session=session)

        self.assertEqual(system, ResolvedSystem("KAPPA", 42))

    def test_confirmed_spansh_subtypes_map_to_canonical_types(self):
        subtypes = (
            "High metal content world",
            "Metal-rich body",
            "Rocky body",
            "Rocky Ice world",
            "Icy body",
            "Unknown world",
            "Rocky body",
        )

        self.assertEqual(
            canonical_planet_types_from_spansh(subtypes),
            ("High metal content", "Metal Rich", "Rocky", "Rocky Ice", "Icy"),
        )

    def test_body_search_keeps_only_explicitly_landable_planets(self):
        rows = [
            {
                "id64": 1,
                "system_id64": 42,
                "name": "Rock",
                "type": "Planet",
                "subtype": "Rocky body",
                "is_landable": True,
            },
            {
                "id64": 2,
                "system_id64": 42,
                "name": "Duplicate",
                "type": "Planet",
                "subtype": "Rocky body",
                "is_landable": True,
            },
            {
                "id64": 3,
                "system_id64": 42,
                "name": "Not landable",
                "type": "Planet",
                "subtype": "Icy body",
                "is_landable": False,
            },
            {
                "id64": 4,
                "system_id64": 42,
                "name": "Missing landability",
                "type": "Planet",
                "subtype": "Rocky Ice world",
            },
            {
                "id64": 5,
                "system_id64": 42,
                "name": "Not a planet",
                "type": "Star",
                "subtype": "High metal content world",
                "is_landable": True,
            },
            {
                "id64": 6,
                "system_id64": 42,
                "name": "Unknown",
                "type": "Planet",
                "subtype": "Unsupported world",
                "is_landable": True,
            },
        ]
        session = setup_session(body_pages=[response({"results": rows, "count": 6})])

        subtypes = fetch_landable_planet_subtypes(
            ResolvedSystem("Kappa", 42),
            session=session,
        )

        self.assertEqual(subtypes, ("Rocky body", "Unsupported world"))
        request = session.calls[0]
        self.assertEqual(request[:3], ("POST", "/bodies/search", 25))
        self.assertEqual(
            request[3]["json"]["filters"],
            {
                "system_id64": {"value": "42"},
                "is_landable": {"value": True},
                "type": {"value": ["Planet"]},
            },
        )

    def test_body_search_empty_result_is_successful(self):
        session = setup_session(body_pages=[response({"results": [], "count": 0})])

        self.assertEqual(
            fetch_landable_planet_subtypes(
                ResolvedSystem("Kappa", 42),
                session=session,
            ),
            (),
        )

    def test_body_search_retains_eligible_body_identity_and_skips_unknown_types(self):
        rows = [
            {"id64": 1, "system_id64": 42, "name": "Kappa 1", "type": "Planet", "subtype": "Rocky body", "is_landable": True},
            {"id64": 2, "system_id64": 42, "name": "Kappa 4", "type": "Planet", "subtype": "Rocky body", "is_landable": True},
            {"id64": 3, "system_id64": 42, "name": "Kappa 5", "type": "Planet", "subtype": "Unknown body", "is_landable": True},
        ]
        session = setup_session(body_pages=[response({"results": rows, "count": 3})])

        self.assertEqual(
            fetch_landable_bodies(ResolvedSystem("Kappa", 42), session=session),
            (
                LandableBody("Kappa 1", "Rocky"),
                LandableBody("Kappa 4", "Rocky"),
            ),
        )

    def test_resolved_system_avoids_repeating_system_search(self):
        system = {"name": "Kappa", "stations": [], "bodies": []}
        session = setup_session(system_record=system)

        fetch_commodity_markets(
            "Kappa",
            ("Platinum",),
            session=session,
            resolved_system=ResolvedSystem("Kappa", 42),
        )

        self.assertNotIn("/systems/search", [call[1] for call in session.calls])
        self.assertIn("/system/42", [call[1] for call in session.calls])

    def test_exact_case_insensitive_system_match_and_request_shape(self):
        session = setup_session(pages=[search_page([search_result("KAPPA")], 1)])
        result = fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertEqual(result.requested_commodity, "Platinum")
        method, path, timeout, kwargs = session.calls[0]
        self.assertEqual((method, path, timeout), ("POST", "/systems/search", 25))
        self.assertEqual(kwargs["json"], {
            "filters": {"name": {"value": "Kappa"}}, "size": 100, "page": 0,
        })

    def test_exact_system_match_on_later_page(self):
        session = setup_session(pages=[
            search_page([search_result("Kappa Reticuli", 41)], 2),
            search_page([search_result("Kappa", 42)], 2),
        ])
        fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertEqual([call[3]["json"]["page"] for call in session.calls[:2]], [0, 1])

    def test_search_without_count_continues_full_pages_until_empty(self):
        full_page = [search_result(f"System {index}", index) for index in range(100)]
        session = setup_session(pages=[
            response({"results": full_page}),
            response({"results": []}),
        ])
        with self.assertRaises(SpanshError):
            fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertEqual([call[3]["json"]["page"] for call in session.calls], [0, 1])

    def test_search_exhausted_without_exact_match_is_fatal(self):
        session = setup_session(pages=[search_page([search_result("Kappa Reticuli")], 1)])
        with self.assertRaises(SpanshError):
            fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertEqual(len(session.calls), 1)

    def test_empty_page_before_reported_count_is_fatal_instead_of_not_found(self):
        session = setup_session(pages=[
            search_page([search_result("Kappa Reticuli", 41)], 2),
            search_page([], 2),
        ])
        with self.assertRaisesRegex(SpanshError, "ended before its reported result count"):
            fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertEqual([call[3]["json"]["page"] for call in session.calls], [0, 1])

    def test_malformed_search_payload_is_fatal(self):
        session = setup_session(pages=[response({"results": "not a list", "count": 1})])
        with self.assertRaises(SpanshError):
            fetch_commodity_market("Kappa", "Platinum", session=session)

    def test_fatal_system_search_http_error_preserves_cause(self):
        failure = requests.ConnectionError("offline")
        session = setup_session(pages=[failure])
        with self.assertRaises(SpanshError) as raised:
            fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertIs(raised.exception.__cause__, failure)

    def test_repeated_page_is_fatal_before_search_completion(self):
        repeated = search_page([search_result("Kappa Reticuli", 41)], 2)
        session = setup_session(pages=[repeated, repeated])
        with self.assertRaises(SpanshError):
            fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertEqual(len(session.calls), 2)

    def test_unusable_system_detail_and_name_mismatch_are_fatal(self):
        for record in ({"name": "Other", "stations": [], "bodies": []}, []):
            with self.subTest(record=record):
                session = setup_session()
                session.routes[("GET", "/system/42")] = [response({"record": record})]
                with self.assertRaises(SpanshError):
                    fetch_commodity_market("Kappa", "Platinum", session=session)

    def test_discovery_recurses_and_last_duplicate_market_id_wins(self):
        system = {
            "name": "Kappa",
            "stations": [station("Old", 123, has_market=False)],
            "bodies": [{
                "stations": [station("Newest", "123", has_market=True)],
                "bodies": [{"stations": [station("Deep body", 124, has_market=True)]}],
            }],
        }
        session = setup_session(
            system_record=system,
            details={123: station_detail("Detail", market=[{
                "commodity": "Platinum", "sell_price": 5, "demand": 2, "supply": 1,
            }]), 124: station_detail("Deep body", market=[{"commodity": "Gold"}])},
        )
        result = fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].station.name, "Detail")
        paths = [call[1] for call in session.calls]
        self.assertEqual(paths.count("/dump/42"), 1)
        self.assertFalse(any(path.startswith("/station/") for path in paths))

    def test_system_and_planetary_candidates_by_market_flag_and_service(self):
        system = {
            "name": "Kappa",
            "stations": [station("Flag candidate", 123, has_market=True)],
            "bodies": [{"stations": [station("Service candidate", 124, services=["Market"])]}],
        }
        details = {
            123: station_detail("Flag candidate", market=[{"commodity": "Platinum"}]),
            124: station_detail("Service candidate", market=[{"commodity": "Platinum"}]),
        }
        session = setup_session(system_record=system, details=details)
        result = fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertEqual(
            [item.station.name for item in result.observations],
            ["Flag candidate", "Service candidate"],
        )

    def test_discovery_missing_or_unusable_market_id_is_an_issue_for_candidate(self):
        system = {
            "name": "Kappa",
            "stations": [
                station("No ID", None, has_market=True),
                station("Bad ID", "market-x", services=["Market"]),
            ],
            "bodies": [],
        }
        result = fetch_commodity_market(
            "Kappa", "Platinum", session=setup_session(system_record=system)
        )
        self.assertEqual([issue.station_name for issue in result.issues], ["No ID", "Bad ID"])
        self.assertTrue(all("market_id" in issue.message for issue in result.issues))

    def test_detail_without_market_capability_is_skipped(self):
        system = {
            "name": "Kappa",
            "stations": [station("Gone", 123, has_market=True)],
            "bodies": [],
        }
        dump = {"name": "Kappa", "stations": [dump_station("Gone")], "bodies": []}
        result = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
            system_record=system, dump_system=dump
        ))
        self.assertEqual(result.observations, ())
        self.assertEqual(result.issues, ())

    def test_unusable_station_detail_becomes_recoverable_issue(self):
        system = {
            "name": "Kappa",
            "stations": [station("Malformed", 123, has_market=True)],
            "bodies": [],
        }
        dump = {"name": "Kappa", "stations": [{
            "name": "Malformed", "id": 123, "market": "invalid"
        }], "bodies": []}
        result = fetch_commodity_market(
            "Kappa",
            "Platinum",
            session=setup_session(system_record=system, dump_system=dump),
        )
        self.assertEqual(result.observations, ())
        self.assertEqual(result.issues[0].station_name, "Malformed")

    def test_dump_system_mismatch_is_fatal(self):
        system = {"name": "Kappa", "stations": [
            station("Wrong system", 123, has_market=True),
            station("Good", 124, has_market=True),
        ], "bodies": []}
        with self.assertRaises(SpanshError):
            fetch_commodity_market("Kappa", "Platinum", session=setup_session(
                system_record=system,
                dump_system={"name": "Other", "stations": [], "bodies": []},
            ))

    def test_station_http_failure_is_recoverable_and_preserves_observation(self):
        system = {"name": "Kappa", "stations": [
            station("Unavailable", 123, has_market=True),
            station("Available", 124, has_market=True),
        ], "bodies": []}
        details = {
            123: requests.ConnectionError("offline"),
            124: station_detail("Available", market=[{"commodity": "Platinum", "sell_price": 4}]),
        }
        result = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
            system_record=system, details=details
        ))
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.issues[0].station_name, "Unavailable")
        self.assertFalse(result.is_complete)

    def test_matching_canonical_and_demonstrated_alias_use_canonical_name(self):
        products = (
            ("Bastnäsite", "Bastnasite"),
            ("Methanol Monohydrate Crystals", "Methanol Crystals"),
            ("Platinum", "PLATINUM"),
        )
        for requested, returned in products:
            with self.subTest(requested=requested, returned=returned):
                system = {
                    "name": "Kappa",
                    "stations": [station("Market", 123, has_market=True)],
                    "bodies": [],
                }
                detail = station_detail("Market", market=[{"commodity": returned, "sell_price": 9}])
                result = fetch_commodity_market("Kappa", requested, session=setup_session(
                    system_record=system, details={123: detail}
                ))
                expected = {
                    "Bastnäsite": "Bastnäsite",
                    "Methanol Monohydrate Crystals": "Methanol Crystals",
                    "Platinum": "Platinum",
                }[requested]
                self.assertEqual(result.requested_commodity, expected)
                self.assertEqual(result.observations[0].commodity, result.requested_commodity)

    def test_unknown_product_uses_normalized_matching_without_new_catalogue_entries(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail("Market", market=[{"commodity": "Test Commodity", "sell_price": 3}])
        result = fetch_commodity_market("Kappa", "test-commodity", session=setup_session(
            system_record=system, details={123: detail}
        ))
        self.assertEqual(result.observations[0].commodity, "Test Commodity")
        self.assertEqual(result.requested_commodity, "test-commodity")

    def test_empty_or_nonmatching_market_is_not_an_issue(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        for market in ([], [{"commodity": "Gold"}]):
            with self.subTest(market=market):
                result = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
                    system_record=system, details={123: station_detail("Market", market=market)}
                ))
                self.assertEqual(result.observations, ())
                self.assertEqual(result.issues, ())

    def test_missing_and_nonlist_market_payload_are_issues(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        for market, include_market in ((None, False), ("invalid", True)):
            dump_station_record = dump_station("Market")
            if include_market:
                dump_station_record["market"] = market
            else:
                del dump_station_record["market"]
            with self.subTest(market=market):
                result = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
                    system_record=system,
                    dump_system={"name": "Kappa", "stations": [dump_station_record], "bodies": []},
                ))
                self.assertEqual(result.observations, ())
                self.assertEqual(len(result.issues), 1)

    def test_malformed_relevant_market_row_adds_issue_without_losing_valid_rows(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail("Market", market=[
            {"commodity": "Platinum", "sell_price": 5, "demand": 1},
            {"commodity": "Platinum", "sell_price": "not-a-price"},
        ])
        result = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
            system_record=system, details={123: detail}
        ))
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(len(result.issues), 1)
        self.assertFalse(result.is_complete)

    def test_malformed_unrelated_market_row_does_not_hide_requested_commodity(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail("Market", market=[
            {"commodity": "Gold", "sell_price": "not-a-price"},
            {"commodity": "Platinum", "sell_price": 725, "demand": 3},
        ])
        result = fetch_commodity_market(
            "Kappa",
            "Platinum",
            session=setup_session(system_record=system, details={123: detail}),
        )
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].sell_price, 725)
        self.assertEqual(result.issues, ())

    def test_none_market_facts_are_preserved(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail("Market", market=[{
            "commodity": "Platinum", "sell_price": None, "demand": None, "supply": None,
        }])
        observation = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
            system_record=system, details={123: detail}
        )).observations[0]
        self.assertIsNone(observation.sell_price)
        self.assertIsNone(observation.demand)
        self.assertIsNone(observation.supply)

    def test_pad_mapping_and_timestamps(self):
        system = {"name": "Kappa", "stations": [
            station(str(index), 123 + index, has_market=True) for index in range(4)
        ], "bodies": []}
        pads = (
            {"has_large_pad": True},
            {"medium_pads": 1},
            {"small_pads": 1},
            {},
        )
        details = {
            123 + index: station_detail(
                str(index), market=[{"commodity": "Platinum"}], **pad_fields,
                market_updated_at="2026-09-16T12:30:00Z",
                updated_at="2026-09-16T12:30:00",
            )
            for index, pad_fields in enumerate(pads)
        }
        result = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
            system_record=system, details=details
        ))
        self.assertEqual(
            [item.station.max_landing_pad for item in result.observations],
            ["L", "M", "S", None],
        )
        self.assertEqual(
            [item.station.market_id for item in result.observations],
            ["123", "124", "125", "126"],
        )
        for item in result.observations:
            expected = datetime(2026, 9, 16, 12, 30, tzinfo=timezone.utc)
            self.assertEqual(item.market_updated_at, expected)
            self.assertEqual(item.station_updated_at, expected)

    def test_invalid_or_missing_timestamps_map_to_none(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail(
            "Market",
            market=[{"commodity": "Platinum"}],
            market_updated_at="bad",
        )
        del detail["record"]["updated_at"]
        observation = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
            system_record=system, details={123: detail}
        )).observations[0]
        self.assertIsNone(observation.market_updated_at)
        self.assertIsNone(observation.station_updated_at)

    def test_carriers_low_demand_and_zero_or_unknown_prices_are_not_filtered_or_ranked(self):
        names = ("ABC-123", "FC01", "Ordinary")
        system = {"name": "Kappa", "stations": [
            station(name, 123 + index, has_market=True) for index, name in enumerate(names)
        ], "bodies": []}
        prices = (0, None, 999)
        details = {
            123 + index: station_detail(name, market=[{
                "commodity": "Platinum", "sell_price": prices[index], "demand": 0,
            }])
            for index, name in enumerate(names)
        }
        result = fetch_commodity_market("Kappa", "Platinum", session=setup_session(
            system_record=system, details=details
        ))
        self.assertEqual([item.station.name for item in result.observations], list(names))
        self.assertEqual([item.sell_price for item in result.observations], list(prices))
        self.assertTrue(all(item.demand == 0 for item in result.observations))

    def test_injected_session_is_reused_and_not_closed(self):
        session = setup_session()
        fetch_commodity_market("Kappa", "Platinum", session=session)
        self.assertFalse(session.closed)
        self.assertEqual(session.calls[0][0:3], ("POST", "/systems/search", 25))

    def test_owned_session_closes_after_success_and_failure(self):
        for pages, succeeds in (
            ([search_page([search_result()], 1)], True),
            ([response({"results": []})], False),
        ):
            session = setup_session(pages=pages)
            with patch("elite_dangerous.market.spansh.requests.Session", return_value=session):
                if succeeds:
                    fetch_commodity_market("Kappa", "Platinum")
                else:
                    with self.assertRaises(SpanshError):
                        fetch_commodity_market("Kappa", "Platinum")
            self.assertTrue(session.closed)

    def test_batch_fetches_multiple_commodities_with_one_traversal(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail("Market", market=[
            {"commodity": "Platinum", "sell_price": 10, "demand": 20},
            {"commodity": "Gold", "sell_price": 30, "demand": 40},
        ])
        session = setup_session(system_record=system, details={123: detail})

        results = fetch_commodity_markets(
            "Kappa",
            (name for name in ("Gold", "Platinum")),
            session=session,
        )

        self.assertEqual(
            tuple(result.requested_commodity for result in results),
            ("Gold", "Platinum"),
        )
        self.assertEqual(
            tuple(result.observations[0].sell_price for result in results),
            (30, 10),
        )
        paths = [call[1] for call in session.calls]
        self.assertEqual(paths.count("/systems/search"), 1)
        self.assertEqual(paths.count("/system/42"), 1)
        self.assertEqual(paths.count("/dump/42"), 1)
        self.assertFalse(any(path.startswith("/station/") for path in paths))

    def test_batch_deduplicates_aliases_and_exact_requests_in_first_order(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail("Market", market=[
            {"commodity": "Bastnasite", "sell_price": 1},
            {"commodity": "Gold", "sell_price": 2},
            {"commodity": "Methanol Monohydrate Crystals", "sell_price": 3},
            {"commodity": "Platinum", "sell_price": 4},
        ])
        results = fetch_commodity_markets(
            "Kappa",
            (name for name in (
                "Gold",
                "Bastnasite",
                "Bastnäsite",
                "Methanol Monohydrate Crystals",
                "Methanol Crystals",
                "Platinum",
                "Gold",
            )),
            session=setup_session(system_record=system, details={123: detail}),
        )

        self.assertEqual(
            tuple(result.requested_commodity for result in results),
            ("Gold", "Bastnäsite", "Methanol Crystals", "Platinum"),
        )
        self.assertEqual(results[1].observations[0].commodity, "Bastnäsite")
        self.assertEqual(results[2].observations[0].commodity, "Methanol Crystals")

    def test_batch_supports_unknown_normalized_names_and_distinct_empty_keys(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail("Market", market=[
            {"commodity": "New-Community Product", "sell_price": 1},
            {"commodity": "???", "sell_price": 2},
            {"commodity": "!!!", "sell_price": 3},
        ])
        results = fetch_commodity_markets(
            "Kappa",
            ("new community product", "???", "!!!"),
            session=setup_session(system_record=system, details={123: detail}),
        )

        self.assertEqual(len(results), 3)
        self.assertEqual(
            tuple(result.observations[0].sell_price for result in results),
            (1, 2, 3),
        )
        self.assertEqual(results[0].observations[0].commodity, "New-Community Product")

    def test_empty_batch_does_not_create_or_use_a_session(self):
        supplied_session = setup_session()
        with patch("elite_dangerous.market.spansh.requests.Session") as make_session:
            self.assertEqual(fetch_commodity_markets("Kappa", ()), ())
            self.assertEqual(make_session.call_count, 0)

        self.assertEqual(
            fetch_commodity_markets("Kappa", (), session=supplied_session),
            (),
        )
        self.assertEqual(supplied_session.calls, [])
        self.assertFalse(supplied_session.closed)

    def test_absent_requested_commodity_has_no_synthetic_issue(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        result = fetch_commodity_markets(
            "Kappa",
            ("Platinum", "Gold"),
            session=setup_session(
                system_record=system,
                details={123: station_detail("Market", market=[{"commodity": "Platinum"}])},
            ),
        )[1]

        self.assertEqual(result.observations, ())
        self.assertEqual(result.issues, ())
        self.assertEqual(result.missing, ("Gold",))

    def test_malformed_requested_row_only_affects_its_commodity(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        results = fetch_commodity_markets(
            "Kappa",
            ("Platinum", "Gold"),
            session=setup_session(
                system_record=system,
                details={123: station_detail("Market", market=[
                    {"commodity": "Platinum", "sell_price": "bad"},
                    {"commodity": "Gold", "sell_price": 50},
                ])},
            ),
        )

        self.assertEqual(len(results[0].issues), 1)
        self.assertEqual(results[0].observations, ())
        self.assertEqual(results[1].issues, ())
        self.assertEqual(results[1].observations[0].sell_price, 50)

    def test_malformed_unrelated_row_is_ignored_and_later_products_survive(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        results = fetch_commodity_markets(
            "Kappa",
            ("Platinum", "Silver"),
            session=setup_session(
                system_record=system,
                details={123: station_detail("Market", market=[
                    {"commodity": "Gold", "sell_price": "bad"},
                    {"commodity": "Platinum", "sell_price": 75},
                    {"commodity": "Silver", "sell_price": 25},
                ])},
            ),
        )

        self.assertEqual(tuple(len(result.observations) for result in results), (1, 1))
        self.assertEqual(tuple(result.issues for result in results), ((), ()))

    def test_unidentifiable_malformed_row_is_shared_across_results(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        results = fetch_commodity_markets(
            "Kappa",
            ("Platinum", "Gold"),
            session=setup_session(
                system_record=system,
                details={123: station_detail("Market", market=[
                    {"sell_price": 12},
                    {"commodity": "Platinum", "sell_price": 75},
                ])},
            ),
        )

        self.assertEqual(results[0].issues, results[1].issues)
        self.assertEqual(len(results[0].issues), 1)
        self.assertEqual(len(results[0].observations), 1)

    def test_duplicate_valid_rows_remain_duplicate_observations(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        result = fetch_commodity_markets(
            "Kappa",
            ("Platinum",),
            session=setup_session(
                system_record=system,
                details={123: station_detail("Market", market=[
                    {"commodity": "Platinum", "sell_price": 5},
                    {"commodity": "Platinum", "sell_price": 8},
                ])},
            ),
        )[0]

        self.assertEqual(tuple(item.sell_price for item in result.observations), (5, 8))

    def test_station_failure_is_shared_and_other_station_products_survive(self):
        system = {
            "name": "Kappa",
            "stations": [
                station("Unavailable", 123, has_market=True),
                station("Available", 124, has_market=True),
            ],
            "bodies": [],
        }
        session = setup_session(
            system_record=system,
            details={
                123: requests.ConnectionError("offline"),
                124: station_detail("Available", market=[
                    {"commodity": "Platinum", "sell_price": 50},
                    {"commodity": "Gold", "sell_price": 25},
                ]),
            },
        )

        results = fetch_commodity_markets(
            "Kappa",
            ("Platinum", "Gold"),
            session=session,
        )

        self.assertEqual(results[0].issues, results[1].issues)
        self.assertEqual(results[0].issues[0].station_name, "Unavailable")
        self.assertEqual(results[0].observations[0].station.name, "Available")
        self.assertEqual(results[1].observations[0].station.name, "Available")
        paths = [call[1] for call in session.calls]
        self.assertEqual(paths.count("/dump/42"), 1)
        self.assertFalse(any(path.startswith("/station/") for path in paths))

    def test_batch_preserves_mapping_and_does_not_apply_policy_or_ranking(self):
        names = ("FC01", "ABC-123", "Ordinary")
        system = {
            "name": "Kappa",
            "stations": [
                station(name, 123 + index, has_market=True)
                for index, name in enumerate(names)
            ],
            "bodies": [],
        }
        prices = (0, 200, None)
        pads = (
            {"has_large_pad": True},
            {"medium_pads": 1},
            {"small_pads": 1},
        )
        details = {
            123 + index: station_detail(
                name,
                market=[{
                    "commodity": "Platinum",
                    "sell_price": prices[index],
                    "demand": 0,
                    "supply": index,
                }],
                market_updated_at="2026-09-16T12:30:00Z",
                updated_at="2026-09-16T12:30:00",
                **pads[index],
            )
            for index, name in enumerate(names)
        }
        result = fetch_commodity_markets(
            "Kappa",
            ("Platinum",),
            session=setup_session(system_record=system, details=details),
        )[0]

        self.assertEqual(tuple(item.station.name for item in result.observations), names)
        self.assertEqual(tuple(item.sell_price for item in result.observations), prices)
        self.assertEqual(tuple(item.demand for item in result.observations), (0, 0, 0))
        self.assertEqual(tuple(item.supply for item in result.observations), (0, 1, 2))
        self.assertEqual(
            tuple(item.station.max_landing_pad for item in result.observations),
            ("L", "M", "S"),
        )
        self.assertTrue(all(
            item.market_updated_at == datetime(2026, 9, 16, 12, 30, tzinfo=timezone.utc)
            for item in result.observations
        ))

    def test_excluded_fleet_carrier_skips_station_detail_and_issue(self):
        system = {
            "name": "Kappa",
            "stations": [station("ABC-123", 123, has_market=True)],
            "bodies": [],
        }
        session = setup_session(system_record=system)

        result = fetch_commodity_market(
            "Kappa",
            "Platinum",
            session=session,
            exclude_station=lambda name: name == "ABC-123",
        )

        self.assertEqual(result.observations, ())
        self.assertEqual(result.issues, ())
        self.assertNotIn(("GET", "/station/123"), [call[:2] for call in session.calls])

    def test_excluded_squadron_carrier_skips_station_detail_and_issue(self):
        system = {
            "name": "Kappa",
            "stations": [station("FC01", 123, has_market=True)],
            "bodies": [],
        }
        session = setup_session(system_record=system)

        result = fetch_commodity_market(
            "Kappa",
            "Platinum",
            session=session,
            exclude_station=lambda name: name == "FC01",
        )

        self.assertEqual(result.observations, ())
        self.assertEqual(result.issues, ())
        self.assertNotIn(("GET", "/station/123"), [call[:2] for call in session.calls])

    def test_excluded_carrier_is_skipped_before_any_dump_market_validation(self):
        market_variants = (
            {"commodities": [{"name": "Platinum", "sellPrice": 10}]},
            None,
            "invalid",
            {"commodities": []},
            {"commodities": "invalid"},
            {"commodities": [{"name": "Platinum", "sellPrice": "invalid"}]},
        )
        for index, market in enumerate(market_variants, start=123):
            with self.subTest(market=market):
                carrier = {
                    "name": "ABC-123",
                    "id": index,
                    "market": market,
                }
                diagnostics = MarketDiagnostics()
                session = setup_session(
                    system_record={"name": "Kappa", "stations": [], "bodies": []},
                    dump_system={"name": "Kappa", "stations": [carrier], "bodies": []},
                )

                result = fetch_commodity_market(
                    "Kappa",
                    "Platinum",
                    session=session,
                    exclude_station=lambda name: name == "ABC-123",
                    diagnostics=diagnostics,
                )

                self.assertEqual(result.observations, ())
                self.assertEqual(result.issues, ())
                self.assertEqual(diagnostics.carriers_excluded, 1)
                self.assertEqual(diagnostics.excluded_carrier_names, ["ABC-123"])

    def test_diagnostics_records_excluded_carrier_names_in_traversal_order(self):
        system = {
            "name": "Kappa",
            "stations": [
                station("ABC-123", 123, has_market=True),
                station("Market", 124, has_market=True),
                station("FC01", 125, has_market=True),
                station("XYZ-789", 126, has_market=True),
            ],
            "bodies": [],
        }
        details = {
            124: station_detail("Market", market=[{"commodity": "Platinum", "sell_price": 10}]),
        }
        session = setup_session(system_record=system, details=details)
        diagnostics = MarketDiagnostics()

        result = fetch_commodity_market(
            "Kappa",
            "Platinum",
            session=session,
            exclude_station=lambda name: name in {"ABC-123", "FC01", "XYZ-789"},
            diagnostics=diagnostics,
        )

        self.assertEqual(diagnostics.carriers_excluded, 3)
        self.assertEqual(diagnostics.excluded_carrier_names, ["ABC-123", "FC01", "XYZ-789"])
        self.assertNotIn(("GET", "/station/123"), [call[:2] for call in session.calls])
        self.assertNotIn(("GET", "/station/125"), [call[:2] for call in session.calls])
        self.assertNotIn(("GET", "/station/126"), [call[:2] for call in session.calls])
        self.assertIn(("GET", "/dump/42"), [call[:2] for call in session.calls])
        self.assertFalse(any(call[1].startswith("/station/") for call in session.calls))
        self.assertEqual(len(result.observations), 1)

    def test_diagnostics_omitted_preserves_existing_carrier_behavior(self):
        system = {"name": "Kappa", "stations": [station("ABC-123", 123, has_market=True)], "bodies": []}
        session = setup_session(system_record=system)

        result = fetch_commodity_market(
            "Kappa", "Platinum", session=session, exclude_station=lambda name: name == "ABC-123"
        )

        self.assertEqual(result.observations, ())
        self.assertEqual(result.issues, ())
        self.assertNotIn(("GET", "/station/123"), [call[:2] for call in session.calls])

    def test_exclusion_is_optional_and_ordinary_station_still_maps(self):
        system = {
            "name": "Kappa",
            "stations": [station("Market", 123, has_market=True)],
            "bodies": [],
        }
        detail = station_detail("Market", market=[{"commodity": "Platinum", "sell_price": 10}])
        session = setup_session(system_record=system, details={123: detail})

        result = fetch_commodity_market(
            "Kappa",
            "Platinum",
            session=session,
            exclude_station=lambda name: name in {"ABC-123", "FC01"},
        )

        self.assertEqual(result.observations[0].station.name, "Market")
        self.assertIn(("GET", "/dump/42"), [call[:2] for call in session.calls])
        self.assertFalse(any(call[1].startswith("/station/") for call in session.calls))

    def test_batch_fatal_system_failure_remains_spansh_error(self):
        session = setup_session(pages=[response({"results": "invalid"})])
        with self.assertRaises(SpanshError):
            fetch_commodity_markets("Kappa", ("Platinum", "Gold"), session=session)

    def test_batch_session_ownership_matches_singular_api(self):
        supplied = setup_session()
        fetch_commodity_markets("Kappa", ("Platinum", "Gold"), session=supplied)
        self.assertFalse(supplied.closed)

        owned = setup_session()
        with patch("elite_dangerous.market.spansh.requests.Session", return_value=owned):
            fetch_commodity_markets("Kappa", ("Platinum", "Gold"))
        self.assertTrue(owned.closed)
        self.assertEqual(owned.close_count, 1)


if __name__ == "__main__":
    unittest.main()
