"""Windows output and Resolve 19 marker regression tests."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

from drpkit import reader as r


class WindowsReaderTest(unittest.TestCase):
    def test_resolve19_marker_position_is_direct_integer(self):
        payload = bytes.fromhex('121d0a1b087c1217000000020000000f0a0d08021a001a01311a0474657374')
        self.assertEqual(r.decode_markers(payload, {2: 'Blue'}), [dict(
            frame=124, color='Blue', name='test', note='', duration=1, custom_data='')])

    def test_modern_markers_still_roundtrip(self):
        markers = [dict(frame=-3, color='Blue', name='名前', note='説明', duration=2, custom_data='')]
        payload = r._pbpack([(2, 2, r.encode_markers(markers, {2: 'Blue'}))])
        self.assertEqual(r.decode_markers(payload, {2: 'Blue'}), markers)

    def test_unnamed_edit_track_has_stable_alias(self):
        xml = '<Sm2TiTrack DbId="t"><Type>1</Type><UserDefinedName/><Sm2TiAudioClip DbId="c"><Name>clip</Name></Sm2TiAudioClip></Sm2TiTrack>'
        self.assertEqual(r._items_from_xml(xml)[0]['track'], '@A1')

    @unittest.skipUnless(os.name == 'nt', 'Windows code-page regression')
    def test_cli_overrides_cp932_output(self):
        env = dict(os.environ, PYTHONIOENCODING='cp932', PYTHONUTF8='0', PYTHONDONTWRITEBYTECODE='1')
        fixture = Path(__file__).parent / 'fixtures' / 'fixture_default-01.drp'
        result = subprocess.run([sys.executable, '-m', 'drpkit', 'read', str(fixture)], cwd=str(Path(__file__).parents[1]), env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
        result.stdout.decode('utf-8', errors='strict')


if __name__ == '__main__':
    unittest.main()
