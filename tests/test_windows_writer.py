"""Regression coverage for unnamed stereo tracks and split Bus tables."""
import os
from pathlib import Path
import struct
import unittest

from drpkit import reader as r, writer as w

FIXTURE = Path(__file__).parent / 'fixtures' / 'fixture_default-01.drp'


class WindowsWriterTest(unittest.TestCase):
    def model(self):
        return r.load_models(str(FIXTURE))[0]['model']

    def test_bus_fader_offset_includes_split_region(self):
        model = self.model()
        tab = next(t for t in r.channel_tables(model) if t['names'] == ['Bus 1'])
        p, _ = w._records_with_pos(model, tab)[1]
        self.assertEqual(struct.unpack_from('<i', model, p + 12)[0], tab['items'][1][0])
        new, done = w.apply_sets(model, [('Bus 1', 1, -30)])
        w._verify(model, new, done)
        after = next(t for t in r.channel_tables(new) if t['names'] == ['Bus 1'])
        self.assertEqual(after['items'][1], [-30])

    def test_unnamed_track_aliases_use_strip_ids_not_name_grouping(self):
        tab = {'names': ['', '', '', ''], 'items': {
            1: [-60, -60, 0, 0], 0xdf: [1] * 4, 0x458: [0, -1, 1, -1]}}
        self.assertEqual(r.track_aliases(tab), {'@A1': [0, 1], '@A2': [2, 3]})
        tab['items'][0x458] = [0, 1, -1, -1]
        self.assertEqual(r.track_aliases(tab), {'@A1': [0], '@A2': [1, 2, 3]})

    def test_blank_table_keys_do_not_collide(self):
        # A routing table with blank names must not hide an audio fader change.
        cells = w._raw_cells(self.model())
        self.assertTrue(cells)
        self.assertTrue(all(isinstance(key[0], int) for key in cells))

    def test_ambiguous_alias_layout_refused(self):
        for ids in ([0, -1, 0, -1], [-1, 0, 1, -1], [0, -2, 1, -1], [0, 1]):
            tab = {'names': ['', '', '', ''], 'items': {
                1: [0] * 4, 0xdf: [1] * 4, 0x458: ids}}
            self.assertEqual(r.track_aliases(tab), {})

    def test_unnamed_fixture_write_without_windows_file(self):
        model = self.model()
        tab = next(t for t in r.channel_tables(model) if t['names'][0] == 'Track1')
        recs, _ = r._parse_records(model, tab['record_start'])
        p, _, count, names = next(rec for rec in recs if rec[1] == r.NAMES_ITEM)
        old_end = p + 12 + sum(4 + len(n.encode('utf-8')) for n in names)
        blank = model[:p + 12] + bytes(4 * count) + model[old_end:]
        new, done = w.apply_sets(blank, [('@A1', 1, -90), ('@A2', 2, 1)])
        w._verify(blank, new, done)
        after = next(t for t in r.channel_tables(new) if r.track_aliases(t))
        self.assertEqual(after['items'][1][:2], [-90, -90])
        self.assertEqual(after['items'][2][2], 1)
        self.assertEqual(len(w._raw_cells(blank)), len(w._raw_cells(new)))

    def test_frequency_only_is_rejected(self):
        for band in range(2, 6):
            with self.assertRaisesRegex(SystemExit, 'frequency requires matching knob'):
                w.apply_sets(self.model(), [('Bus 1', 0xf0 + band, 1000)])

    def test_compressor_mix_preserves_gui_value_and_other_cells(self):
        # Mix is the GUI control value, not a wet percentage: no inversion/squaring.
        model = self.model()
        original = w._raw_cells(model)
        for mix in (0, 25, 50, 75, 100):
            with self.subTest(mix=mix):
                new, done = w.apply_sets(model, [('Track1', 0x117, mix)])
                w._verify(model, new, done)
                self.assertEqual(done[0][3], [0, 1])
                after = w._raw_cells(new)
                expected = dict(original)
                table_index = next(i for i, tab in enumerate(r.channel_tables(model))
                                   if tab['names'][0] == 'Track1')
                for column in (0, 1):
                    expected[(table_index, column, 0x117)] = mix
                self.assertEqual(after, expected)

    def test_frequency_companions_only_requested_cells_change(self):
        model = self.model()
        sets = [('Bus 1', 0xf2, 1000), ('Bus 1', 0x335, 218), ('Bus 1', 0x289, 1)]
        new, done = w.apply_sets(model, sets)
        w._verify(model, new, done)
        tab = next(t for t in r.channel_tables(new) if t['names'] == ['Bus 1'])
        self.assertEqual([tab['items'][k][0] for _, k, _ in sets], [1000, 218, 1])

    @unittest.skipUnless(os.environ.get('DRPKIT_WINDOWS_FIXTURE'), 'local Resolve 19 fixture')
    def test_real_windows_unnamed_stereo_write(self):
        path = os.environ['DRPKIT_WINDOWS_FIXTURE']
        model = r.load_models(path)[0]['model']
        sets = [('@A1', 1, -90), ('@A2', 2, 0), ('Bus 1', 1, -30)]
        new, done = w.apply_sets(model, sets)
        w._verify(model, new, done)
        self.assertEqual(done[0][3], [0, 1])
        self.assertEqual(done[1][3], [2, 3])
        self.assertEqual([s['name'] for s in r.read(path)[0]['strips']], ['@A1', '@A2', 'Bus 1'])


if __name__ == '__main__':
    unittest.main()
