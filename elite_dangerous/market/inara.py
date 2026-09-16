"""Parsing for the mature INARA all-commodities summary table."""

from html.parser import HTMLParser
import re

from .commodities import canonical_commodity_name
from .models import (
    CommodityPriceSummary,
    CommoditySummaryResult,
    MarketIssue,
    _commodity_key,
)


class InaraParseError(ValueError):
    """The supplied document is not a usable INARA commodity-list table."""


class _InaraTableParser(HTMLParser):
    """Collect table rows and cells without interpreting their contents."""

    def __init__(self) -> None:
        super().__init__()
        self._table_depth = 0
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self._table_rows: list[tuple[str, ...]] = []
        self.tables: list[tuple[tuple[str, ...], ...]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            if self._table_depth == 0:
                self._table_rows = []
            self._table_depth += 1
        elif self._table_depth and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th") and self._in_cell:
            self._row.append(" ".join(" ".join(self._cell_parts).split()))
            self._cell_parts = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._row:
                self._table_rows.append(tuple(self._row))
            self._row = []
            self._in_row = False
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self.tables.append(tuple(self._table_rows))
                self._table_rows = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


def _parse_credit_value(text: str) -> int | None:
    """Parse integer credit text in the grouping forms used by INARA."""
    match = re.fullmatch(
        r"\s*([0-9]+(?:[\s,.'’][0-9]+)*)\s*(?:Cr)?\s*",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None

    return int(re.sub(r"[^0-9]", "", match.group(1)))


def parse_inara_summaries(
    document: str,
    requested: tuple[str, ...],
) -> CommoditySummaryResult:
    """Map an INARA all-commodities table document to requested summaries.

    Rows use the mature experiment's columns: commodity at index 0, average
    sell at index 1, and maximum sell at index 4. Malformed relevant rows are
    reported as recoverable issues while usable rows remain available.
    """
    if not isinstance(document, str) or not document.strip():
        raise InaraParseError("INARA document must be non-empty text")

    parser = _InaraTableParser()
    parser.feed(document)
    parser.close()

    requested_by_key: dict[str, str] = {}
    for name in requested:
        requested_by_key.setdefault(_commodity_key(name), name)

    rows = tuple(row for table in parser.tables for row in table)
    has_supported_row = any(
        len(row) >= 5
        and row[0]
        and (
            canonical_commodity_name(row[0]) is not None
            or _commodity_key(row[0]) in requested_by_key
        )
        and (
            _parse_credit_value(row[1]) is not None
            or _parse_credit_value(row[4]) is not None
        )
        for row in rows
    )
    if not has_supported_row:
        raise InaraParseError(
            "INARA document has no supported commodity table rows"
        )

    summaries_by_key: dict[str, CommodityPriceSummary] = {}
    issues: list[MarketIssue] = []
    for row in rows:
        if not row:
            continue

        raw_name = row[0]
        key = _commodity_key(raw_name)
        if key not in requested_by_key:
            continue

        canonical = canonical_commodity_name(raw_name)
        commodity = canonical if canonical is not None else raw_name
        if len(row) < 5:
            issues.append(
                MarketIssue("INARA", f"Incomplete market row for {commodity}")
            )
            continue

        average_sell = _parse_credit_value(row[1])
        maximum_sell = _parse_credit_value(row[4])
        if average_sell is None and maximum_sell is None:
            issues.append(
                MarketIssue("INARA", f"No usable prices for {commodity}")
            )
            continue
        if average_sell is None or maximum_sell is None:
            issues.append(
                MarketIssue("INARA", f"One price is unavailable for {commodity}")
            )

        summaries_by_key[key] = CommodityPriceSummary(
            commodity=commodity,
            average_sell=average_sell,
            maximum_sell=maximum_sell,
            total_demand=None,
        )

    return CommoditySummaryResult(
        requested=requested,
        summaries=tuple(summaries_by_key.values()),
        issues=tuple(issues),
    )
