"""Tests for deposit marker display formatting."""
import unittest
from unittest.mock import patch

from deposit_marker import deposit_details


class DepositMarkerTests(unittest.TestCase):
    def test_deposit_details_translates_canonical_size_without_mutating_item(self):
        item = {'size': 'Grande', 'rigs': 3}
        with patch('deposit_marker.translate', side_effect=lambda context, text: f'{context}:{text}') as translate:
            result = deposit_details(item)

        self.assertEqual(result, 'DepositDialog:Large · 3 rigs')
        translate.assert_called_once_with('DepositDialog', 'Large')
        self.assertEqual(item, {'size': 'Grande', 'rigs': 3})


if __name__ == '__main__':
    unittest.main()
