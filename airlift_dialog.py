"""Airlift configuration dialog."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from airlift import (
    DEFAULT_DEPLOYMENT_COUNTS,
    OPERATIONAL_COUNTS,
    AirliftConfiguration,
    get_operational_configuration,
)
from airlift_preferences import AIRLIFT_FADE_SECONDS_RANGE
from i18n import translate


class AirliftConfigurationDialog(QDialog):
    """Choose an operational configuration and coverage-disk fade duration."""

    def __init__(
        self,
        parent,
        catalog: Mapping[tuple[int, int], AirliftConfiguration],
        radius_km: int,
        deployment_count: int,
        fade_seconds: int,
    ):
        super().__init__(parent)
        context = "AirliftDialog"
        self.setWindowTitle(translate(context, "Airlift configuration"))

        self.radius = QComboBox()
        for radius in DEFAULT_DEPLOYMENT_COUNTS:
            self.radius.addItem(translate(context, "{radius} km").format(
                radius=radius), radius)
        self.radius.setCurrentIndex(self.radius.findData(radius_km))

        self.deployment_count = QComboBox()
        self.fade_seconds = QSpinBox()
        self.fade_seconds.setRange(*AIRLIFT_FADE_SECONDS_RANGE)
        self.fade_seconds.setSuffix(translate(context, " seconds"))
        self.fade_seconds.setValue(fade_seconds)
        self.coverage = QLabel()
        self.catalog = catalog
        self._initial_count = deployment_count

        form = QFormLayout()
        form.addRow(translate(context, "PML radius:"), self.radius)
        form.addRow(translate(context, "Deployment count:"), self.deployment_count)
        form.addRow(translate(context, "Coverage-disk fade:"), self.fade_seconds)
        form.addRow(self.coverage)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.radius.currentIndexChanged.connect(self._radius_changed)
        self.deployment_count.currentIndexChanged.connect(self._update_coverage)
        self._populate_counts(self._initial_count)

    def _radius_changed(self) -> None:
        radius = self.radius.currentData()
        self._populate_counts(DEFAULT_DEPLOYMENT_COUNTS[radius])

    def _populate_counts(self, selected_count: int) -> None:
        radius = self.radius.currentData()
        self.deployment_count.blockSignals(True)
        self.deployment_count.clear()
        for count in OPERATIONAL_COUNTS[radius]:
            self.deployment_count.addItem(str(count), count)
        index = self.deployment_count.findData(selected_count)
        self.deployment_count.setCurrentIndex(
            index if index >= 0 else self.deployment_count.findData(
                DEFAULT_DEPLOYMENT_COUNTS[radius]))
        self.deployment_count.blockSignals(False)
        self._update_coverage()

    def _update_coverage(self) -> None:
        configuration = get_operational_configuration(
            self.catalog, self.radius.currentData(),
            self.deployment_count.currentData())
        self.coverage.setText(translate(
            "AirliftDialog", "Coverage: {coverage:.1f}%").format(
                coverage=configuration.authoritative_coverage_percent))

    def values(self) -> tuple[int, int, int]:
        """Return the accepted radius, count, and fade preference."""
        return (
            self.radius.currentData(),
            self.deployment_count.currentData(),
            self.fade_seconds.value(),
        )
