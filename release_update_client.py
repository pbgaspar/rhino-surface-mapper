"""Fetch and select GitHub releases through cancellable Qt networking."""

from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from app_version import GITHUB_RELEASES_API
from release_updates import (
    MAX_RELEASE_PAGES,
    RELEASE_PAGE_SIZE,
    Release,
    ReleaseCheckError,
    newest_release,
    parse_release_entries,
)


TOTAL_REQUEST_DEADLINE_MS = 10000


class QtReleaseClient(QObject):
    """Own one bounded, abortable release check on the Qt event loop."""

    finished = Signal(object, object)

    def __init__(self, *, network_manager=None, parent=None):
        super().__init__(parent)
        self._manager = network_manager or QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_deadline)
        self._installed_version: str | None = None
        self._page = 0
        self._releases: list[Release] = []
        self._active = False

    @property
    def active(self) -> bool:
        """Whether a release request is currently in progress."""
        return self._active

    def start(self, installed_version: str) -> bool:
        """Start a check, returning false if another check is active."""
        if self._active:
            return False
        self._active = True
        self._installed_version = installed_version
        self._page = 0
        self._releases = []
        self._timer.start(TOTAL_REQUEST_DEADLINE_MS)
        self._request_next_page()
        return True

    def cancel(self) -> None:
        """Cancel without emitting a result or leaving queued follow-up work."""
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        reply = self._reply
        self._reply = None
        if reply is not None:
            reply.abort()

    def _request_next_page(self) -> None:
        self._page += 1
        url = QUrl(GITHUB_RELEASES_API)
        query = QUrlQuery()
        query.addQueryItem("per_page", str(RELEASE_PAGE_SIZE))
        query.addQueryItem("page", str(self._page))
        url.setQuery(query)
        request = QNetworkRequest(url)
        request.setRawHeader(
            QByteArray(b"Accept"), QByteArray(b"application/vnd.github+json")
        )
        request.setRawHeader(
            QByteArray(b"User-Agent"),
            QByteArray(b"RhinoSurfaceMapper-UpdateChecker"),
        )
        request.setRawHeader(
            QByteArray(b"X-GitHub-Api-Version"), QByteArray(b"2022-11-28")
        )
        reply = self._manager.get(request)
        self._reply = reply
        reply.finished.connect(lambda: self._on_reply_finished(reply))

    def _on_reply_finished(self, reply: QNetworkReply) -> None:
        if not self._active or reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status in (403, 429):
            reply.deleteLater()
            self._complete(None, "GitHub rate limit reached. Please try again later.")
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            message = reply.errorString() or (
                "Could not connect to GitHub to check for updates."
            )
            reply.deleteLater()
            self._complete(None, message)
            return
        if status is not None and not 200 <= int(status) < 300:
            reply.deleteLater()
            self._complete(None, "GitHub could not provide release information.")
            return

        try:
            payload = json.loads(bytes(reply.readAll()))
            page_releases = parse_release_entries(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ReleaseCheckError) as exc:
            reply.deleteLater()
            self._complete(None, str(exc) or "GitHub returned an invalid response.")
            return
        reply.deleteLater()
        self._releases.extend(page_releases)
        if len(payload) < RELEASE_PAGE_SIZE:
            self._complete_success()
        elif self._page >= MAX_RELEASE_PAGES:
            self._complete(
                None,
                "GitHub has more releases than the checker can safely inspect.",
            )
        else:
            self._request_next_page()

    def _on_deadline(self) -> None:
        if not self._active:
            return
        reply = self._reply
        self._reply = None
        if reply is not None:
            reply.abort()
        self._complete(None, "The GitHub update check timed out.")

    def _complete_success(self) -> None:
        try:
            release = newest_release(
                self._releases, self._installed_version or ""
            )
        except ValueError as exc:
            self._complete(None, str(exc))
        else:
            self._complete(release, None)

    def _complete(self, release: Release | None, error: str | None) -> None:
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        self._reply = None
        self.finished.emit(release, error)
