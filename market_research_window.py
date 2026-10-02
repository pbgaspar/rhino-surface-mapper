"""Functional Market Research window for Surface Mining assistance."""

from datetime import datetime, timedelta, timezone
from typing import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QColor, QIntValidator, QPalette, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSpinBox, QStyleOptionViewItem, QStyledItemDelegate, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from elite_dangerous.market import load_summary_cache, save_summary_cache, SURFACE_COMMODITIES
from inara_acquisition import fetch_inara_summary
from surface_mining_service import MarketAcquisitionError, SystemNotFoundError
from i18n import translate


INARA_TTL = timedelta(hours=12)
INARA_CACHE_PATH = Path(__file__).resolve().parent / "inara_summary_cache_v1.json"


class _IssueItemDelegate(QStyledItemDelegate):
    """Paint station rows with a stable leading copy-feedback region."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_item = None

    def _reserved_width(self, option):
        return option.fontMetrics.horizontalAdvance("Copied") + 12

    def _presentation_origin(self, option, item):
        """Align child presentation with its category text origin."""
        view = self.parent()
        depth = 0
        ancestor = item.parent()
        while ancestor is not None:
            depth += 1
            ancestor = ancestor.parent()
        return option.rect.left() - view.indentation() * depth

    def _station_rects(self, option, item=None):
        """Return non-overlapping feedback and station-name rectangles."""
        reserved = self._reserved_width(option)
        origin = self._presentation_origin(option, item) if item is not None else option.rect.left()
        feedback = QRect(origin + 2, option.rect.top() + 2, max(0, reserved - 4), max(0, option.rect.height() - 4))
        station_name = QRect(origin + reserved, option.rect.top(), max(0, option.rect.right() - origin - reserved + 1), option.rect.height())
        return feedback, station_name

    def paint(self, painter, option, index):
        item = self.parent().itemFromIndex(index)
        if item is None or item.parent() is None:
            super().paint(painter, option, index)
            return
        feedback_rect, station_rect = self._station_rects(option, item)
        text_option = QStyleOptionViewItem(option)
        text_option.rect = station_rect
        super().paint(painter, text_option, index)
        if item is not self.active_item:
            return
        is_dark = option.palette.color(QPalette.ColorRole.Window).lightness() < 128
        background = QColor("#2e7d32" if is_dark else "#c8e6c9")
        foreground = QColor("#ffffff" if is_dark else "#1b5e20")
        painter.save()
        painter.fillRect(feedback_rect, background)
        painter.setPen(foreground)
        painter.drawText(feedback_rect, Qt.AlignmentFlag.AlignCenter, translate('MarketResearchWindow', "Copied"))
        painter.restore()


class _Worker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self):
        try:
            self.succeeded.emit(self.operation())
        except (SystemNotFoundError, MarketAcquisitionError, RuntimeError, OSError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit(translate('MarketResearchWindow', "Unable to complete the requested update."))
        finally:
            self.finished.emit()


class MarketResearchWindow(QDialog):
    """Non-modal Surface Mining window retaining state for the session."""

    def __init__(self, parent=None, *, coordinator, current_system="", current_system_provider: Callable[[], str | None] | None = None, cache_path=INARA_CACHE_PATH):
        super().__init__(parent)
        self.setWindowTitle(translate('MarketResearchWindow', "Market Research — Surface Mining"))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint |
                            Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(900, 650)
        self.coordinator = coordinator
        self.service = coordinator.service
        self._current_system_provider = current_system_provider
        self.inara_cache_path = Path(cache_path)
        self.snapshot = None
        self.analysis = None
        self.inara_snapshot = None
        self.inara_state = "unavailable"
        self.inara_stored_at = None
        self._inara_fresh = None
        self._spansh_generation = None
        self._inara_thread = None
        self._inara_worker = None
        self._indicator = 0
        self._indicator_timer = QTimer(self)
        self._indicator_timer.timeout.connect(self._animate)
        self.coordinator.snapshot_succeeded.connect(self._search_succeeded)
        self.coordinator.acquisition_started.connect(self._acquisition_started)
        self.coordinator.acquisition_cancelled.connect(self._search_cancelled)
        self.coordinator.acquisition_deadline_exceeded.connect(self._search_failed)
        self.coordinator.acquisition_failed.connect(self._search_failed)

        root = QVBoxLayout(self)
        system_row = QHBoxLayout()
        self.system_label = QLabel(translate('MarketResearchWindow', "System"))
        self.system = QLineEdit(current_system or "")
        self.system.returnPressed.connect(self.search)
        self.current_system_button = QPushButton(translate('MarketResearchWindow', "Current >"))
        self.current_system_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.current_system_button.setAutoDefault(False)
        self.current_system_button.setDefault(False)
        self.current_system_button.setToolTip(translate('MarketResearchWindow', "Use the commander's current or last known system."))
        self.current_system_button.clicked.connect(self.use_current_system)
        self.system.textChanged.connect(self.update_current_system_indicator)
        self.refresh_button = QPushButton(translate('MarketResearchWindow', "Refresh"))
        self.refresh_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.refresh_button.setAutoDefault(False)
        self.refresh_button.setDefault(False)
        self.refresh_button.setToolTip(
            translate('MarketResearchWindow', "Download fresh market data for this system, ignoring the cached snapshot.")
        )
        self.refresh_button.clicked.connect(lambda: self.search(force=True))
        system_row.addWidget(self.system_label)
        system_row.addWidget(self.current_system_button)
        system_row.addWidget(self.system, 1)
        system_row.addWidget(self.refresh_button)
        root.addLayout(system_row)
        self.update_current_system_indicator()

        self.top_products = self._spin(3, 3, 10)
        self.top_markets = self._spin(3, 3, 5)
        self.minimum_demand = QLineEdit("100")
        self.top_products_label = QLabel(translate('MarketResearchWindow', "Top products"))
        self.top_markets_label = QLabel(translate('MarketResearchWindow', "Top markets per product"))
        self.minimum_demand_label = QLabel(translate('MarketResearchWindow', "Minimum demand (t)"))
        for control in (self.top_products, self.top_markets):
            control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            control.setFixedWidth(control.sizeHint().width())
        self.minimum_demand.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.minimum_demand.setFixedWidth(
            self.minimum_demand.fontMetrics().horizontalAdvance("2000000") + 24
        )
        self.top_products.setToolTip(translate('MarketResearchWindow', "Number of best Surface Mining commodities to show."))
        self.top_markets.setToolTip(translate('MarketResearchWindow', "Maximum number of markets shown for each commodity."))
        self.minimum_demand.setToolTip(translate('MarketResearchWindow', "Ignore markets with demand below this value."))
        self.minimum_demand.setValidator(QIntValidator(0, 2_000_000, self.minimum_demand))
        self.minimum_demand.returnPressed.connect(self._commit_minimum_demand)
        parameter_row = QHBoxLayout()
        parameter_row.addWidget(self.top_products_label)
        parameter_row.addWidget(self.top_products)
        parameter_row.addWidget(self.top_markets_label)
        parameter_row.addWidget(self.top_markets)
        parameter_row.addWidget(self.minimum_demand_label)
        parameter_row.addWidget(self.minimum_demand)
        parameter_row.addStretch(1)
        root.addLayout(parameter_row)
        self.status = QLabel()
        root.addWidget(self.status)
        self.inara_button = QPushButton(translate('MarketResearchWindow', "Update INARA"))
        self.inara_button.setAutoDefault(False)
        self.inara_button.setDefault(False)
        self.inara_button.setToolTip(translate('MarketResearchWindow', "Update the cached INARA Avg/Max reference prices."))
        self.inara_button.hide()
        self.inara_button.clicked.connect(self.update_inara)
        root.addWidget(self.inara_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.results = QTextEdit()
        self.results.setReadOnly(True)
        root.addWidget(self.results, 1)
        self.issue_tree = QTreeWidget()
        self.issue_tree.setHeaderHidden(True)
        self.issue_tree.setRootIsDecorated(True)
        self.issue_delegate = _IssueItemDelegate(self.issue_tree)
        self.issue_tree.setItemDelegate(self.issue_delegate)
        self.issue_heading = QLabel(translate('MarketResearchWindow', "Market data issues"))
        self.issue_heading.setVisible(False)
        root.addWidget(self.issue_heading)
        self._copied_issue_item = None
        self._issue_feedback_timer = QTimer(self)
        self._issue_feedback_timer.setSingleShot(True)
        self._issue_feedback_timer.timeout.connect(self._clear_issue_copy_feedback)
        self.issue_tree.setVisible(False)
        self.issue_tree.itemDoubleClicked.connect(self._copy_issue_station)
        root.addWidget(self.issue_tree)
        self.note = QLabel(translate('MarketResearchWindow', "When docked, use EDMC or another market-data updater to refresh and share station market data."))
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        for control in (self.top_products, self.top_markets):
            control.valueChanged.connect(self.recalculate)

    def _commit_minimum_demand(self):
        """Recalculate locally after a valid minimum-demand value is confirmed."""
        if self.minimum_demand.hasAcceptableInput():
            self.recalculate()

    @staticmethod
    def _spin(value, minimum, maximum):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def initialize(self):
        self.update_inara(startup=True)
        if self._current_system_provider is not None:
            current_system = self._current_system_provider()
            if isinstance(current_system, str) and current_system.strip():
                self.system.setText(current_system.strip())
        if self.system.text().strip():
            self.search()

    def use_current_system(self):
        if self._current_system_provider is None:
            return
        current_system = self._current_system_provider()
        if not isinstance(current_system, str) or not current_system.strip():
            return
        self.system.setText(current_system.strip())
        self.search()

    @staticmethod
    def _normalized_system_name(value):
        return value.strip().casefold() if isinstance(value, str) and value.strip() else None

    def update_current_system_indicator(self):
        """Update only the Current button text colour for the known system state."""
        selected = self._normalized_system_name(self.system.text())
        known = None
        if self._current_system_provider is not None:
            known = self._normalized_system_name(self._current_system_provider())
        if known is None or selected is None:
            self.current_system_button.setStyleSheet("")
        elif selected == known:
            self.current_system_button.setStyleSheet("color: #2e7d32;")
        else:
            self.current_system_button.setStyleSheet("color: #f9a825;")

    def _start(self, operation, success, failure, *, kind):
        thread = QThread(self)
        worker = _Worker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(success)
        worker.failed.connect(failure)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._clear_operation(kind))
        thread.finished.connect(thread.deleteLater)
        setattr(self, f"_{kind}_worker", worker)
        setattr(self, f"_{kind}_thread", thread)
        thread.start()

    def _clear_operation(self, kind):
        """Release the worker and thread references after thread completion."""
        setattr(self, f"_{kind}_worker", None)
        setattr(self, f"_{kind}_thread", None)

    def search(self, *, force=False):
        if self._spansh_generation is not None:
            return
        name = self.system.text().strip()
        self.system.setText(name)
        if not name:
            self.status.setText(translate('MarketResearchWindow', "Enter a system name."))
            return
        generation = self.coordinator.request_snapshot(name, force=force)
        if generation is None:
            self.status.setText(translate('MarketResearchWindow', "Unable to start the requested update."))
            return
        self._spansh_generation = generation

    @Slot(int, str, bool)
    def _acquisition_started(self, generation, system_name, force):
        if generation != self._spansh_generation:
            return
        if not force:
            self._clear_surface_mining_results()
        self._set_busy(True, f"{translate('MarketResearchWindow', 'Searching')} {system_name} |")

    def _clear_surface_mining_results(self):
        """Clear only Surface Mining output before a normal acquisition."""
        self.analysis = None
        self.results.clear()
        self.results.setPlainText(f"{translate('MarketResearchWindow', 'INARA Avg/Max:')} {self.inara_state}")
        self._style_inara_status()
        self.issue_tree.clear()
        self.issue_heading.setVisible(False)
        self.issue_tree.setVisible(False)
        self._issue_feedback_timer.stop()
        self._clear_issue_copy_feedback()

    @Slot(object)
    def _search_succeeded(self, generation, snapshot):
        if generation != self._spansh_generation:
            return
        self._spansh_generation = None
        self.snapshot = snapshot
        self._set_busy(False, f"{translate('MarketResearchWindow', 'Ready —')} {snapshot.system_name}")
        self.recalculate(allow_busy=True)

    @Slot(str)
    def _search_cancelled(self, generation, _error):
        if generation != self._spansh_generation:
            return
        self._spansh_generation = None
        self._set_busy(False, "")

    def _search_failed(self, generation, error):
        if generation != self._spansh_generation:
            return
        self._spansh_generation = None
        if isinstance(error, (SystemNotFoundError, MarketAcquisitionError)):
            message = str(error) or translate('MarketResearchWindow', "Unable to retrieve market data.")
        else:
            message = translate('MarketResearchWindow', "Unable to complete the requested update.")
        self._set_busy(False, message)

    def recalculate(self, *, allow_busy=False):
        if self.snapshot is None or (self._spansh_generation is not None and not allow_busy):
            return
        self.analysis = self.service.analyze(
            self.snapshot,
            top_products=self.top_products.value(),
            top_markets=self.top_markets.value(),
            minimum_demand=int(self.minimum_demand.text()),
            summaries=self.inara_snapshot,
        )
        self._render()

    def update_inara(self, *, startup=False):
        if self._inara_thread is not None:
            return
        cached = None
        try:
            cached = load_summary_cache(self.inara_cache_path, tuple(SURFACE_COMMODITIES))
        except (FileNotFoundError, OSError, ValueError):
            pass
        now = datetime.now(timezone.utc)
        if cached is not None and cached.is_fresh(INARA_TTL, now=now) and startup:
            self._apply_inara_snapshot(cached.result, cached.stored_at, fresh=True)
            self.recalculate()
            return
        if cached is not None and startup:
            self._apply_inara_snapshot(cached.result, cached.stored_at, fresh=False)
        self.inara_button.setVisible(True)
        self.inara_button.setEnabled(False)
        self._start(fetch_inara_summary, self._inara_succeeded, self._inara_failed, kind="inara")

    def _inara_succeeded(self, result):
        stored_at = datetime.now(timezone.utc)
        self._apply_inara_snapshot(result, stored_at, fresh=True)
        try:
            save_summary_cache(self.inara_cache_path, result)
        except (OSError, ValueError):
            pass
        self.inara_button.setEnabled(True)
        self.inara_button.hide()
        self.recalculate()

    def _inara_failed(self, _message):
        if self.inara_snapshot is None:
            self.inara_state = "unavailable"
            self.inara_stored_at = None
            self._inara_fresh = None
        self.inara_button.setVisible(True)
        self.inara_button.setEnabled(True)
        self.recalculate()

    def _apply_inara_snapshot(self, result, stored_at, *, fresh):
        """Select an INARA snapshot and update its user-facing state."""
        self.inara_snapshot = result
        self.inara_stored_at = stored_at
        self._inara_fresh = fresh
        age = self._format_inara_age(stored_at)
        self.inara_state = f"{translate('MarketResearchWindow', 'updated')} {age}" if fresh else f"{translate('MarketResearchWindow', 'OLD — updated')} {age}"
        self.inara_button.setVisible(not fresh)

    @staticmethod
    def _format_inara_age(stored_at, *, now=None):
        """Format cache age compactly without exposing the storage timestamp."""
        current = datetime.now(timezone.utc) if now is None else now
        age = max(current - stored_at, timedelta(0))
        minutes = age.total_seconds() // 60
        if minutes < 1:
            return translate('MarketResearchWindow', "just now")
        if minutes < 60:
            return f"{int(minutes)}{translate('MarketResearchWindow', 'm ago')}"
        hours = minutes // 60
        if hours < 24:
            return f"{int(hours)}{translate('MarketResearchWindow', 'h ago')}"
        return f"{int(hours // 24)}{translate('MarketResearchWindow', 'd ago')}"

    def _set_busy(self, busy, text):
        for control in (self.system, self.refresh_button, self.top_products, self.top_markets, self.minimum_demand):
            control.setEnabled(not busy)
        if busy:
            self._indicator_timer.start(250)
        else:
            self._indicator_timer.stop()
        self.status.setText(text)

    def _animate(self):
        self._indicator = (self._indicator + 1) % 4
        self.status.setText(self.status.text().rsplit(" ", 1)[0] + " " + "|—\\/"[self._indicator])

    def _render(self):
        if self.analysis is None:
            return
        now = datetime.now(timezone.utc)
        lines = [
            f"{translate('MarketResearchWindow', 'SURFACE MINING —')} {self.analysis.system_name.upper()} | "
            f"{self.analysis.eligible_market_count} {translate('MarketResearchWindow', 'MARKETS')} | "
            f"{len(SURFACE_COMMODITIES)} {translate('MarketResearchWindow', 'PRODUCTS')} | "
            f"{translate('MarketResearchWindow', 'LOCAL DEMAND >')} {self.analysis.minimum_demand} t",
            f"{translate('MarketResearchWindow', 'INARA Avg/Max:')} {self.inara_state}",
            "",
        ]
        for product in self.analysis.products:
            summary = product.summary
            avg = getattr(summary, "average_sell", None) if summary else None
            maximum = getattr(summary, "maximum_sell", None) if summary else None
            bodies = ", ".join(name.split(self.analysis.system_name + " ", 1)[-1] for name in product.bodies) or translate('MarketResearchWindow', "none identified")
            lines.append(f"{product.commodity} — {translate('MarketResearchWindow', 'Probably on:')} {bodies}")
            unavailable = translate('MarketResearchWindow', "unavailable")
            lines.append(f"  {translate('MarketResearchWindow', 'INARA Avg:')} {avg if avg is not None else unavailable} | {translate('MarketResearchWindow', 'Max:')} {maximum if maximum is not None else unavailable}")
            for market in product.markets:
                age = self._format_market_age(market.market_updated_at, now=now)
                lines.append(f"  {market.station.name} | {translate('MarketResearchWindow', 'Sell')} {market.sell_price} | {translate('MarketResearchWindow', 'Demand')} {market.demand} | {translate('MarketResearchWindow', 'Pad')} {market.station.max_landing_pad or '?'} | {translate('MarketResearchWindow', 'Age')} {age}")
            lines.append("")
        if not self.analysis.products:
            lines.append(translate('MarketResearchWindow', "No eligible commercial results."))
        self.results.setPlainText("\n".join(lines))
        self._style_inara_status()
        self._render_issues(self.analysis.issues)

    def _style_inara_status(self):
        """Colour only the rendered INARA freshness text, not price values."""
        prefix = f"{translate('MarketResearchWindow', 'INARA Avg/Max:')} "
        cursor = self.results.document().find(prefix)
        if cursor.isNull():
            return
        # Collapse the prefix selection before extending to the end of the line;
        # otherwise KeepAnchor would retain the prefix as part of the range.
        cursor.setPosition(cursor.selectionEnd())
        cursor.movePosition(cursor.MoveOperation.EndOfBlock, cursor.MoveMode.KeepAnchor)
        format_ = QTextCharFormat()
        if self._inara_fresh is True:
            format_.setForeground(QColor("#2e7d32"))
        elif self._inara_fresh is False:
            format_.setForeground(QColor("#f9a825"))
        else:
            format_.clearProperty(QTextFormat.Property.ForegroundBrush)
        cursor.mergeCharFormat(format_)

    def _render_issues(self, issues):
        """Render classified market issues as collapsed expandable groups."""
        self._issue_feedback_timer.stop()
        self._clear_issue_copy_feedback()
        self.issue_tree.clear()
        grouped = {
            "no_valid_data": (translate('MarketResearchWindow', "No valid market data"), []),
            "too_old": (translate('MarketResearchWindow', "Too old >365 days"), []),
            "age_unknown": (translate('MarketResearchWindow', "Age unknown"), []),
            "other": (translate('MarketResearchWindow', "Other market data issues"), []),
        }
        for issue in issues:
            label, stations = grouped.get(issue.category, grouped["other"])
            stations.append(issue.station_name)
        groups = [item for item in grouped.values() if item[1]]
        self.issue_heading.setVisible(bool(groups))
        self.issue_tree.setVisible(bool(groups))
        if not groups:
            return
        for label, stations in groups:
            parent = QTreeWidgetItem([f"{label} ({len(stations)})"])
            self.issue_tree.addTopLevelItem(parent)
            parent.setExpanded(False)
            for station_name in stations:
                child = QTreeWidgetItem(parent, [station_name])
                child.setData(0, Qt.ItemDataRole.UserRole, station_name)

    def _copy_issue_station(self, item, _column):
        """Copy a station child name and show temporary row feedback."""
        if item.parent() is None:
            return
        station_name = item.data(0, Qt.ItemDataRole.UserRole)
        if not station_name:
            return
        self._clear_issue_copy_feedback()
        QApplication.clipboard().setText(station_name)
        self._copied_issue_item = item
        self.issue_delegate.active_item = item
        self._issue_feedback_timer.start(3000)
        self.issue_tree.viewport().update()

    def _clear_issue_copy_feedback(self):
        """Remove the temporary copied marker from the active station row."""
        if self._copied_issue_item is not None:
            self._copied_issue_item = None
            self.issue_delegate.active_item = None
            self.issue_tree.viewport().update()

    @staticmethod
    def _format_market_age(updated_at, *, now=None):
        """Format a market timestamp for compact station-row presentation."""
        if updated_at is None:
            return "unknown"
        current = datetime.now(timezone.utc) if now is None else now
        age = max(current.astimezone(timezone.utc) - updated_at.astimezone(timezone.utc), timedelta(0))
        minutes = age.total_seconds() // 60
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{int(minutes)}m"
        hours = minutes // 60
        if hours < 24:
            return f"{int(hours)}h"
        return f"{int(hours // 24)}d"

    def closeEvent(self, event):
        """Stop owned workers before the window is destroyed."""
        if self._inara_thread is not None:
            thread = self._inara_thread
            if thread is not None:
                thread.quit()
                thread.wait(2000)
        super().closeEvent(event)
