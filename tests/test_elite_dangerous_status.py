import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from elite_dangerous.status import read_status_if_changed


class StatusInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / 'Status.json'

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_document_returns_timestamp_and_payload(self):
        payload = {'Flags': 0x04000000, 'BodyName': 'Earth'}
        self.path.write_text(json.dumps(payload), encoding='utf-8')

        result = read_status_if_changed(self.path, None)

        self.assertIsNotNone(result)
        mtime, document = result
        self.assertEqual(mtime, self.path.stat().st_mtime_ns)
        self.assertEqual(document, payload)

    def test_unchanged_timestamp_returns_no_document(self):
        self.path.write_text('{"Flags": 0}', encoding='utf-8')
        first = read_status_if_changed(self.path, None)

        self.assertIsNone(read_status_if_changed(self.path, first[0]))

    def test_force_reads_unchanged_timestamp(self):
        payload = {'Flags': 0}
        self.path.write_text(json.dumps(payload), encoding='utf-8')
        first = read_status_if_changed(self.path, None)

        result = read_status_if_changed(self.path, first[0], force=True)

        self.assertEqual(result, (first[0], payload))

    def test_missing_file_error_is_propagated(self):
        with self.assertRaises(FileNotFoundError):
            read_status_if_changed(self.path, None)

    def test_malformed_json_error_is_propagated(self):
        self.path.write_text('{', encoding='utf-8')

        with self.assertRaises(json.JSONDecodeError):
            read_status_if_changed(self.path, None)

    def test_utf8_document_is_decoded(self):
        payload = {'BodyName': 'Planeta Ártico'}
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

        result = read_status_if_changed(self.path, None)

        self.assertEqual(result[1], payload)
