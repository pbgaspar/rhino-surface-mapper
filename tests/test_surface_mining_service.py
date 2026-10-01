import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from elite_dangerous.market import (
    AcquisitionContext,
    CommodityMarketResult,
    AcquisitionCancelled,
    AcquisitionDeadlineExceeded,
    LandableBody,
    MarketObservation,
    ResolvedSystem,
    SpanshError,
    SpanshSystemNotFoundError,
    Station,
)
from surface_mining_service import (
    SurfaceMiningService,
    SurfaceMiningSnapshot,
    SystemNotFoundError,
)


NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def observation(name, *, commodity="Platinum", price=500, demand=1000, age=timedelta(days=1), market_id=None):
    return MarketObservation(
        Station(name, market_id or name, "Kappa", True, "L"), commodity, price, demand,
        None, NOW - age if age is not None else None, None,
    )


def snapshot(name="Kappa", market_results=()):
    return SurfaceMiningSnapshot(
        name, 42, (LandableBody("Kappa 2", "Rocky"),), ("Platinum",),
        tuple(market_results), NOW,
    )


class SurfaceMiningServiceTests(unittest.TestCase):
    def test_reuses_snapshot_until_ttl_and_refresh_bypasses_it(self):
        acquire = Mock(side_effect=[snapshot(), snapshot(), snapshot()])
        service = SurfaceMiningService(acquire=acquire)
        first = service.snapshot_for(" Kappa ", now=NOW)
        self.assertIs(service.snapshot_for("Kappa", now=NOW + timedelta(minutes=29)), first)
        self.assertIsNot(service.snapshot_for("Kappa", now=NOW + timedelta(minutes=30)), first)
        service.snapshot_for("Kappa", now=NOW + timedelta(minutes=31), force=True)
        self.assertEqual(acquire.call_count, 3)

    def test_multiple_systems_are_retained(self):
        acquire = Mock(side_effect=[snapshot("Kappa"), snapshot("Sol")])
        service = SurfaceMiningService(acquire=acquire)
        service.snapshot_for("Kappa", now=NOW)
        service.snapshot_for("Sol", now=NOW)
        service.snapshot_for("Kappa", now=NOW + timedelta(minutes=1))
        self.assertEqual(acquire.call_count, 2)

    def test_filter_changes_recalculate_without_acquisition(self):
        results = (CommodityMarketResult("Platinum", (observation("Market", demand=101),), ()),)
        acquire = Mock(return_value=snapshot(market_results=results))
        service = SurfaceMiningService(acquire=acquire)
        raw = service.snapshot_for("Kappa", now=NOW)
        self.assertEqual(len(service.analyze(raw, minimum_demand=100).products), 1)
        self.assertEqual(len(service.analyze(raw, minimum_demand=101).products), 0)
        self.assertEqual(acquire.call_count, 1)

    def test_invalid_parameter_ranges_are_rejected(self):
        service = SurfaceMiningService(acquire=Mock(return_value=snapshot()))
        raw = service.snapshot_for("Kappa", now=NOW)
        with self.assertRaises(ValueError):
            service.analyze(raw, top_products=2)
        with self.assertRaises(ValueError):
            service.analyze(raw, top_markets=6)

    def test_valid_boundaries_are_accepted(self):
        service = SurfaceMiningService(acquire=Mock(return_value=snapshot()))
        raw = service.snapshot_for("Kappa", now=NOW)
        service.analyze(raw, top_products=3, top_markets=3)
        service.analyze(raw, top_products=10, top_markets=5)

    def test_top_markets_are_selected_per_product_and_up_to_limit(self):
        results = tuple(
            CommodityMarketResult(
                commodity,
                tuple(observation(f"{commodity} {index}", commodity=commodity, price=500 + index)
                      for index in range(2)),
                (),
            )
            for commodity in ("Platinum", "Gold")
        )
        service = SurfaceMiningService(acquire=Mock(return_value=snapshot(market_results=results)))
        analysis = service.analyze(service.snapshot_for("Kappa", now=NOW), top_products=10, top_markets=5)
        self.assertEqual([len(product.markets) for product in analysis.products], [2, 2])
        self.assertEqual(analysis.eligible_market_count, 4)
        self.assertEqual(
            service.analyze(service.snapshot_for("Kappa", now=NOW), top_products=3, top_markets=3).eligible_market_count,
            4,
        )

    def test_eligible_market_count_deduplicates_physical_markets_and_tracks_demand(self):
        results = (
            CommodityMarketResult(
                "Platinum",
                (observation("Shared", commodity="Platinum", market_id="shared"),
                 observation("Independent", commodity="Platinum", market_id="independent", demand=50)),
                (),
            ),
            CommodityMarketResult(
                "Gold",
                (observation("Shared", commodity="Gold", market_id="shared"),),
                (),
            ),
        )
        service = SurfaceMiningService(acquire=Mock(return_value=snapshot(market_results=results)))
        raw = service.snapshot_for("Kappa", now=NOW)
        self.assertEqual(service.analyze(raw, minimum_demand=100).eligible_market_count, 1)
        self.assertEqual(service.analyze(raw, minimum_demand=40).eligible_market_count, 2)
        self.assertEqual(service.analyze(raw, minimum_demand=100).minimum_demand, 100)

    def test_top_products_use_global_existing_ranking_not_product_maxima(self):
        results = (
            CommodityMarketResult("Platinum", (observation("Platinum high", commodity="Platinum", price=1000, demand=150),), ()),
            CommodityMarketResult("Gold", (observation("Gold high", commodity="Gold", price=1000, demand=200),), ()),
            CommodityMarketResult("Silver", (observation("Silver high", commodity="Silver", price=900, demand=101),), ()),
            CommodityMarketResult("Palladium", (observation("Palladium high", commodity="Palladium", price=800, demand=101),), ()),
        )
        service = SurfaceMiningService(acquire=Mock(return_value=snapshot(market_results=results)))
        analysis = service.analyze(service.snapshot_for("Kappa", now=NOW), top_products=3)
        self.assertEqual(tuple(product.commodity for product in analysis.products), ("Gold", "Platinum", "Silver"))

    def test_carriers_and_non_current_markets_are_not_commercial_results(self):
        results = (
            CommodityMarketResult("Platinum", (
                observation("ABC-123"),
                observation("Old", age=timedelta(days=366)),
                observation("Unknown", age=None),
            ), ()),
        )
        service = SurfaceMiningService(acquire=Mock(return_value=snapshot(market_results=results)))
        analysis = service.analyze(service.snapshot_for("Kappa", now=NOW))
        self.assertEqual(analysis.products, ())
        self.assertEqual({issue.station_name for issue in analysis.issues}, {"Old", "Unknown"})

    def test_duplicate_station_issues_are_deduplicated(self):
        results = tuple(
            CommodityMarketResult(
                commodity,
                (observation("Old", commodity=commodity, age=timedelta(days=366), market_id="1"),),
                (),
            )
            for commodity in ("Platinum", "Gold")
        )
        service = SurfaceMiningService(acquire=Mock(return_value=snapshot(market_results=results)))
        analysis = service.analyze(service.snapshot_for("Kappa", now=NOW))
        self.assertEqual(tuple(issue.station_name for issue in analysis.issues), ("Old",))

    def test_system_not_found_is_distinct(self):
        acquire = Mock(side_effect=SystemNotFoundError("System not found."))
        service = SurfaceMiningService(acquire=acquire)
        with self.assertRaises(SystemNotFoundError):
            service.snapshot_for("Missing", now=NOW)

    def test_real_resolution_error_types_are_classified(self):
        with patch("surface_mining_service.resolve_system", side_effect=SpanshSystemNotFoundError("missing")):
            with self.assertRaises(SystemNotFoundError):
                SurfaceMiningService().snapshot_for("Missing", now=NOW)
        with patch("surface_mining_service.resolve_system", side_effect=SpanshError("offline")):
            with self.assertRaises(Exception) as raised:
                SurfaceMiningService().snapshot_for("Kappa", now=NOW)
            self.assertEqual(type(raised.exception).__name__, "MarketAcquisitionError")

    def test_control_flow_exceptions_cross_the_service_boundary_unchanged(self):
        for exception in (AcquisitionCancelled("cancelled"), AcquisitionDeadlineExceeded("expired")):
            with self.subTest(exception=type(exception).__name__), \
                 patch("surface_mining_service.resolve_system", side_effect=exception):
                with self.assertRaises(type(exception)):
                    SurfaceMiningService().snapshot_for("Kappa", now=NOW)

    def test_cancellation_between_stages_does_not_start_next_stage(self):
        system = ResolvedSystem("Kappa", 42)
        fetch_markets = Mock()
        with patch("surface_mining_service.resolve_system", return_value=system), \
             patch("surface_mining_service.fetch_landable_bodies",
                   side_effect=AcquisitionCancelled("cancelled")), \
             patch("surface_mining_service.fetch_commodity_markets", fetch_markets):
            with self.assertRaises(AcquisitionCancelled):
                SurfaceMiningService().snapshot_for("Kappa", now=NOW)
        fetch_markets.assert_not_called()

    def test_default_acquisition_reuses_one_context_for_all_stages(self):
        contexts = []
        system = ResolvedSystem("Kappa", 42)

        def capture_context(*args, **kwargs):
            contexts.append(kwargs["context"])
            return system if len(contexts) == 1 else (LandableBody("Kappa 2", "Rocky"),)

        with patch("surface_mining_service.resolve_system", side_effect=capture_context), \
             patch("surface_mining_service.fetch_landable_bodies", side_effect=capture_context), \
             patch("surface_mining_service.fetch_commodity_markets", side_effect=capture_context):
            SurfaceMiningService().snapshot_for("Kappa", now=NOW)

        self.assertEqual(len(contexts), 3)
        self.assertIs(contexts[0], contexts[1])
        self.assertIs(contexts[1], contexts[2])

    def test_supplied_context_is_reused_by_default_acquisition(self):
        contexts = []
        system = ResolvedSystem("Kappa", 42)
        supplied = AcquisitionContext(deadline=100.0, clock=lambda: 0.0)

        def capture_context(*args, **kwargs):
            contexts.append(kwargs["context"])
            return system if len(contexts) == 1 else (LandableBody("Kappa 2", "Rocky"),)

        with patch("surface_mining_service.resolve_system", side_effect=capture_context), \
             patch("surface_mining_service.fetch_landable_bodies", side_effect=capture_context), \
             patch("surface_mining_service.fetch_commodity_markets", side_effect=capture_context):
            SurfaceMiningService().snapshot_for("Kappa", now=NOW, context=supplied)

        self.assertEqual(len(contexts), 3)
        self.assertTrue(all(context is supplied for context in contexts))

    def test_known_system_name_index_reuses_without_reacquisition(self):
        acquire = Mock(return_value=snapshot("Kappa"))
        service = SurfaceMiningService(acquire=acquire)
        service.snapshot_for("Kappa", now=NOW)
        service.snapshot_for(" kApPa ", now=NOW + timedelta(minutes=1))
        self.assertEqual(acquire.call_count, 1)

    def test_acquisition_callback_only_runs_when_snapshot_must_be_acquired(self):
        acquire = Mock(side_effect=[snapshot(), snapshot()])
        service = SurfaceMiningService(acquire=acquire)
        on_acquisition = Mock()

        service.snapshot_for("Kappa", now=NOW, on_acquisition=on_acquisition)
        service.snapshot_for(
            "Kappa", now=NOW + timedelta(minutes=1),
            on_acquisition=on_acquisition,
        )
        self.assertEqual(on_acquisition.call_count, 1)

        service.snapshot_for(
            "Kappa", now=NOW + timedelta(minutes=2), force=True,
            on_acquisition=on_acquisition,
        )
        self.assertEqual(on_acquisition.call_count, 2)


if __name__ == "__main__":
    unittest.main()
