import importlib.util
import threading
import unittest
from unittest.mock import Mock

from elite_dangerous.market import AcquisitionCancelled, AcquisitionDeadlineExceeded
from surface_mining_coordinator import SurfaceMiningCoordinator
from surface_mining_service import MarketAcquisitionError


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 not installed")
class SurfaceMiningCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtTest import QTest

        cls.app = QApplication.instance() or QApplication([])
        cls.qtest = QTest

    def _wait(self, predicate):
        for _ in range(200):
            self.qtest.qWait(5)
            if predicate():
                return
        self.fail("coordinator operation did not complete")

    def test_operational_request_starts_once_and_exposes_raw_snapshot(self):
        snapshot = object()
        service = Mock()
        service.snapshot_for.return_value = snapshot
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        results = []
        coordinator.snapshot_succeeded.connect(lambda _generation, value: results.append(value))

        generation = coordinator.request_snapshot("Kappa")
        self._wait(lambda: not coordinator.active)

        self.assertEqual(generation, 1)
        self.assertEqual(results, [snapshot])
        service.snapshot_for.assert_called_once_with(
            "Kappa", force=False, context=service.snapshot_for.call_args.kwargs["context"],
            on_acquisition=service.snapshot_for.call_args.kwargs["on_acquisition"],
        )
        service.analyze.assert_not_called()
        coordinator.shutdown()

    def test_second_request_is_rejected_without_cancelling_first(self):
        started = threading.Event()
        release = threading.Event()
        snapshot = object()

        def acquire(_name, *, force, context, on_acquisition):
            on_acquisition()
            started.set()
            release.wait(1)
            return snapshot

        service = Mock()
        service.snapshot_for.side_effect = acquire
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        rejected = []
        coordinator.request_rejected.connect(rejected.append)
        coordinator.request_snapshot("Kappa")
        self.assertTrue(started.wait(1))
        self.assertIsNone(coordinator.request_snapshot("Sol"))
        self.assertTrue(coordinator.active)
        self.assertEqual(service.snapshot_for.call_count, 1)
        release.set()
        self._wait(lambda: not coordinator.active)
        self.assertTrue(rejected)
        coordinator.shutdown()

    def test_force_is_forwarded(self):
        service = Mock()
        service.snapshot_for.return_value = object()
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)

        coordinator.request_snapshot("Kappa", force=True)
        self._wait(lambda: not coordinator.active)

        self.assertTrue(service.snapshot_for.call_args.kwargs["force"])
        coordinator.shutdown()

    def test_acquisition_started_is_reported_with_generation_and_request_mode(self):
        service = Mock()

        def snapshot_for(_name, *, force, context, on_acquisition):
            on_acquisition()
            return object()

        service.snapshot_for.side_effect = snapshot_for
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        started = []
        coordinator.acquisition_started.connect(lambda *args: started.append(args))

        coordinator.request_snapshot("Kappa", force=False)
        self._wait(lambda: not coordinator.active and len(started) == 1)

        self.assertEqual(started, [(1, "Kappa", False)])

    def test_completed_request_releases_coordinator_for_next_request(self):
        service = Mock()
        service.snapshot_for.side_effect = [object(), object()]
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)

        coordinator.request_snapshot("Kappa")
        self._wait(lambda: not coordinator.active)
        coordinator.request_snapshot("Lave")
        self._wait(lambda: not coordinator.active)

        self.assertEqual(service.snapshot_for.call_count, 2)

    def test_typed_and_ordinary_failures_remain_distinguishable(self):
        for error, signal_name in (
            (AcquisitionCancelled("cancelled"), "acquisition_cancelled"),
            (AcquisitionDeadlineExceeded("expired"), "acquisition_deadline_exceeded"),
            (MarketAcquisitionError("offline"), "acquisition_failed"),
        ):
            with self.subTest(error=type(error).__name__):
                service = Mock()
                service.snapshot_for.side_effect = error
                coordinator = SurfaceMiningCoordinator(service=service)
                self.addCleanup(coordinator.shutdown)
                received = []
                getattr(coordinator, signal_name).connect(
                    lambda _generation, value, received=received: received.append(value)
                )
                coordinator.request_snapshot("Kappa")
                self._wait(lambda: not coordinator.active)
                self.assertIs(received[0], error)
                coordinator.shutdown()

    def test_shutdown_idle_rejects_future_requests(self):
        coordinator = SurfaceMiningCoordinator(service=Mock())
        self.addCleanup(coordinator.shutdown)
        coordinator.shutdown()

        self.assertTrue(coordinator.closing)
        self.assertIsNone(coordinator.request_snapshot("Kappa"))

    def test_shutdown_cancels_exact_context_joins_thread_and_suppresses_callback(self):
        started = threading.Event()
        snapshot = object()

        def acquire(_name, *, force, context, on_acquisition):
            on_acquisition()
            started.set()
            while not context.cancelled:
                context.clock()
            raise AcquisitionCancelled("shutdown")

        service = Mock()
        service.snapshot_for.side_effect = acquire
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        succeeded = []
        cancelled = []
        acquisitions = []
        coordinator.snapshot_succeeded.connect(lambda *_args: succeeded.append(True))
        coordinator.acquisition_cancelled.connect(lambda *_args: cancelled.append(True))
        coordinator.acquisition_started.connect(
            lambda *args: acquisitions.append(args)
        )
        coordinator.request_snapshot("Kappa")
        self.assertTrue(started.wait(1))
        active_context = coordinator.active_context

        coordinator.shutdown()

        self.assertTrue(active_context.cancelled)
        self.assertFalse(coordinator.active)
        self.assertIsNone(coordinator.active_context)
        self.assertEqual(succeeded, [])
        self.assertEqual(cancelled, [])
        self.assertEqual(acquisitions, [])

    def test_prefetch_is_silent_until_promoted(self):
        started = threading.Event()
        release = threading.Event()
        service = Mock()

        def acquire(_name, *, force, context, on_acquisition):
            on_acquisition()
            started.set()
            release.wait(1)
            return object()

        service.snapshot_for.side_effect = acquire
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        started_signals = []
        results = []
        coordinator.acquisition_started.connect(lambda *args: started_signals.append(args))
        coordinator.snapshot_succeeded.connect(lambda *args: results.append(args))

        coordinator.prefetch_snapshot("Kappa")
        self.assertTrue(started.wait(1))
        self.qtest.qWait(10)
        self.assertEqual(started_signals, [])
        self.assertEqual(results, [])
        release.set()
        self._wait(lambda: not coordinator.active)
        self.assertEqual(started_signals, [])
        self.assertEqual(results, [])

    def test_same_system_foreground_promotes_prefetch_without_duplicate(self):
        started = threading.Event()
        release = threading.Event()
        service = Mock()

        def acquire(_name, *, force, context, on_acquisition):
            on_acquisition()
            started.set()
            release.wait(1)
            return "snapshot"

        service.snapshot_for.side_effect = acquire
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        results = []
        started_signals = []
        coordinator.snapshot_succeeded.connect(lambda *args: results.append(args))
        coordinator.acquisition_started.connect(lambda *args: started_signals.append(args))

        coordinator.prefetch_snapshot("Kappa")
        self.assertTrue(started.wait(1))
        generation = coordinator.request_snapshot("Kappa")
        release.set()
        self._wait(lambda: not coordinator.active and len(results) == 1)

        self.assertEqual(service.snapshot_for.call_count, 1)
        self.assertEqual(results, [(generation, "snapshot")])
        self.assertEqual(started_signals, [(generation, "Kappa", False)])

    def test_different_system_foreground_cancels_prefetch_before_starting(self):
        first_started = threading.Event()
        first_cancelled = threading.Event()
        second_started = threading.Event()
        calls = []
        service = Mock()

        def acquire(name, *, force, context, on_acquisition):
            calls.append(name)
            on_acquisition()
            if name == "Kappa":
                first_started.set()
                while not context.cancelled:
                    context.clock()
                first_cancelled.set()
                raise AcquisitionCancelled("cancelled")
            second_started.set()
            return "sol"

        service.snapshot_for.side_effect = acquire
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        failures = []
        results = []
        coordinator.acquisition_failed.connect(lambda *args: failures.append(args))
        coordinator.snapshot_succeeded.connect(lambda *args: results.append(args))

        coordinator.prefetch_snapshot("Kappa")
        self.assertTrue(first_started.wait(1))
        generation = coordinator.request_snapshot("Sol")
        self._wait(lambda: second_started.is_set() and not coordinator.active)

        self.assertTrue(first_cancelled.is_set())
        self.assertEqual(calls, ["Kappa", "Sol"])
        self.assertEqual(failures, [])
        self.assertEqual(results, [(generation, "sol")])

    def test_prefetch_failure_is_silent_and_later_foreground_request_works(self):
        service = Mock()
        service.snapshot_for.side_effect = [MarketAcquisitionError("offline"), "snapshot"]
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        failures = []
        results = []
        coordinator.acquisition_failed.connect(lambda *args: failures.append(args))
        coordinator.snapshot_succeeded.connect(lambda *args: results.append(args))

        coordinator.prefetch_snapshot("Kappa")
        self._wait(lambda: not coordinator.active)
        self.assertEqual(failures, [])
        generation = coordinator.request_snapshot("Kappa")
        self._wait(lambda: not coordinator.active)
        self.assertEqual(results, [(generation, "snapshot")])

    def test_force_foreground_request_preempts_prefetch_and_preserves_force(self):
        started = threading.Event()
        service = Mock()

        def acquire(name, *, force, context, on_acquisition):
            on_acquisition()
            if name == "Kappa" and not force:
                started.set()
                while not context.cancelled:
                    context.clock()
                raise AcquisitionCancelled("cancelled")
            self.assertTrue(force)
            return "fresh"

        service.snapshot_for.side_effect = acquire
        coordinator = SurfaceMiningCoordinator(service=service)
        self.addCleanup(coordinator.shutdown)
        results = []
        coordinator.snapshot_succeeded.connect(lambda *args: results.append(args))

        coordinator.prefetch_snapshot("Kappa")
        self.assertTrue(started.wait(1))
        generation = coordinator.request_snapshot("Kappa", force=True)
        self._wait(lambda: not coordinator.active and results)
        self.assertEqual(results, [(generation, "fresh")])
        self.assertEqual(service.snapshot_for.call_count, 2)


if __name__ == "__main__":
    unittest.main()
