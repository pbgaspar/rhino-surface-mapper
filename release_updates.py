"""GitHub Releases retrieval and Semantic Versioning selection."""

from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering
import re
from urllib.parse import urlsplit

import requests

from app_version import GITHUB_RELEASES_API


_VERSION_PATTERN = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_LEGACY_VERSIONS = {
    "beta-1": "0.1.0-beta.1",
    "beta-2": "0.1.0-beta.2",
}
RELEASE_PAGE_SIZE = 100
MAX_RELEASE_PAGES = 2
_REQUEST_TIMEOUT = (2.0, 3.0)
_RELEASE_URL_PREFIX = (
    "https://github.com/pbgaspar/rhino-surface-mapper/releases/tag/"
)


class ReleaseCheckError(RuntimeError):
    """Raised when GitHub cannot provide a complete, valid release listing."""


@total_ordering
@dataclass(frozen=True)
class SemanticVersion:
    """Parsed SemVer precedence components; build metadata does not affect order."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] = ()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if core != other_core:
            return core < other_core
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if isinstance(left, int) and isinstance(right, str):
                return True
            if isinstance(left, str) and isinstance(right, int):
                return False
            return left < right
        return len(self.prerelease) < len(other.prerelease)

    def __str__(self) -> str:
        core = f"{self.major}.{self.minor}.{self.patch}"
        if not self.prerelease:
            return core
        return f"{core}-" + ".".join(map(str, self.prerelease))


@dataclass(frozen=True)
class Release:
    """Validated published release information used by the updater UI."""

    name: str
    tag_name: str
    version: SemanticVersion
    url: str


def parse_version(value: object) -> SemanticVersion | None:
    """Parse SemVer tags and the two published legacy beta tags."""
    if not isinstance(value, str):
        return None
    tag = value.strip()
    mapped = _LEGACY_VERSIONS.get(tag.casefold(), tag)
    match = _VERSION_PATTERN.fullmatch(mapped)
    if match is None:
        return None

    prerelease_text = match.group(4)
    prerelease: list[int | str] = []
    if prerelease_text:
        for identifier in prerelease_text.split("."):
            if identifier.isdigit():
                if len(identifier) > 1 and identifier.startswith("0"):
                    return None
                try:
                    prerelease.append(int(identifier))
                except ValueError:
                    return None
            else:
                prerelease.append(identifier)
    try:
        major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    except ValueError:
        return None
    return SemanticVersion(major, minor, patch, tuple(prerelease))


def valid_release_url(value: object) -> str | None:
    """Return an approved repository release URL, rejecting other destinations."""
    if not isinstance(value, str) or not value.startswith(_RELEASE_URL_PREFIX):
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or not parsed.path.startswith(
                "/pbgaspar/rhino-surface-mapper/releases/tag/"
            ) or parsed.query or parsed.fragment):
        return None
    return value


def parse_release_entries(payload: object) -> list[Release]:
    """Validate GitHub release records and ignore drafts or malformed entries."""
    if not isinstance(payload, list):
        raise ReleaseCheckError("GitHub returned an invalid releases response.")

    releases: list[Release] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if type(item.get("draft")) is not bool or type(item.get("prerelease")) is not bool:
            continue
        if item["draft"]:
            continue
        tag_name = item.get("tag_name")
        version = parse_version(tag_name)
        url = valid_release_url(item.get("html_url"))
        if version is None or url is None:
            continue
        name = item.get("name")
        releases.append(Release(
            name=name if isinstance(name, str) and name.strip() else tag_name,
            tag_name=tag_name,
            version=version,
            url=url,
        ))
    return releases


def fetch_releases(*, get=None) -> list[Release]:
    """Fetch a bounded number of GitHub release pages and validate the results."""
    request = requests.get if get is None else get
    releases: list[Release] = []
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RhinoSurfaceMapper-UpdateChecker",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    for page in range(1, MAX_RELEASE_PAGES + 1):
        try:
            response = request(
                GITHUB_RELEASES_API,
                params={"per_page": RELEASE_PAGE_SIZE, "page": page},
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ReleaseCheckError(_http_error_message(exc)) from exc
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise ReleaseCheckError(
                "GitHub returned invalid JSON for its releases."
            ) from exc

        page_releases = parse_release_entries(payload)
        releases.extend(page_releases)
        if len(payload) < RELEASE_PAGE_SIZE:
            return releases
    raise ReleaseCheckError(
        "GitHub has more releases than the checker can safely inspect."
    )


def _http_error_message(error: requests.RequestException) -> str:
    response = getattr(error, "response", None)
    if response is not None and response.status_code in (403, 429):
        return "GitHub rate limit reached. Please try again later."
    if isinstance(error, requests.Timeout):
        return "The GitHub update check timed out."
    if isinstance(error, requests.HTTPError):
        return "GitHub could not provide release information."
    return "Could not connect to GitHub to check for updates."


def newest_release(
    releases: list[Release], installed_version: str
) -> Release | None:
    """Return the greatest valid release newer than the installed version."""
    installed = parse_version(installed_version)
    if installed is None:
        raise ValueError(f"Invalid installed version: {installed_version!r}")
    newer = [release for release in releases if release.version > installed]
    return max(newer, key=lambda release: release.version, default=None)
