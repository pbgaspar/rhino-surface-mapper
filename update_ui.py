"""Main-window update banner and About dialog widgets."""

from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_version import APP_NAME, APP_VERSION, AUTHOR_NAME, GITHUB_REPOSITORY
from i18n import translate
from release_updates import Release, valid_release_url
from update_controller import ManualCheckResult


class UpdateBanner(QWidget):
    """Display a persistent release notice or temporary manual-check feedback."""

    dismiss_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._persistent_release: Release | None = None
        self._displayed_persistently = False
        self.setObjectName("update_banner")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 4, 2)
        self.message = QLabel()
        self.message.setObjectName("update_banner_message")
        row.addWidget(self.message, 1)
        self.open_button = QPushButton(translate("UpdateBanner", "View release"))
        self.open_button.clicked.connect(self._open_release)
        row.addWidget(self.open_button)
        self.dismiss_button = QPushButton(translate("UpdateBanner", "Dismiss"))
        self.dismiss_button.clicked.connect(self._dismiss)
        row.addWidget(self.dismiss_button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._restore_persistent_or_hide)
        self.hide()

    def set_persistent_release(self, release: Release | None) -> None:
        """Show or clear a notification that survives application restarts."""
        self._persistent_release = release
        if release is not None:
            self._show_release(release, persistent=True)
        elif self._displayed_persistently:
            self._displayed_persistently = False
            self._restore_persistent_or_hide()

    def show_manual_result(self, result: ManualCheckResult) -> None:
        """Show a non-blocking result without changing persistent state."""
        self._timer.stop()
        self._displayed_persistently = False
        self.open_button.setVisible(result.release is not None)
        if result.release is not None:
            self._release_to_open = result.release
            self.message.setText(translate(
                "UpdateBanner", "Version {version} is available."
            ).format(version=result.release.version))
        elif result.error:
            self._release_to_open = None
            self.message.setText(translate(
                "UpdateBanner", "Update check failed: {error}"
            ).format(error=result.error))
        else:
            self._release_to_open = None
            self.message.setText(translate(
                "UpdateBanner", "Rhino Surface Mapper is up to date."
            ))
        self.show()
        self._timer.start(10000)

    def show_checking(self) -> None:
        """Give immediate non-modal feedback while a manual check is running."""
        self._timer.stop()
        self._displayed_persistently = False
        self._release_to_open = None
        self.open_button.hide()
        self.message.setText(translate("UpdateBanner", "Checking for updates…"))
        self.show()

    def _show_release(self, release: Release, *, persistent: bool) -> None:
        self._release_to_open = release
        self._displayed_persistently = persistent
        self.message.setText(translate(
            "UpdateBanner", "Version {version} is available."
        ).format(version=release.version))
        self.open_button.show()
        self.show()
        if not persistent:
            self._timer.start(10000)

    def _open_release(self) -> None:
        release = getattr(self, "_release_to_open", None)
        url = valid_release_url(release.url if release is not None else None)
        if url is not None:
            QDesktopServices.openUrl(QUrl(url))

    def _dismiss(self) -> None:
        self._timer.stop()
        if self._displayed_persistently:
            self.dismiss_requested.emit()
        else:
            self._restore_persistent_or_hide()

    def _restore_persistent_or_hide(self) -> None:
        self._timer.stop()
        if self._persistent_release is not None:
            self._show_release(self._persistent_release, persistent=True)
        else:
            self._displayed_persistently = False
            self.hide()


class AboutDialog(QDialog):
    """Show application identity and a validated link to its repository."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translate("AboutDialog", "About Rhino Surface Mapper"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        name = QLabel(f"<b>{APP_NAME}</b>")
        name.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(name)
        layout.addWidget(QLabel(translate(
            "AboutDialog", "Version {version}"
        ).format(version=APP_VERSION)))
        layout.addWidget(QLabel(translate(
            "AboutDialog", "Author: {author}"
        ).format(author=AUTHOR_NAME)))
        layout.addWidget(QLabel(translate(
            "AboutDialog",
            "A companion tool for mapping Surface Mining activity in Elite Dangerous.",
        )))
        repository = QLabel(
            f'<a href="{GITHUB_REPOSITORY}">{GITHUB_REPOSITORY}</a>'
        )
        repository.setOpenExternalLinks(True)
        layout.addWidget(repository)
        close_button = QPushButton(translate("AboutDialog", "Close"))
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        self.setMinimumWidth(380)
