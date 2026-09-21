import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from map_pml import (PML_MATCH_DISTANCE_M, infer_legacy_pml, matching_candidates,
                     next_version_path, safe_filename_component, surface_distance)


class MapPmlTests(unittest.TestCase):
    def test_filename_and_distance_rules(self):
        self.assertEqual(safe_filename_component('A:/B. '), 'A__B')
        self.assertEqual(surface_distance(1, 0, 0, 0, 180), 3.141592653589793)
        self.assertLess(surface_distance(6_371_000, 0, 0, 0, 0.1), PML_MATCH_DISTANCE_M)

    def test_legacy_metadata_is_recovered_without_writing(self):
        state = SimpleNamespace(system='', body='', pml_id='', pml_center_lat=None,
                                pml_center_lon=None, marks=[{'name': 'Centro [6]', 'lat': 1, 'lon': 2}])
        infer_legacy_pml(state, Path('Kappa') / 'Kappa 2 [6].json', 'Kappa', 'wrong')
        self.assertEqual((state.system, state.body, state.pml_id), ('Kappa', 'Kappa 2', '6'))
        self.assertEqual((state.pml_center_lat, state.pml_center_lon), (1, 2))

    def test_matching_ignores_invalid_and_respects_strict_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            valid = root / 'valid.json'
            invalid = root / 'invalid.json'
            valid.touch()
            invalid.touch()
            def load(path):
                if path == invalid:
                    raise ValueError('invalid')
                return SimpleNamespace(system='Sol', body='Earth', radius=6_371_000,
                                       pml_center_lat=0, pml_center_lon=0,
                                       pml_id='1', marks=[], body_key='')
            result = matching_candidates([valid, invalid], 'Sol', 'Earth', 0, 0, load)
            self.assertEqual([item[1] for item in result], [valid])

    def test_next_version_does_not_treat_brackets_as_glob_patterns(self):
        canonical = Path('Kappa 2 [6].json')
        paths = [Path('Kappa 2 [6].json'), Path('Kappa 2 [6] v2.json'), Path('other v9.json')]
        self.assertEqual(next_version_path(canonical, paths).name, 'Kappa 2 [6] v3.json')


if __name__ == '__main__':
    unittest.main()
