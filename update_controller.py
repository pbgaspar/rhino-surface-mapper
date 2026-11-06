"""Coordinate asynchronous release checks and persistent update state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Callable

from PySide6.QtCore import QObject, Signal

from app_version import APP_VERSION
from release_updates import (
    Release,
    newest_release,
    parse_version,
    valid_release_url,
)
from release_update_client import QtReleaseClient
from settings_persistence import save_preferences


logger = logging.getLogger(__name__)
CHECK_INTERVAL = timedelta(hours=24)
LAST_CHECK_KEY = "update_last_successful_check"
DISMISSED_VERSION_KEY = "update_dismissed_version"
NOTICE_VERSION_KEY = "update_notice_version"
NOTICE_TAG_KEY = "update_notice_tag"
NOTICE_NAME_KEY = "update_notice_name"
NOTICE_URL_KEY = "update_notice_url"


@dataclass(frozen=True)
class ManualCheckResult:
    """Outcome shown in the main window after a user-requested check."""

    release: Release | None = None
    error: str | None = None


def should_check_automatically(
    preferences: dict[str, object],
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a successful check is absent, expired, or invalid."""
    stored = preferences.get(LAST_CHECK_KEY)
    if not isinstance(stored, str):
        return True
    try:
        last_check = datetime.fromisoformat(stored)
    except ValueError:
        return True
    if last_check.tzinfo is None or last_check.utcoffset() is None:
        return True
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("The current time must be timezone-aware.")
    if last_check > current:
        return True
    return current - last_check.astimezone(timezone.utc) >= CHECK_INTERVAL


def _restore_notification(
    preferences: dict[str, object], installed_version: str
) -> Release | None:
    version_text = preferences.get(NOTICE_VERSION_KEY)
    tag_name = preferences.get(NOTICE_TAG_KEY)
    url = valid_release_url(preferences.get(NOTICE_URL_KEY))
    if (not isinstance(version_text, str) or not isinstance(tag_name, str)
            or url is None):
        return None
    version = parse_version(version_text)
    tagged_version = parse_version(tag_name)
    installed = parse_version(installed_version)
    if (version is None or tagged_version != version or installed is None
            or version <= installed):
        return None
    dismissed = parse_version(preferences.get(DISMISSED_VERSION_KEY))
    if dismissed is not None and version <= dismissed:
        return None
    name = preferences.get(NOTICE_NAME_KEY)
    return Release(
        name=name if isinstance(name, str) and name.strip() else tag_name,
        tag_name=tag_name,
        version=version,
        url=url,
    )


class UpdateController(QObject):
    """Own release-check lifecycle and update state on the GUI thread."""

    notification_changed = Signal(object)
    manual_result = Signal(object)

    def __init__(
        self,
        preferences: dict[str, object],
        preferences_path,
        *,
        installed_version: str = APP_VERSION,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        network_manager=None,
        parent=None,
    ):
        super().__init__(parent)
        self.preferences = preferences
        self.preferences_path = preferences_path
        self.installed_version = installed_version
        self._clock = clock
        self._client = QtReleaseClient(network_manager=network_manager, parent=self)
        self._client.finished.connect(self._check_completed)
        self._checking = False
        self._manual_requested = False
        self._automatic_requested = False
        self._closing = False
        self.notification = _restore_notification(preferences, installed_version)
        if (self.notification is None
                and any(key in preferences for key in (
                    NOTICE_VERSION_KEY, NOTICE_TAG_KEY, NOTICE_NAME_KEY,
                    NOTICE_URL_KEY))):
            self._clear_notification_state()

    @property
    def checking(self) -> bool:
        """Return whether a release request is currently active."""
        return self._checking

    def start_automatic_check(self) -> bool:
        """Start the interval-based check when one is due."""
        if self._closing or not should_check_automatically(
                self.preferences, now=self._clock()):
            return False
        self.check_for_updates(manual=False)
        return True

    def check_for_updates(self, *, manual: bool) -> bool:
        """Start a check or join its result if another check is active."""
        if self._closing:
            return False
        if self._checking:
            self._manual_requested = self._manual_requested or manual
            self._automatic_requested = self._automatic_requested or not manual
            return True
        self._manual_requested = manual
        self._automatic_requested = not manual
        self._checking = True
        if not self._client.start(self.installed_version):
            self._checking = False
            self._manual_requested = False
            self._automatic_requested = False
            return False
        return True

    def dismiss_notification(self) -> None:
        """Persist dismissal of the currently visible automatic notice."""
        if self.notification is None:
            return
        self.preferences[DISMISSED_VERSION_KEY] = str(self.notification.version)
        self._clear_notification_state()
        self._save_preferences()
        self.notification_changed.emit(None)

    def shutdown(self) -> bool:
        """Cancel active network work before the owning window is destroyed."""
        self._closing = True
        self._checking = False
        self._manual_requested = False
        self._automatic_requested = False
        self._client.cancel()
        return True

    def _check_completed(self, release: Release | None, error: str | None) -> None:
        if self._closing:
            return
        manual = self._manual_requested
        automatic = self._automatic_requested
        self._manual_requested = False
        self._automatic_requested = False
        self._checking = False
        notification_to_emit = None
        if error is None:
            self.preferences[LAST_CHECK_KEY] = self._clock().astimezone(
                timezone.utc
            ).isoformat()
            if release is not None and automatic:
                dismissed = parse_version(
                    self.preferences.get(DISMISSED_VERSION_KEY)
                )
                if dismissed is None or release.version > dismissed:
                    self.preferences[NOTICE_VERSION_KEY] = str(release.version)
                    self.preferences[NOTICE_TAG_KEY] = release.tag_name
                    self.preferences[NOTICE_NAME_KEY] = release.name
                    self.preferences[NOTICE_URL_KEY] = release.url
                    self.notification = release
                    notification_to_emit = release
            self._save_preferences()
        if self._closing:
            return
        if notification_to_emit is not None:
            self.notification_changed.emit(notification_to_emit)
        if self._closing:
            return
        if manual:
            self.manual_result.emit(ManualCheckResult(release, error))

    def _clear_notification_state(self) -> None:
        self.preferences.pop(NOTICE_VERSION_KEY, None)
        self.preferences.pop(NOTICE_TAG_KEY, None)
        self.preferences.pop(NOTICE_NAME_KEY, None)
        self.preferences.pop(NOTICE_URL_KEY, None)
        self.notification = None

    def _save_preferences(self) -> None:
        try:
            save_preferences(self.preferences_path, self.preferences)
        except OSError:
            logger.exception("Could not persist update-check preferences")
