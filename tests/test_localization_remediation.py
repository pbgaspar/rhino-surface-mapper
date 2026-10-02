import unittest
import re
from pathlib import Path
from xml.etree import ElementTree


class LocalizationRemediationTests(unittest.TestCase):
    def test_market_research_and_storage_sources_are_translated(self):
        project_root = Path(__file__).parents[1]
        root = ElementTree.parse(project_root / 'translations' / 'rsm_pt_PT.ts').getroot()
        contexts = {
            context.findtext('name'): {
                message.findtext('source'): message.findtext('translation')
                for message in context.findall('message')
            }
            for context in root.findall('context')
        }
        market = contexts['MarketResearchWindow']
        source_text = (project_root / 'market_research_window.py').read_text(encoding='utf-8')
        used_sources = {
            match.group(2)
            for match in re.finditer(
                r"translate\('MarketResearchWindow',\s*(['\"])(.*?)\1\)",
                source_text,
            )
        }
        missing_sources = sorted(source for source in used_sources if not market.get(source))
        self.assertEqual(missing_sources, [])
        for source in ('Market Research — Surface Mining', 'Market data issues',
                       'No valid market data', 'Sell', 'Demand', 'Age'):
            self.assertTrue(market[source])
        self.assertEqual(market['MARKETS'], 'MERCADOS')
        self.assertEqual(market['PRODUCTS'], 'PRODUTOS')
        self.assertEqual(market['LOCAL DEMAND >'], 'PROCURA LOCAL >')
        self.assertEqual(market['updated'], 'atualizado')
        self.assertEqual(market['Probably on:'], 'Provavelmente em:')
        self.assertEqual(contexts['LayoutOptions']['Storage'], 'Armazenamento')
        self.assertEqual(contexts['LayoutOptions']['Trash retention'], 'Período de conservação no Lixo')
        self.assertEqual(contexts['LayoutOptions']['days'], 'dias')


if __name__ == '__main__':
    unittest.main()
