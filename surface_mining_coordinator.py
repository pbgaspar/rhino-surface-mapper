"""Session-level operational Surface Mining acquisition coordination."""

from PySide6.QtCore import QObject, QThread, Signal, Slot

from elite_dangerous.market import (
    AcquisitionCancelled,
    AcquisitionContext,
    AcquisitionDeadlineExceeded,
)
from surface_mining_service import SurfaceMiningService


class _SnapshotThread(QThread):
    """Run one bounded synchronous snapshot acquisition and then terminate."""

    succeeded = Signal(int, object)
    acquisition_started = Signal(int, str, bool)
    cancelled = Signal(int, object)
    deadline_exceeded = Signal(int, object)
    failed = Signal(int, object)

    def __init__(self, generation, service, system_name, force, context, parent=None):
        super().__init__(parent)
        self._generation = generation
        self._service = service
        self._system_name = system_name
        self._force = force
        self._context = context

    def run(self):
        try:
            snapshot = self._service.snapshot_for(
                self._system_name,
                force=self._force,
                context=self._context,
                on_acquisition=lambda: self.acquisition_started.emit(
                    self._generation, self._system_name, self._force
                ),
            )
        except AcquisitionCancelled as exc:
            self.cancelled.emit(self._generation, exc)
        except AcquisitionDeadlineExceeded as exc:
            self.deadline_exceeded.emit(self._generation, exc)
        except Exception as exc:
            self.failed.emit(self._generation, exc)
        else:
            self.succeeded.emit(self._generation, snapshot)


class SurfaceMiningCoordinator(QObject):
    """Own one session-level operational Surface Mining acquisition at a time."""

    snapshot_succeeded = Signal(int, object)
    acquisition_started = Signal(int, str, bool)
    acquisition_cancelled = Signal(int, object)
    acquisition_deadline_exceeded = Signal(int, object)
    acquisition_failed = Signal(int, object)
    request_rejected = Signal(str)

    def __init__(self, *, service=None, parent=None):
        super().__init__(parent)
        self.service = service or SurfaceMiningService()
        self._thread = None
        self._context = None
        self._generation = 0
        self._active_generation = None
        self._active_system = None
        self._closing = False
        self._pending_outcome = None
        self._active_mode = None
        self._pending_foreground = None

    @property
    def active_context(self):
        """Return the context owned by the active request, if any."""
        return self._context

    @property
    def active(self):
        """Return whether an operational acquisition is running."""
        return self._thread is not None

    @property
    def closing(self):
        return self._closing

    def request_snapshot(self, system_name, *, force=False):
        """Start one operational request, returning its generation or ``None``."""
        if self._closing:
            self.request_rejected.emit("Coordinator is closing.")
            return None
        requested = system_name.strip()
        if not requested:
            self.request_rejected.emit("System name cannot be empty.")
            return None

        if self._thread is not None:
            if (self._active_mode == "prefetch"
                    and not force
                    and requested.casefold() == self._active_system.casefold()):
                self._active_mode = "foreground"
                return self._active_generation
            if self._active_mode == "prefetch":
                self._generation += 1
                generation = self._generation
                self._pending_foreground = (generation, requested, force)
                self._context.cancel()
                return generation
            self.request_rejected.emit("A Surface Mining acquisition is already active.")
            return None

        return self._start_request(requested, force=force, mode="foreground")

    def prefetch_snapshot(self, system_name):
        """Silently populate the service cache for a newly observed system."""
        if self._closing:
            return None
        requested = system_name.strip()
        if not requested or self._thread is not None:
            return None
        return self._start_request(requested, force=False, mode="prefetch")

    def _start_request(self, requested, *, force, mode, generation=None):
        if generation is None:
            self._generation += 1
            generation = self._generation
        context = AcquisitionContext.with_timeout()
        thread = _SnapshotThread(
            generation, self.service, requested, force, context, self
        )
        thread.succeeded.connect(self._succeeded)
        thread.acquisition_started.connect(self._acquisition_started)
        thread.cancelled.connect(self._cancelled)
        thread.deadline_exceeded.connect(self._deadline_exceeded)
        thread.failed.connect(self._failed)
        thread.setProperty("surface_mining_generation", generation)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._context = context
        self._active_generation = generation
        self._active_system = requested
        self._active_mode = mode
        thread.start()
        return generation

    def shutdown(self):
        """Reject new work, cancel active work, and join its thread safely."""
        self._closing = True
        context = self._context
        thread = self._thread
        if context is not None:
            context.cancel()
        if thread is not None and thread.isRunning():
            thread.wait()
        if thread is not None:
            self._clear_finished_thread(thread, self._active_generation)

    def _accept_callback(self, generation):
        return not self._closing and generation == self._active_generation

    @Slot(int, object)
    def _succeeded(self, generation, snapshot):
        if self._accept_callback(generation):
            self._pending_outcome = ("succeeded", generation, snapshot)

    @Slot(int, str, bool)
    def _acquisition_started(self, generation, system_name, force):
        if self._accept_callback(generation) and self._active_mode == "foreground":
            self.acquisition_started.emit(generation, system_name, force)

    @Slot(int, object)
    def _cancelled(self, generation, error):
        if self._accept_callback(generation):
            self._pending_outcome = ("cancelled", generation, error)

    @Slot(int, object)
    def _deadline_exceeded(self, generation, error):
        if self._accept_callback(generation):
            self._pending_outcome = ("deadline", generation, error)

    @Slot(int, object)
    def _failed(self, generation, error):
        if self._accept_callback(generation):
            self._pending_outcome = ("failed", generation, error)

    @Slot()
    def _thread_finished(self):
        thread = self.sender()
        if thread is None:
            return
        generation = thread.property("surface_mining_generation")
        self._clear_finished_thread(thread, generation)

    def _clear_finished_thread(self, thread, generation):
        if generation != self._active_generation or thread is not self._thread:
            return
        self._thread = None
        self._context = None
        self._active_generation = None
        mode = self._active_mode
        self._active_mode = None
        self._active_system = None
        outcome = self._pending_outcome
        self._pending_outcome = None
        pending = self._pending_foreground
        self._pending_foreground = None
        if pending is not None and not self._closing:
            _, system_name, force = pending
            self._start_request(
                system_name, force=force, mode="foreground", generation=pending[0]
            )
            return
        if outcome is None or self._closing or mode != "foreground":
            return
        kind, generation, value = outcome
        if kind == "succeeded":
            self.snapshot_succeeded.emit(generation, value)
        elif kind == "cancelled":
            self.acquisition_cancelled.emit(generation, value)
        elif kind == "deadline":
            self.acquisition_deadline_exceeded.emit(generation, value)
        else:
            self.acquisition_failed.emit(generation, value)
