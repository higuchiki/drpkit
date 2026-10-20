"""Semantic Hz writer, independent of a running Resolve."""
import math
from pathlib import Path
import tempfile
import unittest
from drpkit import reader as r, writer as w

FIXTURE = Path(__file__).parent / 'fixtures' / 'fixture_default-01.drp'


class EqFrequencyTest(unittest.TestCase):
    def model(self):
        return r.load_models(str(FIXTURE))[0]['model']

    def test_gui_export_points(self):
        for band, hz, range_id, knob in [(1, 70, None, 84),
                (2, 1000, 1, 218), (2, 1234, 1, 238),
                (3, 240, 1, 83), (4, 1223, 2, 89), (5, 6048, 3, 136),
                (6, 22000, None, 256)]:
            encoded = w.encode_eq_frequency(band, hz, range_id)
            self.assertEqual(encoded[0x333 + band], knob, (band, hz))

    def test_all_integer_hz_have_valid_bin(self):
        law = w._eq_law()
        for band in range(1, 7):
            low, high = (30, 399) if band == 1 else ((1400, 22000) if band == 6 else (30, 22000))
            for hz in range(low, high + 1):
                encoded = w.encode_eq_frequency(band, hz, law=law)
                range_id = encoded.get(0x287 + band, law['fixed_bands'].get(band))
                limits = law['ranges'][range_id]
                knob = encoded[0x333 + band]
                position = 256 * math.log(hz / limits['min_hz']) / math.log(limits['log_max_hz'] / limits['min_hz'])
                self.assertTrue(abs(knob - position) <= 0.5 + 1e-8)
                self.assertEqual(encoded[0xf0 + band], hz)

    def test_current_range_preserved_when_possible(self):
        self.assertEqual(w.encode_eq_frequency(2, 1000, 2)[0x289], 2)
        self.assertEqual(w.encode_eq_frequency(2, 1000, 0)[0x289], 1)

    def test_invalid_input(self):
        for band, hz in [(0, 100), (7, 100), (1.0, 100), (True, 100), (2, True),
                         (2, 29), (2, 22001), (1, 400), (6, 1399),
                         (2, 'nan'), (2, 'inf'), (2, 123.5), (2, 'bad')]:
            with self.assertRaises(ValueError):
                w.encode_eq_frequency(band, hz)

    def test_raw_conflicts_and_duplicates(self):
        model = self.model()
        with self.assertRaises(ValueError):
            w.frequency_sets(model, [('@A1', 2, 1000)], [('Track1', 0x335, 218)])
        with self.assertRaises(ValueError):
            w.frequency_sets(model, [('@A1', 2, 1000), ('Track1', 2, 1100)])

    def test_unknown_or_non_eq_target(self):
        for name in ('Missing', 'VCA 1'):
            with self.assertRaises(ValueError):
                w.frequency_sets(self.model(), [(name, 2, 1000)])

    def test_build_and_exact_changed_cells(self):
        data, log = w.build_drp(str(FIXTURE), [], eq_frequencies=[('@A1', 2, 1234), ('Bus 1', 5, 17654)])
        import io
        after = r.models_from_drp(io.BytesIO(data))[0]['model']
        w._verify(self.model(), after, log)
        self.assertEqual(len(log), 6)

    def test_invalid_request_creates_no_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new.drp'
            with self.assertRaises(SystemExit):
                w.rewrite_drp(str(FIXTURE), str(path), [], eq_frequencies=[('Bus 1', 2, 20)])
            self.assertFalse(path.exists())

    def test_readonly_verify_reports_mismatch(self):
        self.assertEqual(w.verify_eq_frequencies(str(FIXTURE), [('Bus 1', 2, 119)]), [])
        rows = w.verify_eq_frequencies(str(FIXTURE), [('Bus 1', 2, 1399)])
        self.assertEqual(rows[0]['expected_hz'], 1399)
        self.assertEqual(rows[0]['actual_hz'], [119])


if __name__ == '__main__':
    unittest.main()
