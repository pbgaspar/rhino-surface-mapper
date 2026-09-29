"""Surface mining product data and name normalization."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
import unicodedata


CATALOGUE_PATH = Path(__file__).with_name("SURFACE_MINING_COMMODITIES.json")
_EXPECTED_COMMODITY_COUNT = 37
_ALLOWED_PLANET_TYPES = frozenset(
    {
        "High metal content",
        "Metal Rich",
        "Rocky",
        "Rocky Ice",
        "Icy",
    }
)


class CatalogueFormatError(ValueError):
    """Raised when the surface commodity catalogue is missing or invalid."""


def _load_catalogue(path: Path) -> tuple[dict[str, object], ...]:
    """Load and validate the required surface commodity catalogue."""
    try:
        with path.open("r", encoding="utf-8") as catalogue_file:
            payload = json.load(catalogue_file)
    except FileNotFoundError as exc:
        raise CatalogueFormatError(f"catalogue file is missing: {path}") from exc
    except UnicodeDecodeError as exc:
        raise CatalogueFormatError("catalogue is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise CatalogueFormatError("catalogue is not valid JSON") from exc

    if not isinstance(payload, list):
        raise CatalogueFormatError("catalogue must be a JSON array")
    if len(payload) != _EXPECTED_COMMODITY_COUNT:
        raise CatalogueFormatError(
            f"catalogue must contain exactly {_EXPECTED_COMMODITY_COUNT} records"
        )

    records: list[dict[str, object]] = []
    seen_names: set[str] = set()
    seen_normalized_names: set[str] = set()
    for index, record in enumerate(payload):
        if not isinstance(record, dict) or set(record) != {"name", "planet_types"}:
            raise CatalogueFormatError(
                f"catalogue record {index} must contain only name and planet_types"
            )

        name = record["name"]
        if not isinstance(name, str) or not name.strip():
            raise CatalogueFormatError(
                f"catalogue record {index} has an invalid name"
            )
        if name in seen_names:
            raise CatalogueFormatError(f"duplicate commodity name: {name!r}")
        normalized_name = normalize_name(name)
        if normalized_name in seen_normalized_names:
            raise CatalogueFormatError(
                f"duplicate normalized commodity name: {name!r}"
            )
        seen_names.add(name)
        seen_normalized_names.add(normalized_name)

        planet_types = record["planet_types"]
        if not isinstance(planet_types, list) or not planet_types:
            raise CatalogueFormatError(
                f"catalogue record {index} has invalid planet_types"
            )
        if any(
            not isinstance(planet_type, str) or not planet_type.strip()
            for planet_type in planet_types
        ):
            raise CatalogueFormatError(
                f"catalogue record {index} has an invalid planet type"
            )
        unknown_types = set(planet_types) - _ALLOWED_PLANET_TYPES
        if unknown_types:
            raise CatalogueFormatError(
                f"catalogue record {index} has unsupported planet types: "
                f"{sorted(unknown_types)!r}"
            )
        if len(planet_types) != len(set(planet_types)):
            raise CatalogueFormatError(
                f"catalogue record {index} has duplicate planet types"
            )

        records.append(record)

    return tuple(records)

_COMMODITY_ALIASES = {
    "Bastnasite": "Bastnäsite",
    "Methanol Monohydrate Crystals": "Methanol Crystals",
}

COMMODITY_ALIASES = MappingProxyType(_COMMODITY_ALIASES)


def normalize_name(value: object | None) -> str:
    """Return the experiment-compatible key for a product name.

    NFKD decomposition removes accents; case folding and retaining only
    alphanumeric characters makes case, punctuation, and spacing irrelevant.
    ``None`` normalizes to an empty key, matching the adopted experiments.
    """
    if value is None:
        return ""

    decomposed = unicodedata.normalize("NFKD", str(value))
    return "".join(
        character.casefold()
        for character in decomposed
        if not unicodedata.combining(character) and character.isalnum()
    )


_CATALOGUE = _load_catalogue(CATALOGUE_PATH)
SURFACE_COMMODITIES = tuple(record["name"] for record in _CATALOGUE)


def commodities_for_planet_types(planet_types: Iterable[str]) -> tuple[str, ...]:
    """Return catalogue-ordered commodities available on any requested type."""
    if isinstance(planet_types, (str, bytes)):
        raise TypeError("planet_types must be an iterable of planet type names")
    requested = set(planet_types)
    if any(not isinstance(planet_type, str) for planet_type in requested):
        raise TypeError("planet type names must be strings")
    return tuple(
        record["name"]
        for record in _CATALOGUE
        if requested.intersection(record["planet_types"])
    )


def planet_types_for_commodities(
    commodity_names: Iterable[str],
) -> Mapping[str, frozenset[str]]:
    """Return catalogue-derived canonical planet types for requested commodities."""
    if isinstance(commodity_names, (str, bytes)):
        raise TypeError("commodity_names must be an iterable of commodity names")
    requested = tuple(commodity_names)
    result: dict[str, frozenset[str]] = {}
    for requested_name in requested:
        canonical = canonical_commodity_name(requested_name)
        if canonical is None:
            continue
        for record in _CATALOGUE:
            if record["name"] == canonical:
                result[canonical] = frozenset(record["planet_types"])
                break
    return result


def _build_canonical_names() -> MappingProxyType:
    """Build immutable normalized-name to canonical-name lookup data."""
    names = {normalize_name(product): product for product in SURFACE_COMMODITIES}
    names.update(
        (normalize_name(alias), canonical)
        for alias, canonical in _COMMODITY_ALIASES.items()
    )
    return MappingProxyType(names)


_CANONICAL_NAMES = _build_canonical_names()


def canonical_commodity_name(raw_name: object | None) -> str | None:
    """Resolve a canonical product name or demonstrated alias.

    Unknown names return ``None``. Returned values always use the adopted
    canonical spelling from :data:`SURFACE_COMMODITIES`.
    """
    return _CANONICAL_NAMES.get(normalize_name(raw_name))
