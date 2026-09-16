"""Surface mining product data and name normalization."""

from types import MappingProxyType
import unicodedata


# Canonical spelling and adopted membership are characterized from the mature
# market experiments. Keep this data separate from its lookup behavior.
_SURFACE_COMMODITIES = (
    "Helium",
    "Helium-3",
    "Tritium",
    "Water",
    "Iridium",
    "Platinum",
    "Palladium",
    "Gold",
    "Osmium",
    "Silver",
    "Samarium",
    "Tantalum",
    "Thorium",
    "Uranium",
    "Titanium",
    "Lithium",
    "Copper",
    "Thortveitite",
    "Periclase Dunite",
    "Monazite",
    "Rhodplumsite",
    "Diamond",
    "Alexandrite",
    "Sapphire",
    "Ruby",
    "Grandidierite",
    "Serendibite",
    "Bastnäsite",
    "Low Temperature Diamonds",
    "Quartz Pyroxenite",
    "Deuterium",
    "Magnesite",
    "Olivine",
    "Jadeite",
    "Uraninite",
    "Haematite",
    "Methanol Crystals",
)

_COMMODITY_ALIASES = {
    "Bastnasite": "Bastnäsite",
    "Methanol Monohydrate Crystals": "Methanol Crystals",
}

SURFACE_COMMODITIES = _SURFACE_COMMODITIES
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


def _build_canonical_names() -> MappingProxyType:
    """Build immutable normalized-name to canonical-name lookup data."""
    names = {normalize_name(product): product for product in _SURFACE_COMMODITIES}
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
