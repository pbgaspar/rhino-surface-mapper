import unittest

from elite_dangerous.market.commodities import (
    COMMODITY_ALIASES,
    SURFACE_COMMODITIES,
    canonical_commodity_name,
    normalize_name,
)


class CommodityTests(unittest.TestCase):
    def test_current_adopted_catalogue_has_37_products(self):
        self.assertEqual(len(SURFACE_COMMODITIES), 37)
        self.assertEqual(len(set(SURFACE_COMMODITIES)), len(SURFACE_COMMODITIES))

    def test_catalogue_is_immutable_and_consumers_need_not_assume_order(self):
        self.assertIsInstance(SURFACE_COMMODITIES, tuple)
        self.assertEqual(
            set(SURFACE_COMMODITIES),
            set(reversed(SURFACE_COMMODITIES)),
        )
        with self.assertRaises(TypeError):
            COMMODITY_ALIASES["Another name"] = "Helium"

    def test_normalization_ignores_case_accents_punctuation_and_spaces(self):
        self.assertEqual(normalize_name("Bastnäsite"), "bastnasite")
        self.assertEqual(normalize_name("  LOW-temperature  DIAMONDS! "), "lowtemperaturediamonds")
        self.assertEqual(normalize_name("Helium-3"), normalize_name("helium 3"))

    def test_canonical_names_resolve_to_adopted_spelling(self):
        self.assertEqual(canonical_commodity_name("bastnäsite"), "Bastnäsite")
        self.assertEqual(canonical_commodity_name("LOW temperature diamonds"), "Low Temperature Diamonds")

    def test_demonstrated_aliases_resolve_to_canonical_names(self):
        self.assertEqual(canonical_commodity_name("Bastnasite"), "Bastnäsite")
        self.assertEqual(
            canonical_commodity_name("Methanol Monohydrate Crystals"),
            "Methanol Crystals",
        )

    def test_unknown_product_returns_none(self):
        self.assertIsNone(canonical_commodity_name("Unobtainium"))
        self.assertIsNone(canonical_commodity_name(None))


if __name__ == "__main__":
    unittest.main()
