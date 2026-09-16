import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("system_iridium", Path(__file__).with_name("System Iridium market.py"))
market = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market)


class MarketTests(unittest.TestCase):
    def test_selected_commodity_and_interactive_input(self):
        record = {"name": "Test", "market": [
            {"commodity": "Iridium", "demand": 7, "sell_price": 42},
            {"commodity": "Gold", "demand": 20, "sell_price": 100},
        ]}
        self.assertEqual(market.commodity_row(record, " gOLD ")["price"], 100)
        self.assertIsNone(market.commodity_row(record, "Silver"))
        with patch.object(market.sys, "argv", ["script.py"]), \
             patch("builtins.input", side_effect=[" Kappa ", " Gold "]), \
             patch.object(market, "query_system", return_value=([], [])) as query, \
             patch("builtins.print"):
            self.assertEqual(market.main(), 0)
            query.assert_called_once_with("Kappa", "Gold")

    def test_exact_system_on_second_page(self):
        pages = [{"results": [{"name": "Kappa Reticuli", "id64": 1}], "count": 2},
                 {"results": [{"name": "Kappa", "id64": 2}], "count": 2}]
        with patch.object(market, "get_json", side_effect=pages) as request:
            self.assertEqual(market.find_system(None, "kappa"), 2)
            self.assertEqual(request.call_args.kwargs["json"]["page"], 1)

    def test_repeated_page_is_not_silently_accepted(self):
        page = {"results": [{"name": "Kappa Reticuli", "id64": 1}], "count": 2}
        with patch.object(market, "get_json", return_value=page):
            with self.assertRaises(ValueError):
                market.find_system(None, "Kappa")

    def test_planetary_stations_and_duplicates(self):
        station = {"name": "Station", "market_id": 123}
        self.assertEqual(len(market.collect_stations({"stations": [station],
            "bodies": [{"stations": [station, {"market_id": 456}]}]})), 2)

    def test_pad_sizes_and_unknown(self):
        for data, expected in [({"has_large_pad": True}, "L (grande)"),
                               ({"medium_pads": 1}, "M (média)"),
                               ({"small_pads": 1}, "S (pequena)"),
                               ({"has_large_pad": False}, "Desconhecida")]:
            self.assertEqual(market.landing_pad(data), expected)

    def test_prices_demand_and_distinct_dates(self):
        record = {"name": "Test", "updated_at": "station date",
                  "market_updated_at": "market date", "market": [
                      {"commodity": "Iridium", "demand": 7, "sell_price": 42, "buy_price": 99}]}
        row = market.commodity_row(record, "Iridium")
        self.assertEqual(row["price"], 42)
        self.assertEqual(row["market_updated_at"], "market date")
        self.assertEqual(row["updated_at"], "station date")
        record["market"][0]["demand"] = 0
        self.assertIsNone(market.commodity_row(record, "Iridium"))
        record["market"][0]["demand"] = None
        with self.assertRaises(ValueError):
            market.commodity_row(record, "Iridium")

    def test_missing_market_is_not_zero_demand(self):
        with self.assertRaises(ValueError):
            market.commodity_row({"name": "Test"}, "Iridium")
        self.assertIsNone(market.commodity_row({"name": "Test", "market": []}, "Iridium"))


if __name__ == "__main__":
    unittest.main()

