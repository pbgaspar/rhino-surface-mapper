from unittest.mock import Mock

import pytest
import requests

from app_version import APP_VERSION, GITHUB_RELEASES_API
from release_updates import (
    ReleaseCheckError,
    fetch_releases,
    newest_release,
    parse_release_entries,
    parse_version,
    valid_release_url,
)


RELEASE_URL = (
    "https://github.com/pbgaspar/rhino-surface-mapper/releases/tag/"
)


def entry(tag, *, draft=False, prerelease=False, url=None, name=None):
    return {
        "tag_name": tag,
        "name": name or tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": url or RELEASE_URL + tag,
    }


@pytest.mark.parametrize(("tag", "expected"), [
    ("beta-1", "0.1.0-beta.1"),
    ("beta-2", "0.1.0-beta.2"),
    ("BETA-2", "0.1.0-beta.2"),
    ("v0.1.0-beta.3", "0.1.0-beta.3"),
])
def test_parse_semver_and_historical_beta_tags(tag, expected):
    assert str(parse_version(tag)) == expected


def test_current_development_version_is_the_canonical_version():
    assert APP_VERSION == "0.1.0-beta.3"
    assert str(parse_version(APP_VERSION)) == APP_VERSION


@pytest.mark.parametrize(("older", "newer"), [
    ("0.1.0-beta.9", "0.1.0-beta.10"),
    ("0.1.0-beta.3", "0.1.0-beta.4"),
    ("0.1.0-beta.3", "0.1.0"),
    ("0.9.9", "0.10.0"),
    ("1.0.0-alpha", "1.0.0-alpha.1"),
    ("1.0.0-alpha.1", "1.0.0-alpha.beta"),
    ("1.0.0-rc.1", "1.0.0"),
])
def test_semver_precedence(older, newer):
    assert parse_version(older) < parse_version(newer)


@pytest.mark.parametrize("tag", [
    "beta-3", "release-1", "1.2", "01.2.3", "1.2.3-01", "1.2.3-",
    "1.2.3+build..bad", "",
])
def test_invalid_or_nonstandard_tags_are_rejected(tag):
    assert parse_version(tag) is None


def test_version_with_integer_too_large_for_runtime_is_ignored():
    assert parse_version("1.2.3-beta." + "9" * 5000) is None


def test_build_metadata_does_not_change_semver_precedence():
    assert parse_version("1.2.3+build.1") == parse_version("1.2.3+build.2")


def test_release_entries_keep_beta2_even_when_github_does_not_mark_prerelease():
    releases = parse_release_entries([
        entry("beta-1", prerelease=True),
        entry("beta-2", prerelease=False),
    ])
    assert [str(release.version) for release in releases] == [
        "0.1.0-beta.1", "0.1.0-beta.2",
    ]


def test_drafts_malformed_entries_and_untrusted_urls_are_ignored():
    releases = parse_release_entries([
        entry("v0.1.0-beta.4", draft=True),
        entry("not-semver"),
        entry("v0.1.0-beta.5", url="https://evil.example/release"),
        {"tag_name": "v0.1.0-beta.6", "draft": False},
        "not an object",
    ])
    assert releases == []
    assert valid_release_url(
        RELEASE_URL + "v0.1.0-beta.4"
    ) == RELEASE_URL + "v0.1.0-beta.4"
    assert valid_release_url("https://github.com.evil.example/release") is None


def test_newest_release_selects_greatest_applicable_version_not_first():
    releases = parse_release_entries([
        entry("v0.1.0-beta.5", prerelease=True),
        entry("v0.1.0-beta.4", prerelease=True),
        entry("beta-2"),
        entry("v0.1.0"),
    ])
    selected = newest_release(releases, APP_VERSION)
    assert selected is not None
    assert selected.tag_name == "v0.1.0"


def test_newest_release_returns_none_when_no_release_is_newer():
    releases = parse_release_entries([entry("beta-1"), entry("beta-2")])
    assert newest_release(releases, APP_VERSION) is None


def test_fetch_releases_uses_github_api_and_explicit_timeouts():
    response = Mock()
    response.json.return_value = [entry("beta-2")]
    get = Mock(return_value=response)

    releases = fetch_releases(get=get)

    assert len(releases) == 1
    get.assert_called_once()
    assert get.call_args.args == (GITHUB_RELEASES_API,)
    assert get.call_args.kwargs["params"] == {"per_page": 100, "page": 1}
    assert get.call_args.kwargs["timeout"] == (2.0, 3.0)
    response.raise_for_status.assert_called_once()


def test_fetch_releases_paginates_only_within_the_configured_bound():
    full_page = [None] * 100
    response_full = Mock()
    response_full.json.return_value = full_page
    response_empty = Mock()
    response_empty.json.return_value = []
    get = Mock(side_effect=[response_full, response_empty])

    assert fetch_releases(get=get) == []
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["params"]["page"] == 2


def test_fetch_releases_fails_if_pagination_bound_is_exhausted():
    response = Mock()
    response.json.return_value = [None] * 100
    get = Mock(return_value=response)
    with pytest.raises(ReleaseCheckError, match="safely inspect"):
        fetch_releases(get=get)
    assert get.call_count == 2


def test_fetch_releases_reports_timeout_and_rate_limit_errors():
    get = Mock(side_effect=requests.Timeout())
    with pytest.raises(ReleaseCheckError, match="timed out"):
        fetch_releases(get=get)

    response = Mock(status_code=403)
    get = Mock(side_effect=requests.HTTPError("forbidden", response=response))
    with pytest.raises(ReleaseCheckError, match="rate limit"):
        fetch_releases(get=get)


def test_fetch_releases_reports_http_and_json_errors():
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError(
        "server error", response=Mock(status_code=500)
    )
    with pytest.raises(ReleaseCheckError, match="could not provide"):
        fetch_releases(get=Mock(return_value=response))

    response = Mock()
    response.json.side_effect = ValueError("bad json")
    with pytest.raises(ReleaseCheckError, match="invalid JSON"):
        fetch_releases(get=Mock(return_value=response))


def test_fetch_releases_rejects_wrong_payload_shape():
    response = Mock()
    response.json.return_value = {"message": "not a releases list"}
    with pytest.raises(ReleaseCheckError, match="invalid releases response"):
        fetch_releases(get=Mock(return_value=response))
