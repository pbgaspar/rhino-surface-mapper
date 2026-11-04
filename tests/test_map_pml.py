import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from map_pml import (PML_MATCH_DISTANCE_M, corresponds_to_map, infer_legacy_pml, matching_candidates,
                     newest_by_pml_save_time, next_version_path,
                     safe_filename_component, surface_distance)


class MapPmlTests(unittest.TestCase):
    def make_state(self, *, system='Sol', body='Earth', center_lon=0, pml_id='1'):
        return SimpleNamespace(system=system, body=body, radius=6_371_000,
                               pml_center_lat=0, pml_center_lon=center_lon,
                               pml_id=pml_id)

    def test_correspondence_uses_identity_and_inclusive_distance(self):
        state = self.make_state()
        degrees_at_threshold = PML_MATCH_DISTANCE_M / 6_371_000 * 180 / 3.141592653589793
        self.assertTrue(corresponds_to_map(state, 'Sol', 'Earth', 0, 0.0))
        self.assertTrue(corresponds_to_map(state, 'Sol', 'Earth', 0, degrees_at_threshold))
        self.assertFalse(corresponds_to_map(state, 'Sol', 'Earth', 0, degrees_at_threshold + 0.001))
        self.assertFalse(corresponds_to_map(state, 'Other', 'Earth', 0, 0.0))
        self.assertFalse(corresponds_to_map(state, 'Sol', 'Mars', 0, 0.0))

    def test_pml_and_jd_identifiers_do_not_change_correspondence(self):
        pml = self.make_state(pml_id='6')
        jd = self.make_state(pml_id='JD1')
        self.assertEqual(corresponds_to_map(pml, 'Sol', 'Earth', 0, 0.05),
                         corresponds_to_map(jd, 'Sol', 'Earth', 0, 0.05))

    def test_missing_or_invalid_centre_does_not_correspond(self):
        missing = self.make_state()
        missing.pml_center_lat = None
        self.assertFalse(corresponds_to_map(missing, 'Sol', 'Earth', 0, 0))
        invalid = self.make_state()
        invalid.pml_center_lat = 'invalid'
        self.assertFalse(corresponds_to_map(invalid, 'Sol', 'Earth', 0, 0))

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

    def test_saved_map_selection_prefers_save_time_then_legacy_mtime(self):
        with tempfile.TemporaryDirectory() as folder:
            older = Path(folder) / 'older.json'
            newer = Path(folder) / 'newer.json'
            legacy_old = Path(folder) / 'legacy-old.json'
            legacy_new = Path(folder) / 'legacy-new.json'
            for path in (older, newer, legacy_old, legacy_new):
                path.touch()
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))
            os.utime(legacy_old, (100, 100))
            os.utime(legacy_new, (200, 200))
            saved_old = self.make_state()
            saved_old.last_saved_at = '2024-01-01T00:00:00Z'
            saved_new = self.make_state()
            saved_new.last_saved_at = '2024-01-02T00:00:00Z'
            legacy_old_state = self.make_state()
            legacy_old_state.last_saved_at = 'unusable'
            legacy_new_state = self.make_state()
            legacy_new_state.last_saved_at = None
            legacy_old_state.pml_id = legacy_new_state.pml_id = 'JD2'

            selected = newest_by_pml_save_time([
                (0, older, saved_old), (0, newer, saved_new),
                (0, legacy_old, legacy_old_state),
                (0, legacy_new, legacy_new_state),
            ])
            self.assertEqual({item[1] for item in selected}, {newer, legacy_new})

    def test_next_version_does_not_treat_brackets_as_glob_patterns(self):
        canonical = Path('Kappa 2 [6].json')
        paths = [Path('Kappa 2 [6].json'), Path('Kappa 2 [6] v2.json'), Path('other v9.json')]
        self.assertEqual(next_version_path(canonical, paths).name, 'Kappa 2 [6] v3.json')


if __name__ == '__main__':
    unittest.main()
