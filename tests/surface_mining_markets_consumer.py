"""Surface Mining Markets consumer for reusable market services.

Coordinates local Spansh markets and global INARA summaries, then presents
the best products and stations for a requested system.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIRECTORY.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from elite_dangerous.market import (  # noqa: E402
    CacheFormatError,
    classify_market_freshness,
    CommoditySummaryResult,
    InaraParseError,
    MarketDiagnostics,
    MarketIssue,
    MarketObservation,
    LandableBody,
    SpanshError,
    SURFACE_COMMODITIES,
    commodities_for_planet_types,
    fetch_commodity_markets,
    fetch_landable_bodies,
    filter_market_observations,
    is_carrier_name,
    load_summary_cache,
    parse_inara_summaries,
    rank_market_observations,
    planet_types_for_commodities,
    resolve_system,
    save_summary_cache,
)


INARA_COMMODITIES_URL = "https://inara.cz/elite/commodities-list/"
CACHE_FILENAME = "inara_summary_cache_v1.json"
CACHE_PATH = SCRIPT_DIRECTORY / CACHE_FILENAME
INARA_CACHE_MAX_AGE = timedelta(hours=1)
HEADLESS_TIMEOUT_SECONDS = 60

MIN_DEMAND = 100
TOP_PRODUCTS = 3
TOP_STATIONS = 3


def format_number(value: int | None) -> str:
    """Format a known integer, leaving unavailable values visibly unknown."""
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ")


def data_age(value: datetime | None, *, now: datetime | None = None) -> str:
    """Return a compact age for a UTC-aware market timestamp."""
    if value is None:
        return "?"
    if value.tzinfo is None or value.utcoffset() is None:
        return "?"

    current_time = datetime.now(timezone.utc) if now is None else now
    seconds = max(0, int((current_time - value.astimezone(timezone.utc)).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def find_headless_browser() -> Path | None:
    """Find an installed Chrome or Edge executable for the INARA page."""
    candidates = (
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/Edge/Application/msedge.exe",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def browser_page_diagnostics(html_text: str) -> bool:
    """Detect common browser challenge and unavailable-page responses."""
    lower_html = html_text[:200_000].casefold()
    challenge_markers = (
        "captcha",
        "challenge-platform",
        "cf-chl-",
        "just a moment",
        "verify you are human",
        "checking your browser",
        "enable javascript and cookies",
        "service unavailable",
    )
    return any(marker in lower_html for marker in challenge_markers)


def fetch_inara_html() -> str:
    """Acquire the INARA commodity page through an installed headless browser."""
    browser_path = find_headless_browser()
    if browser_path is None:
        raise RuntimeError("No installed Edge or Chrome browser was found.")

    temporary_profile = Path(tempfile.mkdtemp(prefix="inara-headless-"))
    command = [
        str(browser_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        f"--user-data-dir={temporary_profile}",
        "--virtual-time-budget=15000",
        "--dump-dom",
        INARA_COMMODITIES_URL,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=HEADLESS_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Browser exceeded the {HEADLESS_TIMEOUT_SECONDS}-second timeout."
        ) from exc
    finally:
        shutil.rmtree(temporary_profile, ignore_errors=True)

    html_text = result.stdout.decode("utf-8", errors="replace")
    has_commodity_content = bool(
        re.search(r"(?i)<table\b|\bhelium\b|\bplatinum\b|commodit", html_text)
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Browser exited with return code {result.returncode}."
        )
    if not html_text:
        raise RuntimeError("Browser returned no HTML.")
    if browser_page_diagnostics(html_text):
        raise RuntimeError("INARA returned a browser challenge or error page.")
    if not has_commodity_content:
        raise RuntimeError("Browser HTML does not appear to contain commodities.")
    return html_text


def query_system_markets(
    name: str,
    *,
    progress=print,
    diagnostics: MarketDiagnostics | None = None,
    timing: bool = False,
    non_current_markets: dict[str, dict[str, object]] | None = None,
) -> tuple[str, dict[str, tuple[MarketObservation, ...]], tuple[MarketIssue, ...], tuple[LandableBody, ...], int]:
    """Fetch all current surface commodities in one Spansh traversal."""
    started = perf_counter()

    def stage(label, operation):
        stage_started = perf_counter()
        if timing:
            progress(f"[+{stage_started - started:6.2f}s] {label}...")
        value = operation()
        if timing:
            progress(
                f"[+{perf_counter() - started:6.2f}s] {label} done "
                f"({perf_counter() - stage_started:.2f}s)"
            )
        return value

    system = stage("Resolve system", lambda: resolve_system(name))
    bodies = stage("Fetch landable bodies", lambda: fetch_landable_bodies(system))
    preparation_started = perf_counter()
    planet_types = tuple(body.canonical_planet_type for body in bodies)
    commodities = commodities_for_planet_types(planet_types)
    if timing:
        progress(
            f"[+{perf_counter() - started:6.2f}s] Prepare applicable commodities done "
            f"({perf_counter() - preparation_started:.2f}s) — {len(commodities)} commodities"
        )
    progress(
        f"Querying {len(commodities)} commodities in {system.name} "
        "with one Spansh market traversal..."
    )
    if not commodities:
        progress("No supported landable Surface Mining body types were found.")
        return system.name, {}, (), bodies, 0
    market_kwargs = {
        "exclude_station": is_carrier_name,
        "resolved_system": system,
    }
    if diagnostics is not None:
        market_kwargs["diagnostics"] = diagnostics
    results = stage(
        "Fetch local markets",
        lambda: fetch_commodity_markets(
            system.name,
            commodities,
            **market_kwargs,
        ),
    )

    observations_by_commodity: dict[str, tuple[MarketObservation, ...]] = {}
    issues: list[MarketIssue] = []
    seen_issues: set[MarketIssue] = set()
    exact_name = system.name
    for result in results:
        if result.observations:
            exact_name = result.observations[0].station.system_name
        current_observations = []
        for observation in result.observations:
            freshness = classify_market_freshness(observation)
            if freshness == "current":
                current_observations.append(observation)
            elif non_current_markets is not None:
                key = observation.station.market_id or observation.station.name
                entry = non_current_markets.setdefault(
                    key,
                    {"station": observation.station, "freshness": freshness},
                )
                entry.setdefault("commodities", set()).add(observation.commodity)

        eligible = filter_market_observations(
            current_observations,
            exclude_carriers=True,
            demand_greater_than=MIN_DEMAND,
            require_positive_sell_price=True,
        )
        ranked = rank_market_observations(eligible)
        if ranked:
            observations_by_commodity[result.requested_commodity] = ranked

        for issue in result.issues:
            if issue not in seen_issues:
                seen_issues.add(issue)
                issues.append(issue)

    progress(
        f"Spansh returned qualifying markets for "
        f"{len(observations_by_commodity)} commodities; "
        f"{len(issues)} distinct issue(s)."
    )
    return exact_name, observations_by_commodity, tuple(issues), bodies, len(commodities)


def load_or_refresh_inara(
    cache_path: Path = CACHE_PATH,
    *,
    now: datetime | None = None,
) -> tuple[CommoditySummaryResult | None, str, datetime | None, str | None]:
    """Use a fresh reusable cache or refresh, retaining a stale safe fallback."""
    requested = tuple(SURFACE_COMMODITIES)
    current_time = datetime.now(timezone.utc) if now is None else now
    cached = None
    cache_problem: str | None = None

    try:
        cached = load_summary_cache(cache_path, requested)
    except FileNotFoundError:
        cache_problem = "summary cache is missing"
    except (CacheFormatError, json.JSONDecodeError) as exc:
        cache_problem = f"summary cache is invalid: {exc}"
    except OSError as exc:
        cache_problem = f"summary cache could not be read: {exc}"

    if cached is not None and cached.is_fresh(INARA_CACHE_MAX_AGE, now=current_time):
        return cached.result, "fresh cache", cached.stored_at, None

    try:
        html_text = fetch_inara_html()
    except (OSError, RuntimeError) as exc:
        refresh_problem = f"INARA acquisition failed: {exc}"
        return _inara_fallback(cached, cache_problem, refresh_problem)

    try:
        refreshed = parse_inara_summaries(html_text, requested)
    except InaraParseError as exc:
        refresh_problem = f"INARA parsing failed: {exc}"
        return _inara_fallback(cached, cache_problem, refresh_problem)

    if not refreshed.is_complete or refreshed.issues:
        refresh_problem = (
            "INARA refresh was incomplete "
            f"({len(refreshed.missing)} missing, {len(refreshed.issues)} issue(s)); "
            "partial values were not used."
        )
        return _inara_fallback(cached, cache_problem, refresh_problem)

    try:
        save_summary_cache(cache_path, refreshed, stored_at=current_time)
    except (OSError, ValueError) as exc:
        if cached is not None:
            return (
                cached.result,
                "stale cache fallback",
                cached.stored_at,
                f"INARA refresh was valid but the cache could not be saved: {exc}",
            )
        return (
            refreshed,
            "refreshed, cache save failed",
            current_time,
            f"INARA values are usable for this run, but the cache could not be saved: {exc}",
        )
    return refreshed, "refreshed", current_time, None


def _inara_fallback(
    cached,
    cache_problem: str | None,
    refresh_problem: str,
) -> tuple[CommoditySummaryResult | None, str, datetime | None, str]:
    details = "; ".join(
        detail for detail in (cache_problem, refresh_problem) if detail
    )
    if cached is not None:
        return cached.result, "stale cache fallback", cached.stored_at, details
    return None, "unavailable", None, details


def select_top_products(
    results: dict[str, tuple[MarketObservation, ...]],
    limit: int = TOP_PRODUCTS,
) -> tuple[tuple[str, tuple[MarketObservation, ...]], ...]:
    """Select products by their best station using reusable ranking semantics."""
    if limit <= 0:
        return ()
    ordered_observations = rank_market_observations(
        observation
        for product_observations in results.values()
        for observation in product_observations
    )
    selected: list[tuple[str, tuple[MarketObservation, ...]]] = []
    seen_products: set[str] = set()
    for observation in ordered_observations:
        product = observation.commodity
        if product in seen_products or product not in results:
            continue
        seen_products.add(product)
        selected.append((product, results[product]))
        if len(selected) >= limit:
            break
    return tuple(selected)


def parse_product_count(value: str) -> int:
    """Parse a requested positive product count."""
    text = value.strip()
    if not text:
        return TOP_PRODUCTS
    if not text.isdecimal():
        raise ValueError("Enter a positive integer.")
    count = int(text)
    if count <= 0:
        raise ValueError("Enter a positive integer.")
    return count


def prompt_product_count(input_fn=None) -> int:
    """Prompt until the user supplies a positive product count."""
    if input_fn is None:
        input_fn = input
    while True:
        try:
            return parse_product_count(input_fn(f"Number of products [{TOP_PRODUCTS}]: "))
        except ValueError as exc:
            print(str(exc))


def _cache_label(status: str, stored_at: datetime | None) -> str:
    if stored_at is None:
        return f"INARA ({status})"
    age_seconds = max(
        0,
        int((datetime.now(timezone.utc) - stored_at).total_seconds()),
    )
    age_hours, remainder = divmod(age_seconds, 3600)
    return (
        f"INARA ({status}; stored {stored_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC, "
        f"{age_hours}h{remainder // 60:02d}m old)"
    )


def print_results(
    system_name: str,
    selected: tuple[tuple[str, tuple[MarketObservation, ...]], ...],
    summary_result: CommoditySummaryResult | None,
    cache_status: str,
    cache_time: datetime | None,
    cache_warning: str | None,
    issues: tuple[MarketIssue, ...],
    elapsed: float,
    *,
    applicable_commodity_count: int,
    bodies: tuple[LandableBody, ...],
    non_current_markets: dict[str, dict[str, object]] | None = None,
) -> None:
    """Present the selected local markets and available global summaries."""
    print()
    print("=" * 112)
    print(
        f"SURFACE MINING — {system_name.upper()} "
        f"| {applicable_commodity_count} PRODUCTS "
        f"| LOCAL DEMAND > {format_number(MIN_DEMAND)} t"
    )
    print("=" * 112)

    if cache_warning:
        print(f"INARA warning: {cache_warning}")
    if not selected:
        print("No products met the local market criteria.")

    summaries = (
        {summary.commodity: summary for summary in summary_result.summaries}
        if summary_result is not None
        else {}
    )
    source_label = _cache_label(cache_status, cache_time)
    for number, (product, stations) in enumerate(selected, 1):
        summary = summaries.get(product)
        print()
        print(f"{number}. {product.upper()}")
        compatible_types = planet_types_for_commodities((product,)).get(product, frozenset())
        body_names = [
            body.name[len(system_name) + 1:]
            if body.name.startswith(system_name + " ")
            and body.name[len(system_name) + 1:]
            else body.name
            for body in bodies
            if body.canonical_planet_type in compatible_types
        ]
        print(f"   Probably on: {', '.join(body_names) if body_names else 'no matching body identified'}")
        if summary is not None and (
            summary.average_sell is not None or summary.maximum_sell is not None
        ):
            print(
                f"   {source_label} — global average: "
                f"{format_number(summary.average_sell)} Cr/t | global maximum: "
                f"{format_number(summary.maximum_sell)} Cr/t"
            )
        else:
            print(f"   {source_label} — global prices unavailable.")

        headers = ["Station", "Sell (Cr/t)", "Demand (t)", "Pad", "Market UTC", "Age"]
        rows = [
            [
                observation.station.name,
                format_number(observation.sell_price),
                format_number(observation.demand),
                observation.station.max_landing_pad or "?",
                observation.market_updated_at.isoformat()
                if observation.market_updated_at is not None
                else "Unknown",
                data_age(observation.market_updated_at),
            ]
            for observation in stations[:TOP_STATIONS]
        ]
        widths = [
            max(len(header), max((len(str(row[i])) for row in rows), default=0))
            for i, header in enumerate(headers)
        ]
        print(
            "   "
            + " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
        )
        print("   " + "-+-".join("-" * width for width in widths))
        for row in rows:
            print("   " + " | ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))

    if summary_result is not None and summary_result.missing:
        print(
            f"INARA has no summary for {len(summary_result.missing)} requested product(s); "
            "those values remain unavailable."
        )
    if issues:
        print()
        print("Partial local result — station issues:")
        for issue in issues:
            print(f"  {issue.station_name}: {issue.message}")
    if non_current_markets:
        too_old = [item for item in non_current_markets.values() if item["freshness"] == "too_old"]
        age_unknown = [item for item in non_current_markets.values() if item["freshness"] == "age_unknown"]
        if too_old:
            print()
            print("Too old:")
            for item in too_old:
                station = item["station"]
                print(f"  {station.name} — market data older than 365 days")
        if age_unknown:
            print()
            print("Age unknown:")
            for item in age_unknown:
                print(f"  {item['station'].name}")
    print()
    print(f"{len(selected)} products shown; {len(issues)} distinct station issue(s).")
    print(f"Elapsed: {elapsed:.2f} s")


def main() -> int:
    """Run the interactive/argv consumer without import-time side effects."""
    system_name = (
        " ".join(sys.argv[1:]).strip()
        if len(sys.argv) > 1
        else input("System name: ").strip()
    )
    if not system_name:
        print("Enter a system name.")
        return 1

    product_count = (
        prompt_product_count()
        if len(sys.argv) == 1
        else TOP_PRODUCTS
    )

    started = perf_counter()
    diagnostics = MarketDiagnostics()
    non_current_markets: dict[str, dict[str, object]] = {}
    try:
        exact_name, local_results, issues, bodies, applicable_count = query_system_markets(
            system_name,
            diagnostics=diagnostics,
            timing=True,
            non_current_markets=non_current_markets,
        )
    except SpanshError as exc:
        print(f"Could not query the system: {exc}")
        return 1

    inara_started = perf_counter()
    print(f"[+{inara_started - started:6.2f}s] Load/refresh INARA...")
    summary_result, cache_status, cache_time, cache_warning = load_or_refresh_inara()
    print(
        f"[+{perf_counter() - started:6.2f}s] Load/refresh INARA done "
        f"({perf_counter() - inara_started:.2f}s) — {cache_status}"
    )
    selection_started = perf_counter()
    selected = select_top_products(local_results, limit=product_count)
    print(
        f"[+{perf_counter() - started:6.2f}s] Select Top-N done "
        f"({perf_counter() - selection_started:.2f}s)"
    )
    print(
        "             market diagnostics: "
        f"candidates: {diagnostics.market_candidates} | "
        f"carriers skipped: {diagnostics.carriers_excluded} | "
        f"invalid market id: {diagnostics.invalid_market_ids}"
    )
    if diagnostics.excluded_carrier_names:
        for station_name in diagnostics.excluded_carrier_names:
            print(f"               {station_name}")
    print(
        "             station requests: "
        f"{diagnostics.station_requests_attempted} | "
        f"successes: {diagnostics.station_requests_succeeded} | "
        f"failures: {diagnostics.station_requests_failed}"
    )
    print(
        "             station HTTP: "
        f"{diagnostics.station_http_elapsed:.2f}s | "
        f"system detail: {diagnostics.system_detail_elapsed:.2f}s"
    )
    print("             slowest:")
    for station_name, elapsed in diagnostics.slowest_station_requests:
        print(f"               {station_name} — {elapsed:.2f}s")
    render_started = perf_counter()
    print(f"[+{render_started - started:6.2f}s] Render results...")
    print_results(
        exact_name,
        selected,
        summary_result,
        cache_status,
        cache_time,
        cache_warning,
        issues,
        perf_counter() - started,
        applicable_commodity_count=applicable_count,
        bodies=bodies,
        non_current_markets=non_current_markets,
    )
    print(
        f"[+{perf_counter() - started:6.2f}s] Render results done "
        f"({perf_counter() - render_started:.2f}s)"
    )
    return 2 if issues else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nQuery cancelled.")
        raise SystemExit(130)
