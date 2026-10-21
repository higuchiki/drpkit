"""Frame fields stored as 'integer|hex' (integer frames + fractional frames as a little-endian double).

Resolve writes this form for Start / Duration / In when a clip's frame rate differs from the timeline's
(e.g. a 24 fps mp3 on a 60 fps timeline). Synthetic data only: a minimal SQLite project and SeqContainer XML.
"""
import binascii
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from drpkit import reader as fr  # noqa: E402


def enc(n, frac):
    return "%d|%s" % (n, binascii.hexlify(struct.pack("<d", frac)).decode())


class FramesFieldTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(fr._frames("216264"), 216264.0)
        self.assertIs(type(fr._frames("216264", True)), int)
        self.assertAlmostEqual(fr._frames("216264|009217f40760e03f"), 216264.5117225, places=6)
        self.assertEqual(fr._frames(enc(10, 0.5)), 10.5)
        self.assertEqual(fr._frames(enc(10, 0.0), True), 10)
        self.assertIs(type(fr._frames(enc(10, 0.0), True)), int)
        self.assertIsNone(fr._frames(""))
        self.assertIsNone(fr._frames(None))
        self.assertIs(fr._dur, fr._frames)

    def test_xml_items(self):
        xml = ('<Sm2TiTrack DbId="t1"><Type>1</Type><UserDefinedName/>'
               '<Sm2TiAudioClip DbId="c1"><Name>a.mp3</Name><Start>%s</Start><Duration>%s</Duration><In>%s</In>'
               '</Sm2TiAudioClip></Sm2TiTrack>') % (enc(100, 0.25), enc(50, 0.5), enc(0, 0.5))
        it = fr._items_from_xml(xml)[0]
        self.assertEqual((it["start"], it["duration"], it["in"]), (100.25, 50.5, 0.5))

    def test_db_edits(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "Project.db")
            con = sqlite3.connect(path)
            con.executescript(
                'create table Sm2Timeline (Name text, Sequence text);'
                'create table Sm2TiTrack (Sm2TiTrack_id text, Sequence text, Type integer, UserDefinedName text);'
                'create table Sm2TiItem (Sm2TiItem_id text, Sm2TiTrack_id text, DbType text, Name text, PrettyType text,'
                ' Start text, Duration text, "In" text, AlignmentType text, Position text, EffectFiltersBA blob,'
                ' FieldsBlob blob);'
                'create table BtLockableBlob (FieldsBlob blob, BlobOwner text);')
            con.execute("insert into Sm2Timeline values ('T', 's1')")
            con.execute("insert into Sm2TiTrack values ('k1', 's1', 1, '')")
            con.execute("insert into Sm2TiTrack values ('k2', 's1', 1, '')")
            item = "insert into Sm2TiItem values (?, ?, 'Sm2TiAudioClip', ?, null, ?, ?, ?, null, null, null, null)"
            # '94' sorts after '216264|..' as text; the reader must order by number
            con.execute(item, ("i1", "k1", "late", "216396", "380", "655"))
            con.execute(item, ("i2", "k1", "frac", enc(216264, 0.5117225), "94", "2866"))
            con.execute(item, ("i3", "k1", "early", "94", "10", "0"))
            con.execute(item, ("i4", "k2", "second", enc(255670, 0.5), enc(15812, 0.0), enc(0, 0.5)))
            con.commit()
            con.close()
            res = fr.edits_from_db(path, {})
        items = res[0]["items"]
        self.assertEqual([it["name"] for it in items], ["early", "frac", "late", "second"])
        frac = items[1]
        self.assertAlmostEqual(frac["start"], 216264.5117225, places=6)
        self.assertEqual(frac["duration"], 94.0)
        self.assertIs(type(items[2]["start"]), int)
        self.assertEqual((items[3]["start"], items[3]["duration"], items[3]["in"]), (255670.5, 15812.0, 0.5))


if __name__ == "__main__":
    unittest.main()
