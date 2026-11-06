from datetime import datetime, timedelta, timezone
import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest

from app_version import APP_VERSION
from release_updates import parse_release_entries, parse_version
from settings_persistence import load_preferences
from update_controller import (
    DISMISSED_VERSION_KEY,
    LAST_CHECK_KEY,
    NOTICE_NAME_KEY,
    NOTICE_TAG_KEY,
    NOTICE_URL_KEY,
    NOTICE_VERSION_KEY,
    ManualCheckResult,
    UpdateController,
    should_check_automatically,
)


_APP = None


def _application():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture(autouse=True)
def qt_application():
    return _application()
_RELEASE = parse_release_entries([{
    "tag_name": "v0.1.0-beta.4",
    "name": "Beta 4",
    "draft": False,
    "prerelease": True,
    "html_url": (
        "https://github.com/pbgaspar/rhino-surface-mapper/releases/tag/"
        "v0.1.0-beta.4"
    ),
}])[0]


def wait_until(predicate, timeout=5.0):
    _application()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return predicate()


def _entry(tag="v0.1.0-beta.4"):
    name = "Beta " + tag.rsplit(".", 1)[-1]
    return {
        "tag_name": tag,
        "name": name,
        "draft": False,
        "prerelease": True,
        "html_url": (
            "https://github.com/pbgaspar/rhino-surface-mapper/releases/tag/"
            + tag
        ),
    }


class _FakeReply(QObject):
    finished = Signal()

    def __init__(self, response, parent=None):
        super().__init__(parent)
        self.response = response
        self.aborted = False

    def attribute(self, attribute):
        if attribute == QNetworkRequest.Attribute.HttpStatusCodeAttribute:
            return self.response.get("status", 200)
        return None

    def error(self):
        return self.response.get("error", QNetworkReply.NetworkError.NoError)

    def errorString(self):
        return self.response.get("error_string", "")

    def readAll(self):
        if "body" in self.response:
            return self.response["body"]
        return json.dumps(self.response.get("payload", [])).encode("utf-8")

    def abort(self):
        self.aborted = True
        self.finished.emit()

    def deleteLater(self):
        pass

    def complete(self):
        self.finished.emit()


class _FakeNetworkManager(QObject):
    def __init__(self, responses, parent=None):
        super().__init__(parent)
        self.responses = list(responses)
        self.replies = []
        self.requests = []

    def get(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        reply = _FakeReply(response, self)
        self.replies.append(reply)
        delay = response.get("delay_ms", 0)
        if delay is not None:
            QTimer.singleShot(delay, reply.complete)
        return reply


def network_manager(*payloads):
    return _FakeNetworkManager([{"payload": payload} for payload in payloads])


def test_first_run_and_interval_boundaries_and_future_timestamp():
    now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
    assert should_check_automatically({}, now=now)
    assert should_check_automatically({LAST_CHECK_KEY: "invalid"}, now=now)
    assert should_check_automatically({
        LAST_CHECK_KEY: (now + timedelta(minutes=1)).isoformat(),
    }, now=now)
    assert not should_check_automatically({
        LAST_CHECK_KEY: (now - timedelta(hours=23, minutes=59)).isoformat(),
    }, now=now)
    assert should_check_automatically({
        LAST_CHECK_KEY: (now - timedelta(hours=24)).isoformat(),
    }, now=now)


def test_automatic_check_records_success_and_preserves_other_preferences(tmp_path):
    now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
    preferences = {"theme": "Dark", "scanner_group": 4}
    controller = UpdateController(
        preferences, tmp_path / "options.json", network_manager=network_manager(
            [_entry()]
        ), clock=lambda: now,
    )
    changed = []
    controller.notification_changed.connect(changed.append)

    assert controller.start_automatic_check()
    assert wait_until(lambda: not controller.checking)

    saved = load_preferences(tmp_path / "options.json")
    assert saved["theme"] == "Dark"
    assert saved["scanner_group"] == 4
    assert saved[LAST_CHECK_KEY] == now.isoformat()
    assert saved[NOTICE_VERSION_KEY] == "0.1.0-beta.4"
    assert saved[NOTICE_TAG_KEY] == "v0.1.0-beta.4"
    assert changed == [_RELEASE]
    assert not controller.start_automatic_check()
    assert controller.shutdown()


def test_failed_check_does_not_advance_success_timestamp(tmp_path):
    preferences = {"theme": "Light"}
    manager = _FakeNetworkManager([{
        "payload": [],
        "error": QNetworkReply.NetworkError.HostNotFoundError,
        "error_string": "offline",
    }])
    controller = UpdateController(
        preferences, tmp_path / "options.json", network_manager=manager
    )
    assert controller.start_automatic_check()
    assert wait_until(lambda: not controller.checking)
    assert LAST_CHECK_KEY not in preferences
    assert preferences["theme"] == "Light"
    assert not (tmp_path / "options.json").exists()
    assert controller.shutdown()


def test_notification_restores_valid_state_and_rejects_invalid_or_old_state(tmp_path):
    state = {
        NOTICE_VERSION_KEY: "0.1.0-beta.4",
        NOTICE_TAG_KEY: "v0.1.0-beta.4",
        NOTICE_NAME_KEY: "Beta 4",
        NOTICE_URL_KEY: _RELEASE.url,
    }
    controller = UpdateController(state, tmp_path / "options.json")
    assert controller.notification == _RELEASE
    controller.shutdown()

    old_state = dict(state, **{NOTICE_VERSION_KEY: "beta-2"})
    older = UpdateController(old_state, tmp_path / "other.json")
    assert older.notification is None
    assert NOTICE_VERSION_KEY not in old_state
    older.shutdown()

    invalid_state = dict(state, **{NOTICE_URL_KEY: "https://evil.example/"})
    invalid = UpdateController(invalid_state, tmp_path / "invalid.json")
    assert invalid.notification is None
    assert NOTICE_URL_KEY not in invalid_state
    invalid.shutdown()


def test_dismissal_persists_across_sessions_and_same_release_does_not_return(tmp_path):
    path = tmp_path / "options.json"
    preferences = {
        "theme": "Dark",
        NOTICE_VERSION_KEY: str(_RELEASE.version),
        NOTICE_TAG_KEY: _RELEASE.tag_name,
        NOTICE_NAME_KEY: _RELEASE.name,
        NOTICE_URL_KEY: _RELEASE.url,
    }
    first = UpdateController(preferences, path)
    assert first.notification == _RELEASE
    first.dismiss_notification()
    assert first.shutdown()

    restored_preferences = load_preferences(path)
    assert restored_preferences["theme"] == "Dark"
    assert restored_preferences[DISMISSED_VERSION_KEY] == "0.1.0-beta.4"
    assert NOTICE_VERSION_KEY not in restored_preferences
    second = UpdateController(
        restored_preferences, path, network_manager=network_manager([_entry()])
    )
    assert second.notification is None
    second.check_for_updates(manual=False)
    assert wait_until(lambda: not second.checking)
    assert second.notification is None
    assert NOTICE_VERSION_KEY not in restored_preferences
    assert second.shutdown()


def test_newer_release_after_dismissal_triggers_a_new_notice(tmp_path):
    newer = parse_release_entries([{
        "tag_name": "v0.1.0-beta.5",
        "name": "Beta 5",
        "draft": False,
        "prerelease": True,
        "html_url": (
            "https://github.com/pbgaspar/rhino-surface-mapper/releases/tag/"
            "v0.1.0-beta.5"
        ),
    }])[0]
    preferences = {DISMISSED_VERSION_KEY: "0.1.0-beta.4"}
    controller = UpdateController(
        preferences, tmp_path / "options.json", network_manager=network_manager([
            _entry("v0.1.0-beta.5")
        ])
    )
    changed = []
    controller.notification_changed.connect(changed.append)
    assert controller.start_automatic_check()
    assert wait_until(lambda: not controller.checking)
    assert controller.notification == newer
    assert changed == [newer]
    assert preferences[DISMISSED_VERSION_KEY] == "0.1.0-beta.4"
    assert preferences[NOTICE_VERSION_KEY] == "0.1.0-beta.5"
    assert preferences[NOTICE_TAG_KEY] == "v0.1.0-beta.5"
    assert controller.shutdown()


def test_manual_check_reports_a_dismissed_release_without_restoring_notice(tmp_path):
    preferences = {
        DISMISSED_VERSION_KEY: "0.1.0-beta.4",
        LAST_CHECK_KEY: datetime.now(timezone.utc).isoformat(),
    }
    controller = UpdateController(
        preferences, tmp_path / "options.json", network_manager=network_manager([
            _entry()
        ])
    )
    results = []
    notifications = []
    controller.manual_result.connect(results.append)
    controller.notification_changed.connect(notifications.append)

    assert controller.check_for_updates(manual=True)
    assert wait_until(lambda: not controller.checking)

    assert len(results) == 1
    assert isinstance(results[0], ManualCheckResult)
    assert results[0].release == _RELEASE
    assert results[0].error is None
    assert controller.notification is None
    assert notifications == []
    assert preferences[DISMISSED_VERSION_KEY] == "0.1.0-beta.4"
    assert NOTICE_VERSION_KEY not in preferences
    assert preferences[LAST_CHECK_KEY]
    assert controller.shutdown()


def test_manual_check_joins_automatic_request_and_receives_result(tmp_path):
    manager = _FakeNetworkManager([{"payload": [_entry()], "delay_ms": None}])
    controller = UpdateController(
        {}, tmp_path / "options.json", network_manager=manager
    )
    results = []
    controller.manual_result.connect(results.append)
    assert controller.check_for_updates(manual=False)
    assert len(manager.replies) == 1
    assert controller.check_for_updates(manual=True)
    assert len(manager.replies) == 1
    manager.replies[0].complete()
    assert wait_until(lambda: not controller.checking)
    assert len(results) == 1
    assert results[0].release == _RELEASE
    assert controller.notification == _RELEASE
    assert controller.shutdown()


def test_shutdown_aborts_active_request_without_stale_callbacks(tmp_path):
    manager = _FakeNetworkManager([{"payload": [_entry()], "delay_ms": None}])
    controller = UpdateController(
        {}, tmp_path / "options.json", network_manager=manager
    )
    results = []
    notifications = []
    controller.manual_result.connect(results.append)
    controller.notification_changed.connect(notifications.append)
    assert controller.check_for_updates(manual=False)
    assert controller.check_for_updates(manual=True)
    reply = manager.replies[0]
    assert controller.shutdown()
    assert reply.aborted
    reply.complete()
    QApplication.processEvents()
    assert not controller.checking
    assert results == []
    assert notifications == []
    assert LAST_CHECK_KEY not in controller.preferences


def test_automatic_check_joins_manual_request_and_activates_notice(tmp_path):
    manager = _FakeNetworkManager([{"payload": [_entry()], "delay_ms": None}])
    controller = UpdateController(
        {}, tmp_path / "options.json", network_manager=manager
    )
    results = []
    controller.manual_result.connect(results.append)
    assert controller.check_for_updates(manual=True)
    assert controller.check_for_updates(manual=False)
    assert len(manager.replies) == 1
    manager.replies[0].complete()
    assert wait_until(lambda: not controller.checking)
    assert len(results) == 1 and results[0].release == _RELEASE
    assert controller.notification == _RELEASE
    assert controller.shutdown()


def test_total_deadline_cancels_request_without_success_timestamp(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("release_update_client.TOTAL_REQUEST_DEADLINE_MS", 25)
    manager = _FakeNetworkManager([{"payload": [], "delay_ms": None}])
    controller = UpdateController(
        {}, tmp_path / "options.json", network_manager=manager
    )
    results = []
    controller.manual_result.connect(results.append)
    assert controller.check_for_updates(manual=True)
    assert wait_until(lambda: not controller.checking)
    assert manager.replies[0].aborted
    assert len(results) == 1
    assert "timed out" in results[0].error.lower()
    assert LAST_CHECK_KEY not in controller.preferences
    assert controller.shutdown()


def test_pagination_selects_newest_release_and_ignores_malformed_entries(tmp_path):
    manager = _FakeNetworkManager([
        {"payload": [None] * 100},
        {"payload": [_entry("v0.1.0-beta.5")]},
    ])
    controller = UpdateController(
        {}, tmp_path / "options.json", network_manager=manager
    )
    results = []
    controller.manual_result.connect(results.append)
    assert controller.check_for_updates(manual=True)
    assert wait_until(lambda: not controller.checking)
    assert len(manager.requests) == 2
    assert "page=1" in manager.requests[0].url().query()
    assert "page=2" in manager.requests[1].url().query()
    assert results[0].release.tag_name == "v0.1.0-beta.5"
    assert results[0].error is None
    assert controller.shutdown()


def test_malformed_network_response_is_reported_without_success_timestamp(tmp_path):
    manager = _FakeNetworkManager([{"body": b"not-json"}])
    controller = UpdateController(
        {}, tmp_path / "options.json", network_manager=manager
    )
    results = []
    controller.manual_result.connect(results.append)
    assert controller.check_for_updates(manual=True)
    assert wait_until(lambda: not controller.checking)
    assert results[0].error
    assert LAST_CHECK_KEY not in controller.preferences
    assert controller.shutdown()


def test_total_deadline_covers_paginated_request(tmp_path, monkeypatch):
    monkeypatch.setattr("release_update_client.TOTAL_REQUEST_DEADLINE_MS", 25)
    manager = _FakeNetworkManager([
        {"payload": [None] * 100},
        {"payload": [], "delay_ms": None},
    ])
    controller = UpdateController(
        {}, tmp_path / "options.json", network_manager=manager
    )
    results = []
    controller.manual_result.connect(results.append)
    assert controller.check_for_updates(manual=True)
    assert wait_until(lambda: len(manager.replies) == 2)
    assert wait_until(lambda: not controller.checking)
    assert manager.replies[1].aborted
    assert "timed out" in results[0].error.lower()
    assert LAST_CHECK_KEY not in controller.preferences
    assert controller.shutdown()


def test_manual_up_to_date_and_error_results_are_reported(tmp_path):
    controller = UpdateController(
        {}, tmp_path / "options.json", network_manager=network_manager([])
    )
    results = []
    controller.manual_result.connect(results.append)
    controller.check_for_updates(manual=True)
    assert wait_until(lambda: not controller.checking)
    assert results[-1].release is None and results[-1].error is None
    controller.shutdown()

    failed_manager = _FakeNetworkManager([{
        "payload": [],
        "error": QNetworkReply.NetworkError.HostNotFoundError,
        "error_string": "offline",
    }])
    failed = UpdateController(
        {}, tmp_path / "failed.json", network_manager=failed_manager
    )
    failed_results = []
    failed.manual_result.connect(failed_results.append)
    failed.check_for_updates(manual=True)
    assert wait_until(lambda: not failed.checking)
    assert failed_results[-1].error == "offline"
    assert LAST_CHECK_KEY not in failed.preferences
    assert failed.shutdown()


def test_invalid_installed_version_is_rejected():
    assert parse_version("not-a-version") is None
    assert APP_VERSION == "0.1.0-beta.3"
