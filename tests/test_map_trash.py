import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from map_trash import (DEFAULT_RETENTION_DAYS, MAX_RETENTION_DAYS,
                       MIN_RETENTION_DAYS, cleanup_expired_trash,
                       inspect_trash, restore_trash_entry, retention_days,
                       soft_delete_map, TrashEntry)


class MapTrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.maps = self.root / 'MAPAS'
        self.trash = self.root / 'MAPAS_TRASH'
        self.maps.mkdir()
        self.trash.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_soft_delete_writes_recovery_metadata_and_moves_map(self):
        path = self.maps / 'Sol' / 'Earth.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'protected': False}), encoding='utf-8')
        with patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            item = soft_delete_map(path)
        self.assertFalse(path.exists())
        self.assertTrue((item / 'map.json').is_file())
        metadata = json.loads((item / 'metadata.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['original_relative_path'], 'Sol/Earth.json')
        self.assertIn('deleted_at', metadata)

    def test_protected_and_active_maps_are_rejected(self):
        path = self.maps / 'map.json'
        path.write_text(json.dumps({'protected': True}), encoding='utf-8')
        with patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            with self.assertRaises(ValueError):
                soft_delete_map(path)
            path.write_text(json.dumps({'protected': False}), encoding='utf-8')
            with self.assertRaises(ValueError):
                soft_delete_map(path, active_path=path)
        self.assertTrue(path.exists())

    def test_invalid_retention_uses_safe_default(self):
        self.assertEqual(retention_days(0), DEFAULT_RETENTION_DAYS)
        self.assertEqual(retention_days('30'), DEFAULT_RETENTION_DAYS)
        self.assertEqual(retention_days(MIN_RETENTION_DAYS), MIN_RETENTION_DAYS)
        self.assertEqual(retention_days(MAX_RETENTION_DAYS), MAX_RETENTION_DAYS)

    def test_cleanup_preserves_malformed_and_unknown_entries(self):
        malformed = self.trash / 'malformed'
        malformed.mkdir()
        (malformed / 'metadata.json').write_text('{}', encoding='utf-8')
        unknown = self.trash / 'unknown.txt'
        unknown.write_text('keep', encoding='utf-8')
        with patch('map_trash.maps_trash_directory', return_value=self.trash):
            self.assertEqual(cleanup_expired_trash(1), 0)
        self.assertTrue(malformed.exists())
        self.assertTrue(unknown.exists())

    def test_non_object_metadata_is_reported_and_preserved_by_inspection_and_cleanup(self):
        values = ([], 'text', 123, None)
        items = []
        for index, value in enumerate(values):
            item = self.trash / f'malformed-{index}'
            item.mkdir()
            (item / 'metadata.json').write_text(json.dumps(value), encoding='utf-8')
            (item / 'map.json').write_text('preserve', encoding='utf-8')
            items.append(item)

        with patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            entries, invalid_count = inspect_trash()
            self.assertEqual(entries, [])
            self.assertEqual(invalid_count, len(values))
            self.assertEqual(cleanup_expired_trash(1), 0)

        for item, value in zip(items, values):
            self.assertTrue(item.is_dir())
            self.assertEqual(
                json.loads((item / 'metadata.json').read_text(encoding='utf-8')),
                value,
            )
            self.assertEqual((item / 'map.json').read_text(encoding='utf-8'), 'preserve')

    def test_restore_recreates_nested_destination_and_removes_own_container(self):
        source = self.maps / 'Kappa' / 'Map v12.json'
        source.parent.mkdir()
        source.write_text(json.dumps({'protected': False}), encoding='utf-8')
        with patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            item = soft_delete_map(source)
            entries, invalid = inspect_trash()
            self.assertEqual(invalid, 0)
            self.assertEqual(len(entries), 1)
            restored = restore_trash_entry(entries[0])
        self.assertEqual(restored, source.resolve())
        self.assertEqual(json.loads(source.read_text(encoding='utf-8')), {'protected': False})
        self.assertFalse(item.exists())

    def test_restore_collision_does_not_overwrite_or_remove_trash(self):
        source = self.maps / 'Map.json'
        source.write_text(json.dumps({'protected': False}), encoding='utf-8')
        destination = self.maps / 'Map.json'
        with patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            item = soft_delete_map(source)
            destination.write_text('current', encoding='utf-8')
            entry = inspect_trash()[0][0]
            with self.assertRaises(FileExistsError):
                restore_trash_entry(entry)
        self.assertEqual(destination.read_text(encoding='utf-8'), 'current')
        self.assertTrue(item.exists())

    def test_invalid_entries_are_reported_and_preserved(self):
        invalid = self.trash / 'invalid'
        invalid.mkdir()
        (invalid / 'metadata.json').write_text(json.dumps({'original_relative_path': '../escape.json'}), encoding='utf-8')
        with patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            entries, invalid_count = inspect_trash()
        self.assertEqual(entries, [])
        self.assertEqual(invalid_count, 1)
        self.assertTrue(invalid.exists())

    def test_symlinked_trash_directory_is_preserved_and_not_restored(self):
        external = self.root / 'external'
        external.mkdir()
        map_path = external / 'map.json'
        map_path.write_text('external map', encoding='utf-8')
        metadata_path = external / 'metadata.json'
        metadata_path.write_text(json.dumps({
            'original_relative_path': 'old.json',
            'deleted_at': '2020-01-01T00:00:00+00:00',
        }), encoding='utf-8')
        item = self.trash / 'linked'
        try:
            os.symlink(external, item, target_is_directory=True)
        except OSError:
            item.mkdir()

        with patch.object(Path, 'is_symlink', autospec=True,
                          side_effect=lambda path: path.name == 'linked'), \
                patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            entries, invalid_count = inspect_trash()
            self.assertEqual(entries, [])
            self.assertEqual(invalid_count, 1)
            self.assertEqual(cleanup_expired_trash(1), 0)
            with self.assertRaises(ValueError):
                restore_trash_entry(TrashEntry(
                    item, 'old.json', datetime.now(timezone.utc)))

        self.assertTrue(item.exists())
        self.assertEqual(map_path.read_text(encoding='utf-8'), 'external map')
        self.assertTrue(metadata_path.is_file())

    def test_symlinked_trash_files_are_preserved_by_inspection_and_cleanup(self):
        external = self.root / 'external'
        external.mkdir()
        external_map = external / 'map.json'
        external_map.write_text('external map', encoding='utf-8')
        external_metadata = external / 'metadata.json'
        external_metadata.write_text(json.dumps({
            'original_relative_path': 'old-metadata.json',
            'deleted_at': '2020-01-01T00:00:00+00:00',
        }), encoding='utf-8')

        map_link = self.trash / 'map-link'
        map_link.mkdir()
        (map_link / 'metadata.json').write_text(json.dumps({
            'original_relative_path': 'old-map.json',
            'deleted_at': '2020-01-01T00:00:00+00:00',
        }), encoding='utf-8')

        metadata_link = self.trash / 'metadata-link'
        metadata_link.mkdir()
        (metadata_link / 'map.json').write_text('local map', encoding='utf-8')
        try:
            (map_link / 'map.json').symlink_to(external_map)
        except OSError:
            (map_link / 'map.json').write_text('link placeholder', encoding='utf-8')
        try:
            (metadata_link / 'metadata.json').symlink_to(external_metadata)
        except OSError:
            (metadata_link / 'metadata.json').write_text('link placeholder', encoding='utf-8')

        with patch.object(Path, 'is_symlink', autospec=True,
                          side_effect=lambda path: path.name in {'map.json', 'metadata.json'}), \
                patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            entries, invalid_count = inspect_trash()
            self.assertEqual(entries, [])
            self.assertEqual(invalid_count, 2)
            self.assertEqual(cleanup_expired_trash(1), 0)

        self.assertTrue(map_link.exists())
        self.assertTrue(metadata_link.exists())
        self.assertEqual(external_map.read_text(encoding='utf-8'), 'external map')
        self.assertTrue(external_metadata.is_file())

    def test_valid_expired_entry_is_removed_but_invalid_entry_is_preserved(self):
        valid = self.trash / 'valid'
        valid.mkdir()
        (valid / 'map.json').write_text('old', encoding='utf-8')
        (valid / 'metadata.json').write_text(json.dumps({
            'original_relative_path': 'old.json',
            'deleted_at': '2020-01-01T00:00:00+00:00',
        }), encoding='utf-8')
        invalid = self.trash / 'invalid'
        invalid.mkdir()
        (invalid / 'metadata.json').write_text('{}', encoding='utf-8')
        with patch('map_trash.maps_directory', return_value=self.maps), \
                patch('map_trash.maps_trash_directory', return_value=self.trash):
            self.assertEqual(cleanup_expired_trash(1), 1)
        self.assertFalse(valid.exists())
        self.assertTrue(invalid.exists())


if __name__ == '__main__':
    unittest.main()
