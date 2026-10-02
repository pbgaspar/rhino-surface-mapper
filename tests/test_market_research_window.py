import importlib.util
import threading
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QTextFormat
from PySide6.QtWidgets import QSplitter, QSizePolicy, QStyleOptionViewItem, QTreeWidgetItem
from market_research_window import _IssueItemDelegate
from elite_dangerous.market import MarketIssue
from market_research_window import _Worker, MarketResearchWindow
from surface_mining_coordinator import SurfaceMiningCoordinator
from surface_mining_service import SystemNotFoundError


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 not installed")
class MarketResearchWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtTest import QTest
        cls.app = QApplication.instance() or QApplication([])
        cls.qtest = QTest
        cls._window_type = MarketResearchWindow
        cls._coordinators = []

        def make_window(*args, **kwargs):
            coordinator = SurfaceMiningCoordinator()
            cls._coordinators.append(coordinator)
            kwargs.setdefault("coordinator", coordinator)
            return cls._window_type(*args, **kwargs)

        make_window._format_market_age = cls._window_type._format_market_age

        globals()["MarketResearchWindow"] = make_window

    @classmethod
    def tearDownClass(cls):
        for coordinator in cls._coordinators:
            coordinator.shutdown()
        globals()["MarketResearchWindow"] = cls._window_type

    def _wait_for_completion(self, window):
        for _ in range(100):
            self.qtest.qWait(10)
            if window._spansh_generation is None:
                return
        self.fail("Market Research worker did not complete")

    def _window_with_snapshot_operation(self, operation):
        window = MarketResearchWindow(current_system="Kappa")
        def acquire(name, *, force, context, on_acquisition):
            on_acquisition()
            return operation(name, force=force, context=context)

        window.service.snapshot_for = acquire
        window.recalculate = Mock()
        return window

    def _wait_for(self, predicate, message):
        for _ in range(100):
            self.qtest.qWait(10)
            if predicate():
                return
        self.fail(message)

    def _assert_ready_status(self, window, system_name):
        status = window.status.text()
        self.assertIn("Ready —", status)
        self.assertIn(system_name.upper(), status)
        self.assertNotIn(system_name, status)
        self.assertIn("font-weight: 700", status)
        self.assertIn("font-size:", status)
        self.assertNotIn("font-weight", status.split("<span", 1)[0])

    def test_uses_injected_coordinator_and_does_not_shutdown_it_on_close(self):
        coordinator = SurfaceMiningCoordinator()
        window = self._window_type(coordinator=coordinator, current_system="Kappa")
        try:
            self.assertIs(window.coordinator, coordinator)
            self.assertIs(window.service, coordinator.service)
            window.close()
            self.assertFalse(coordinator.closing)
        finally:
            coordinator.shutdown()

    def test_initialize_uses_dynamic_system_provider_for_one_normal_search(self):
        coordinator = SurfaceMiningCoordinator()
        window = self._window_type(
            coordinator=coordinator,
            current_system_provider=lambda: " Lave ",
        )
        coordinator.request_snapshot = Mock(return_value=17)
        try:
            with patch.object(window, "update_inara"):
                window.initialize()
            self.assertEqual(window.system.text(), "Lave")
            coordinator.request_snapshot.assert_called_once_with("Lave", force=False)
        finally:
            window.close()
            coordinator.shutdown()

    def test_current_system_action_uses_latest_provider_without_forcing(self):
        coordinator = SurfaceMiningCoordinator()
        latest = ["Lave"]
        window = self._window_type(
            coordinator=coordinator,
            current_system_provider=lambda: latest[0],
            current_system="Kappa",
        )
        coordinator.request_snapshot = Mock(return_value=23)
        try:
            window.current_system_button.click()
            latest[0] = "Sol"
            window._spansh_generation = None
            window.current_system_button.click()
            self.assertEqual(window.system.text(), "Sol")
            self.assertEqual(
                coordinator.request_snapshot.call_args_list,
                [(("Lave",), {"force": False}), (("Sol",), {"force": False})],
            )
        finally:
            window.close()
            coordinator.shutdown()

    def test_current_system_button_label_position_and_control_tooltips(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            self.assertEqual(window.current_system_button.text(), "Current >")
            root = window.layout()
            system_row = root.itemAt(0).layout()
            system_widgets = (
                window.system_label,
                window.current_system_button,
                window.system,
                window.refresh_button,
            )
            self.assertEqual(window.system_label.text(), "System")
            positions = [system_row.indexOf(widget) for widget in system_widgets]
            self.assertTrue(all(position >= 0 for position in positions))
            self.assertEqual(positions, sorted(positions))
            self.assertEqual(system_row.stretch(system_row.indexOf(window.system)), 1)
            self.assertEqual(system_row.stretch(system_row.indexOf(window.current_system_button)), 0)
            self.assertEqual(system_row.stretch(system_row.indexOf(window.refresh_button)), 0)
            self.assertEqual(
                window.current_system_button.sizePolicy().horizontalPolicy(),
                QSizePolicy.Policy.Fixed,
            )
            self.assertEqual(
                window.refresh_button.sizePolicy().horizontalPolicy(),
                QSizePolicy.Policy.Fixed,
            )
            self.assertEqual(
                window.system.sizePolicy().horizontalPolicy(),
                QSizePolicy.Policy.Expanding,
            )

            parameter_row = root.itemAt(1).layout()
            parameter_widgets = (
                window.top_products_label,
                window.top_products,
                window.top_markets_label,
                window.top_markets,
                window.minimum_demand_label,
                window.minimum_demand,
            )
            parameter_positions = [parameter_row.indexOf(widget) for widget in parameter_widgets]
            self.assertTrue(all(position >= 0 for position in parameter_positions))
            self.assertEqual(parameter_positions, sorted(parameter_positions))
            self.assertIsNotNone(parameter_row.itemAt(parameter_row.count() - 1).spacerItem())
            for control in (
                window.top_products, window.top_markets, window.minimum_demand,
            ):
                self.assertEqual(
                    control.sizePolicy().horizontalPolicy(),
                    QSizePolicy.Policy.Fixed,
                )
            self.assertEqual(
                window.current_system_button.toolTip(),
                "Use the commander's current or last known system.",
            )
            self.assertEqual(
                window.refresh_button.toolTip(),
                "Download fresh market data for this system, ignoring the cached snapshot.",
            )
            self.assertEqual(
                window.top_products.toolTip(),
                "Number of best Surface Mining commodities to show.",
            )
            self.assertEqual(
                window.top_markets.toolTip(),
                "Maximum number of markets shown for each commodity.",
            )
            self.assertEqual(
                window.minimum_demand.toolTip(),
                "Ignore markets with demand below this value.",
            )
            self.assertEqual(
                window.inara_button.toolTip(),
                "Update the cached INARA Avg/Max reference prices.",
            )
        finally:
            window.close()

    def test_new_system_acquisition_clears_old_results_when_busy_starts(self):
        window = self._window_with_snapshot_operation(
            Mock(return_value=SimpleNamespace(system_name="Sol"))
        )
        try:
            window.results.setPlainText("Kappa results")
            window.system.setText("Sol")
            window.search()
            self._wait_for(
                lambda: window.status.text().startswith("Searching Sol"),
                "search never entered its acquisition state",
            )
            self.assertNotIn("Kappa results", window.results.toPlainText())
            self.assertIn("INARA Avg/Max:", window.results.toPlainText())
            self.assertTrue(window._indicator_timer.isActive())
            self._wait_for_completion(window)
            self._assert_ready_status(window, "Sol")
        finally:
            window.close()

    def test_cached_snapshot_reuse_does_not_clear_or_enter_busy_state(self):
        from surface_mining_service import SurfaceMiningService

        cached = SimpleNamespace(
            system_name="Kappa", system_id64=42,
            acquired_at=datetime.now(timezone.utc),
        )
        acquire = Mock(return_value=cached)
        service = SurfaceMiningService(acquire=acquire)
        service.snapshot_for("Kappa")
        coordinator = SurfaceMiningCoordinator(service=service)
        window = self._window_type(coordinator=coordinator, current_system="Kappa")
        service.analyze = Mock()
        window.recalculate = Mock()
        clear_results = Mock(wraps=window._clear_surface_mining_results)
        window._clear_surface_mining_results = clear_results
        set_busy = Mock(wraps=window._set_busy)
        window._set_busy = set_busy
        try:
            window.results.setPlainText("Current Kappa results")
            window.search()
            self._wait_for_completion(window)
            self.assertEqual(window.results.toPlainText(), "Current Kappa results")
            clear_results.assert_not_called()
            self.assertFalse(any(call.args[0] for call in set_busy.call_args_list))
            self.assertFalse(window._indicator_timer.isActive())
            self.assertEqual(acquire.call_count, 1)
        finally:
            window.close()
            coordinator.shutdown()

    def test_refresh_keeps_previous_results_visible_during_forced_acquisition(self):
        started = threading.Event()
        release = threading.Event()

        forced_values = []

        def acquire(_name, *, force, context):
            forced_values.append(force)
            started.set()
            release.wait(2)
            return SimpleNamespace(system_name="Kappa")

        window = self._window_with_snapshot_operation(Mock(side_effect=acquire))
        try:
            window.results.setPlainText("Previous Kappa results")
            window.search(force=True)
            self.assertTrue(started.wait(2), "forced acquisition did not enter acquire")
            self._wait_for(
                lambda: window.status.text().startswith("Searching Kappa"),
                "Refresh did not enter its acquisition state",
            )
            self.assertEqual(forced_values, [True])
            self.assertEqual(window.results.toPlainText(), "Previous Kappa results")
            self.assertTrue(window._indicator_timer.isActive())
            release.set()
            self._wait_for_completion(window)
        finally:
            release.set()
            window.close()

    def test_refresh_failure_preserves_previous_results(self):
        window = self._window_with_snapshot_operation(
            Mock(side_effect=SystemNotFoundError("System not found."))
        )
        try:
            window.results.setPlainText("Previous valid results")
            window.search(force=True)
            self._wait_for_completion(window)
            self.assertEqual(window.results.toPlainText(), "Previous valid results")
            self.assertEqual(window.status.text(), "System not found.")
        finally:
            window.close()

    def test_current_system_action_without_system_does_not_acquire_or_clear_field(self):
        coordinator = SurfaceMiningCoordinator()
        window = self._window_type(
            coordinator=coordinator,
            current_system="Kappa",
            current_system_provider=lambda: None,
        )
        coordinator.request_snapshot = Mock()
        try:
            window.results.setPlainText("Previous results")
            window.current_system_button.click()
            self.assertEqual(window.system.text(), "Kappa")
            self.assertEqual(window.results.toPlainText(), "Previous results")
            coordinator.request_snapshot.assert_not_called()
        finally:
            window.close()
            coordinator.shutdown()

    def test_search_success_clears_busy_state_and_releases_worker(self):
        snapshot = SimpleNamespace(system_name="Kappa")
        window = self._window_with_snapshot_operation(Mock(return_value=snapshot))
        try:
            window.search()
            self.assertIsNotNone(window._spansh_generation)
            self._wait_for_completion(window)
            self.assertIs(window.snapshot, snapshot)
            self._assert_ready_status(window, "Kappa")
            self.assertTrue(window.system.isEnabled())
            self.assertFalse(window._indicator_timer.isActive())
            self.assertIsNone(window._spansh_generation)
        finally:
            window.close()

    def test_search_system_not_found_clears_busy_state_and_releases_worker(self):
        window = self._window_with_snapshot_operation(
            Mock(side_effect=SystemNotFoundError("System not found."))
        )
        try:
            window.search()
            self._wait_for_completion(window)
            self.assertEqual(window.status.text(), "System not found.")
            self.assertTrue(window.system.isEnabled())
            self.assertFalse(window._indicator_timer.isActive())
            self.assertIsNone(window._spansh_generation)
        finally:
            window.close()

    def test_search_unexpected_exception_uses_generic_error_and_releases_worker(self):
        window = self._window_with_snapshot_operation(
            Mock(side_effect=TypeError("boom"))
        )
        try:
            window.search()
            self._wait_for_completion(window)
            self.assertEqual(window.status.text(), "Unable to complete the requested update.")
            self.assertTrue(window.system.isEnabled())
            self.assertFalse(window._indicator_timer.isActive())
            self.assertIsNone(window._spansh_generation)
        finally:
            window.close()

    def test_search_can_start_again_after_completion(self):
        snapshots = [SimpleNamespace(system_name="Kappa"), SimpleNamespace(system_name="Lave")]
        operation = Mock(side_effect=snapshots)
        window = self._window_with_snapshot_operation(operation)
        try:
            window.search()
            self._wait_for_completion(window)
            window.system.setText("Lave")
            window.search()
            self._wait_for_completion(window)
            self.assertEqual(operation.call_count, 2)
            self.assertIs(window.snapshot, snapshots[1])
            self._assert_ready_status(window, "Lave")
        finally:
            window.close()

    def test_minimum_demand_enter_recalculates_existing_snapshot_only(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            snapshot = SimpleNamespace(system_name="Kappa")
            analysis = SimpleNamespace(products=(), issues=(), system_name="Kappa")
            window.snapshot = snapshot
            window.service.snapshot_for = Mock()
            window.service.analyze = Mock(return_value=analysis)
            window._render = Mock()
            clear_results = Mock(wraps=window._clear_surface_mining_results)
            window._clear_surface_mining_results = clear_results
            window.minimum_demand.setText("500")
            window.minimum_demand.returnPressed.emit()
            window.service.analyze.assert_called_once_with(
                snapshot,
                top_products=3,
                top_markets=3,
                minimum_demand=500,
                summaries=None,
            )
            window.service.snapshot_for.assert_not_called()
            clear_results.assert_not_called()
            self.assertFalse(window.status.text().startswith("Searching"))
        finally:
            window.close()

    def test_top_controls_recalculate_without_clearing_or_acquisition(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            snapshot = SimpleNamespace(system_name="Kappa")
            window.snapshot = snapshot
            window.service.snapshot_for = Mock()
            window.service.analyze = Mock(return_value=SimpleNamespace(
                products=(), issues=(), system_name="Kappa"))
            window._render = Mock()
            clear_results = Mock(wraps=window._clear_surface_mining_results)
            window._clear_surface_mining_results = clear_results
            window.results.setPlainText("Existing results")

            window.top_products.setValue(4)
            window.top_markets.setValue(4)

            self.assertEqual(window.service.analyze.call_count, 2)
            window.service.snapshot_for.assert_not_called()
            clear_results.assert_not_called()
            self.assertEqual(window.results.toPlainText(), "Existing results")
            self.assertFalse(window._indicator_timer.isActive())
        finally:
            window.close()

    def test_minimum_demand_rejects_invalid_input_without_recalculation(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window.snapshot = SimpleNamespace(system_name="Kappa")
            window.service.analyze = Mock()
            window.minimum_demand.setText("not-a-number")
            self.assertFalse(window.minimum_demand.hasAcceptableInput())
            window.minimum_demand.returnPressed.emit()
            window.service.analyze.assert_not_called()
        finally:
            window.close()

    def test_minimum_demand_real_return_key_recalculates_without_search(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            snapshot = SimpleNamespace(system_name="Kappa")
            analysis = SimpleNamespace(products=(), issues=(), system_name="Kappa")
            window.snapshot = snapshot
            window.service.snapshot_for = Mock()
            window.service.analyze = Mock(return_value=analysis)
            window._render = Mock()
            window.status.setText("Ready — Kappa")

            window.minimum_demand.setFocus()
            window.minimum_demand.selectAll()
            self.qtest.keyClicks(window.minimum_demand, "500")
            self.qtest.keyClick(window.minimum_demand, Qt.Key.Key_Return)

            window.service.analyze.assert_called_once_with(
                snapshot,
                top_products=3,
                top_markets=3,
                minimum_demand=500,
                summaries=None,
            )
            window.service.snapshot_for.assert_not_called()
            self.assertIsNone(window._spansh_generation)
            self.assertFalse(window.status.text().startswith("Searching"))
            self.assertFalse(window._indicator_timer.isActive())
            self.assertEqual(window.system.text(), "Kappa")
            self.assertFalse(window.refresh_button.autoDefault())
            self.assertFalse(window.refresh_button.isDefault())
            self.assertFalse(window.inara_button.autoDefault())
            self.assertFalse(window.inara_button.isDefault())
        finally:
            window.close()

    def test_system_real_return_key_searches_without_updating_inara(self):
        operation = Mock(return_value=SimpleNamespace(system_name="Kappa"))
        window = self._window_with_snapshot_operation(operation)
        update_inara = Mock()
        window.update_inara = update_inara
        try:
            window.system.setFocus()
            self.qtest.keyClick(window.system, Qt.Key.Key_Return)
            self._wait_for_completion(window)
            self.assertEqual(operation.call_count, 1)
            update_inara.assert_not_called()
        finally:
            window.close()

    def test_minimum_demand_real_return_key_does_not_update_inara(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            snapshot = SimpleNamespace(system_name="Kappa")
            analysis = SimpleNamespace(products=(), issues=(), system_name="Kappa")
            window.snapshot = snapshot
            window.service.snapshot_for = Mock()
            window.service.analyze = Mock(return_value=analysis)
            window._render = Mock()
            update_inara = Mock()
            window.update_inara = update_inara
            window.minimum_demand.setFocus()
            window.minimum_demand.selectAll()
            self.qtest.keyClicks(window.minimum_demand, "500")
            self.qtest.keyClick(window.minimum_demand, Qt.Key.Key_Return)
            update_inara.assert_not_called()
        finally:
            window.close()

    def test_refresh_button_still_requests_forced_search_when_clicked(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window.search = Mock()
            window.refresh_button.click()
            window.search.assert_called_once_with(force=True)
        finally:
            window.close()

    def test_results_and_issues_use_horizontal_splitter_with_two_to_one_initial_ratio(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            self.assertEqual(window.size().width(), 1150)
            self.assertEqual(window.size().height(), 800)
            self.assertIsInstance(window.results_splitter, QSplitter)
            self.assertEqual(window.results_splitter.orientation(), Qt.Orientation.Horizontal)
            self.assertEqual(window.results_splitter.count(), 2)
            window.results_splitter.resize(900, 400)
            window.results_splitter.setSizes([600, 300])
            left, right = window.results_splitter.sizes()
            self.assertGreater(left, right)
            self.assertAlmostEqual(left / right, 2, delta=0.1)
            self.assertIs(window.results.parentWidget(), window.results_splitter.widget(0))
            self.assertIs(window.issue_tree.parentWidget(), window.results_splitter.widget(1))
        finally:
            window.close()

    def test_update_inara_button_click_starts_manual_update_path(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window._start = Mock()
            window.inara_button.click()
            window._start.assert_called_once()
            self.assertFalse(window.inara_button.autoDefault())
            self.assertFalse(window.inara_button.isDefault())
        finally:
            window.close()

    def test_fresh_inara_status_uses_relative_age_and_hides_update(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            stored_at = datetime(2026, 9, 30, 7, 0, tzinfo=timezone.utc)
            result = Mock()
            window._apply_inara_snapshot(result, stored_at, fresh=True)
            window.analysis = SimpleNamespace(
                products=(), issues=(), system_name="Kappa",
                eligible_market_count=0, minimum_demand=500,
            )
            now = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
            window.inara_state = f"updated {window._format_inara_age(stored_at, now=now)}"
            window._render()
            self.assertIn("INARA Avg/Max: updated 3h ago", window.results.toPlainText())
            self.assertNotIn("OLD", window.results.toPlainText())
            self.assertNotIn("unavailable", window.results.toPlainText())
            self.assertTrue(window.inara_button.isHidden())
            cursor = window.results.document().find("updated 3h ago")
            self.assertEqual(cursor.charFormat().foreground().color().name(), "#2e7d32")
            prefix = window.results.document().find("INARA Avg/Max:")
            self.assertFalse(prefix.charFormat().hasProperty(QTextFormat.Property.ForegroundBrush))
        finally:
            window.close()

    def test_translated_inara_prefix_does_not_change_base_result_colour(self):
        translations = {"INARA Avg/Max:": "Média/Máximo INARA:"}
        with patch(
            "market_research_window.translate",
            side_effect=lambda _context, source: translations.get(source, source),
        ):
            window = MarketResearchWindow(current_system="Kappa")
            try:
                window._inara_fresh = True
                window.inara_state = "updated 3h ago"
                window.analysis = SimpleNamespace(
                    products=(), issues=(), system_name="Kappa",
                    eligible_market_count=0, minimum_demand=100,
                )
                window._render()
                document = window.results.document()
                prefix = document.find("Média/Máximo INARA:")
                freshness = document.find("updated 3h ago")
                heading = document.find("SURFACE MINING")
                self.assertFalse(prefix.charFormat().hasProperty(QTextFormat.Property.ForegroundBrush))
                self.assertEqual(freshness.charFormat().foreground().color().name(), "#2e7d32")
                self.assertFalse(heading.charFormat().hasProperty(QTextFormat.Property.ForegroundBrush))
            finally:
                window.close()

    def test_stale_inara_fallback_is_old_and_shows_update(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            stored_at = datetime.now(timezone.utc) - timedelta(hours=17)
            window._apply_inara_snapshot(Mock(), stored_at, fresh=False)
            self.assertIn("OLD", window.inara_state)
            self.assertIn("17h ago", window.inara_state)
            self.assertFalse(window.inara_button.isHidden())
            window.analysis = SimpleNamespace(
                products=(), issues=(), system_name="Kappa",
                eligible_market_count=0, minimum_demand=100,
            )
            window._render()
            cursor = window.results.document().find("OLD")
            self.assertEqual(cursor.charFormat().foreground().color().name(), "#f9a825")
            prefix = window.results.document().find("INARA Avg/Max:")
            self.assertFalse(prefix.charFormat().hasProperty(QTextFormat.Property.ForegroundBrush))
        finally:
            window.close()

    def test_unavailable_inara_shows_update(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window._inara_failed("offline")
            self.assertEqual(window.inara_state, "unavailable")
            self.assertFalse(window.inara_button.isHidden())
            window.analysis = SimpleNamespace(
                products=(), issues=(), system_name="Kappa",
                eligible_market_count=0, minimum_demand=100,
            )
            window._render()
            cursor = window.results.document().find("unavailable")
            self.assertFalse(cursor.charFormat().foreground().isOpaque())
        finally:
            window.close()

    def test_successful_manual_inara_update_hides_button_and_uses_snapshot(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            result = Mock()
            with patch("market_research_window.save_summary_cache"):
                window._inara_succeeded(result)
            self.assertIs(window.inara_snapshot, result)
            self.assertTrue(window.inara_state.startswith("updated "))
            self.assertTrue(window.inara_button.isHidden())
        finally:
            window.close()

    def test_failed_inara_update_preserves_stale_fallback(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            result = Mock()
            window._apply_inara_snapshot(
                result, datetime.now(timezone.utc) - timedelta(hours=17), fresh=False
            )
            window._inara_failed("offline")
            self.assertIs(window.inara_snapshot, result)
            self.assertIn("OLD", window.inara_state)
            self.assertFalse(window.inara_button.isHidden())
        finally:
            window.close()

    def test_market_age_formatting_uses_compact_elapsed_units(self):
        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(MarketResearchWindow._format_market_age(now - timedelta(seconds=30), now=now), "just now")
        self.assertEqual(MarketResearchWindow._format_market_age(now - timedelta(minutes=35), now=now), "35m")
        self.assertEqual(MarketResearchWindow._format_market_age(now - timedelta(hours=23), now=now), "23h")
        self.assertEqual(MarketResearchWindow._format_market_age(now - timedelta(hours=28), now=now), "1d")
        self.assertEqual(MarketResearchWindow._format_market_age(now - timedelta(days=2), now=now), "2d")
        self.assertEqual(MarketResearchWindow._format_market_age(now + timedelta(seconds=30), now=now), "just now")

    def test_market_rendering_uses_human_readable_age(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
            station = SimpleNamespace(name="Darboux Station", max_landing_pad="M")
            market = SimpleNamespace(
                station=station,
                sell_price=273674,
                demand=17729,
                market_updated_at=updated_at,
            )
            product = SimpleNamespace(
                commodity="Painite",
                summary=None,
                bodies=(),
                markets=(market,),
            )
            window.analysis = SimpleNamespace(
                system_name="Kappa", products=(product,), issues=(),
                eligible_market_count=1, minimum_demand=100,
            )
            window._render()
            rendered = window.results.toPlainText()
            self.assertIn("SURFACE MINING | 1 MARKETS | 37 PRODUCTS | LOCAL DEMAND > 100 t", rendered)
            self.assertNotIn("KAPPA", rendered.splitlines()[0])
            self.assertIn("Darboux Station", rendered)
            self.assertIn("Age 2h", rendered)
            self.assertNotIn(updated_at.isoformat(), rendered)
        finally:
            window.close()

    def test_product_result_typography_is_limited_to_left_result_blocks(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            product = SimpleNamespace(commodity="Monazite", summary=None, bodies=(), markets=())
            window.analysis = SimpleNamespace(
                system_name="Kappa", products=(product,), issues=(),
                eligible_market_count=1, minimum_demand=100,
            )
            window._render()
            document = window.results.document()
            heading = document.find("MONAZITE")
            suffix = document.find("Probably on:")
            detail = document.find("INARA Avg:")
            summary = document.find("SURFACE MINING |")
            self.assertEqual(heading.charFormat().fontWeight(), 700)
            self.assertNotEqual(suffix.charFormat().fontWeight(), 700)
            self.assertEqual(heading.charFormat().fontPointSize(), window.results.font().pointSizeF() + 2)
            self.assertEqual(detail.charFormat().fontPointSize(), window.results.font().pointSizeF() + 2)
            self.assertEqual(summary.charFormat().fontPointSize(), window.results.font().pointSizeF() + 2)
            self.assertNotEqual(summary.charFormat().fontWeight(), 700)
            self.assertIn("MONAZITE", window.results.toPlainText())
        finally:
            window.close()

    def test_ready_status_preserves_localized_prefix_and_styles_only_uppercase_system(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window._set_ready_status("Kappa")
            self._assert_ready_status(window, "Kappa")
        finally:
            window.close()

    def test_market_issues_are_collapsed_independent_groups(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window.analysis = SimpleNamespace(
                system_name="Kappa",
                products=(),
                eligible_market_count=0, minimum_demand=100,
                issues=(
                    MarketIssue("Invalid A", "Station has no valid market data.", "no_valid_data"),
                    MarketIssue("Invalid B", "Station has no valid market data.", "no_valid_data"),
                    MarketIssue("Old A", "Market data is too old.", "too_old"),
                ),
            )
            window._render()
            self.assertFalse(window.issue_heading.isHidden())
            self.assertEqual(window.issue_tree.topLevelItemCount(), 2)
            groups = [window.issue_tree.topLevelItem(index) for index in range(2)]
            self.assertEqual(groups[0].text(0), "No valid market data (2)")
            self.assertEqual(groups[1].text(0), "Too old >365 days (1)")
            self.assertFalse(groups[0].isExpanded())
            self.assertFalse(groups[1].isExpanded())
            groups[0].setExpanded(True)
            self.assertEqual(groups[0].childCount(), 2)
            self.assertEqual(groups[0].child(0).text(0), "Invalid A")
            self.assertNotIn("Station has no valid market data", groups[0].child(0).text(0))
        finally:
            window.close()

    def test_issue_station_double_click_copies_name_and_feedback(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window.analysis = SimpleNamespace(
                system_name="Kappa", products=(), eligible_market_count=0, minimum_demand=100,
                issues=(MarketIssue("Richelieu Biological Forum", "Station has no valid market data.", "no_valid_data"),),
            )
            window._render()
            group = window.issue_tree.topLevelItem(0)
            station = group.child(0)
            self.assertEqual(window.issue_tree.columnCount(), 1)
            self.app.clipboard().clear()
            window.issue_tree.itemDoubleClicked.emit(station, 0)
            self.assertEqual(self.app.clipboard().text(), "Richelieu Biological Forum")
            self.assertEqual(station.text(0), "Richelieu Biological Forum")
            self.assertNotIn("Copied", self.app.clipboard().text())
            self.assertIs(window._copied_issue_item, station)
            self.assertTrue(window._issue_feedback_timer.isActive())
            window._issue_feedback_timer.timeout.emit()
            self.assertEqual(station.text(0), "Richelieu Biological Forum")
            self.assertIsNone(window._copied_issue_item)
        finally:
            window.close()

    def test_issue_delegate_reserves_bounded_non_overlapping_feedback_region(self):
        delegate = _IssueItemDelegate()
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 1000, 20)
        feedback_rect, station_rect = delegate._station_rects(option)
        self.assertLess(feedback_rect.width(), option.rect.width() // 2)
        self.assertGreater(station_rect.left(), feedback_rect.right())
        self.assertGreater(station_rect.width(), option.rect.width() // 2)
        inactive_start = station_rect.left()
        active_feedback_rect, active_station_rect = delegate._station_rects(option)
        self.assertEqual(active_station_rect.left(), inactive_start)
        self.assertFalse(feedback_rect.intersects(station_rect))
        self.assertFalse(active_feedback_rect.intersects(active_station_rect))

    def test_issue_delegate_origin_compensates_for_child_indentation(self):
        from PySide6.QtWidgets import QTreeWidget

        tree = QTreeWidget()
        delegate = _IssueItemDelegate(tree)
        parent = QTreeWidgetItem(tree, ["Too old >365 days (3)"])
        child = QTreeWidgetItem(parent, ["Station"])
        option = QStyleOptionViewItem()
        option.rect = QRect(tree.indentation(), 0, 1000, 20)
        feedback_rect, station_rect = delegate._station_rects(option, child)
        self.assertEqual(feedback_rect.left(), 2)
        self.assertGreater(station_rect.left(), feedback_rect.right())
        tree.deleteLater()

    def test_issue_category_double_click_does_not_copy_and_second_copy_rearms_feedback(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window.analysis = SimpleNamespace(
                system_name="Kappa", products=(), eligible_market_count=0, minimum_demand=100,
                issues=(
                    MarketIssue("Station A", "Station has no valid market data.", "no_valid_data"),
                    MarketIssue("Station B", "Station has no valid market data.", "no_valid_data"),
                ),
            )
            window._render()
            group = window.issue_tree.topLevelItem(0)
            self.app.clipboard().setText("unchanged")
            window.issue_tree.itemDoubleClicked.emit(group, 0)
            self.assertEqual(self.app.clipboard().text(), "unchanged")
            window.issue_tree.itemDoubleClicked.emit(group.child(0), 0)
            first_timer = window._issue_feedback_timer.remainingTime()
            window.issue_tree.itemDoubleClicked.emit(group.child(1), 0)
            self.assertEqual(self.app.clipboard().text(), "Station B")
            self.assertIsNot(window._copied_issue_item, group.child(0))
            self.assertIs(window._copied_issue_item, group.child(1))
            self.assertGreater(window._issue_feedback_timer.remainingTime(), 0)
            self.assertGreaterEqual(window._issue_feedback_timer.remainingTime(), first_timer - 50)
        finally:
            window.close()

    def test_market_issues_section_is_hidden_when_empty(self):
        window = MarketResearchWindow(current_system="Kappa")
        try:
            window.analysis = SimpleNamespace(
                system_name="Kappa", products=(), issues=(),
                eligible_market_count=0, minimum_demand=100,
            )
            window._render()
            self.assertTrue(window.issue_heading.isHidden())
            self.assertTrue(window.issue_tree.isHidden())
        finally:
            window.close()

    def test_worker_reports_unexpected_failure_and_finishes(self):
        worker = _Worker(lambda: (_ for _ in ()).throw(TypeError("boom")))
        failures = []
        finished = []
        worker.failed.connect(failures.append)
        worker.finished.connect(lambda: finished.append(True))
        worker.run()
        self.assertEqual(failures, ["Unable to complete the requested update."])
        self.assertEqual(finished, [True])

    def test_current_button_indicator_matches_known_system(self):
        latest = ["Kappa"]
        window = MarketResearchWindow(
            current_system=" kApPa ", current_system_provider=lambda: latest[0]
        )
        try:
            self.assertIn("color: #2e7d32", window.current_system_button.styleSheet())
            window.system.setText("Sol")
            self.assertIn("color: #f9a825", window.current_system_button.styleSheet())
            latest[0] = None
            window.update_current_system_indicator()
            self.assertEqual(window.current_system_button.styleSheet(), "")
        finally:
            window.close()

    def test_current_button_click_selects_known_system_and_becomes_green(self):
        latest = ["Kappa"]
        coordinator = SurfaceMiningCoordinator()
        window = self._window_type(
            coordinator=coordinator,
            current_system="Sol",
            current_system_provider=lambda: latest[0],
        )
        try:
            coordinator.request_snapshot = Mock(return_value=17)
            window.current_system_button.click()
            self.assertEqual(window.system.text(), "Kappa")
            self.assertIn("color: #2e7d32", window.current_system_button.styleSheet())
            coordinator.request_snapshot.assert_called_once_with("Kappa", force=False)
        finally:
            coordinator.shutdown()
            window.close()

    def test_window_uses_one_instance_state_and_manual_inara_success(self):
        with tempfile.TemporaryDirectory() as directory:
            window = MarketResearchWindow(cache_path=Path(directory) / "inara.json", current_system="Kappa")
            try:
                self.assertEqual(window.system.text(), "Kappa")
                result = Mock(summaries=(), is_complete=True, issues=())
                with patch("market_research_window.save_summary_cache") as save:
                    window._inara_succeeded(result)
                self.assertIs(window.inara_snapshot, result)
                save.assert_called_once()
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
