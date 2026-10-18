"""Reader / writer tests against synthetic fixtures made in Resolve 21.1.1.

fixtures/
  fixture_default-01.drp    new project, 2 audio tracks (Track1 = 10 s 1 kHz sine, Track2 = 10 s silence),
                            Track1 clip colored Orange, mixer untouched
  fixture_written-01.drp    default -> fairlight_writer.py (see expect_fixture_roundtrip-01.yaml)
  fixture_roundtrip-01.drp  written -> ImportProject into Resolve -> ExportProject
  fixture_fades_48_24-01.drp  FCPXML import (clip volume -6 dB) + API SetFades(FadeIn=48, FadeOut=24), saved, exported
  fixture_busfader_-20dB-01.drp  default with bus fader item 0x001 = -200; rendering it in Resolve is exactly
                                 20.0 dB quieter than the default (-21.1 -> -41.1 dB mean, 1 kHz sine)
"""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import yaml  # noqa: E402
from drpkit import reader as fr  # noqa: E402
from drpkit import writer as fw  # noqa: E402

FX = os.path.join(HERE, "fixtures")
DEFAULT = os.path.join(FX, "fixture_default-01.drp")
WRITTEN = os.path.join(FX, "fixture_written-01.drp")
ROUNDTRIP = os.path.join(FX, "fixture_roundtrip-01.drp")
SETS = [("Track2", 0x10c, 1), ("Track2", 0x10d, 51996), ("Track2", 0x10e, -200), ("Track2", 0x110, 40496),
        ("Track2", 0x112, 32196), ("Track2", 0x109, 68), ("Track2", 0x002, 1), ("Track2", 0x001, -60),
        ("Track2", 0x0f1, 160), ("Track2", 0x101, 1),
        ("Bus 1", 0x11d, 1), ("Bus 1", 0x11e, -15), ("Bus 1", 0x10d, 70000)]


def raw_tables(path):
    """{(table first name, channel name, column, item): raw int32}"""
    out = {}
    for mdl in fr.load_models(path):
        for tab in fr.channel_tables(mdl["model"]):
            for item, vals in tab["items"].items():
                if item == fr.NAMES_ITEM:
                    continue
                for col, v in enumerate(vals):
                    nm = tab["names"][col] if col < len(tab["names"]) else "?"
                    out[(tab["names"][0], nm, col, item)] = v
    return out


def check(path, expect):
    with open(os.path.join(HERE, expect), encoding="utf-8") as f:
        exp = yaml.safe_load(f)
    return fr.check_expect(fr.read(path), exp)


class ReaderTest(unittest.TestCase):
    def test_default_expect(self):
        ok, ng = check(DEFAULT, "expect_fixture_default-01.yaml")
        print("\n[default] match %d, mismatch %d" % (ok, len(ng)))
        self.assertEqual(ng, [])
        self.assertGreater(ok, 30)

    def test_roundtrip_expect(self):
        ok, ng = check(ROUNDTRIP, "expect_fixture_roundtrip-01.yaml")
        print("\n[roundtrip] match %d, mismatch %d" % (ok, len(ng)))
        self.assertEqual(ng, [])

    def test_edits(self):
        tl = fr.read_edits(DEFAULT)
        self.assertEqual(len(tl), 1)
        self.assertEqual(tl[0]["fps"], 24.0)
        clips = {r["track"]: r for r in tl[0]["items"]}
        self.assertEqual(set(clips), {"Track1", "Track2"})
        for r in clips.values():
            self.assertEqual((r["start"], r["end"], r["duration"], r["src_in"]), (86400, 86640, 240, 0.0))
            self.assertEqual(r["start_tc"], "01:00:00:00")
        self.assertEqual(clips["Track1"]["color"], "Orange")
        self.assertIsNone(clips["Track2"]["color"])


class FadeAndBusTest(unittest.TestCase):
    def test_fades(self):
        tl = fr.read_edits(os.path.join(FX, "fixture_fades_48_24-01.drp"))
        clip = [r for r in tl[0]["items"] if r["kind"] == "AudioClip"][0]
        self.assertEqual((clip["fade_in"], clip["fade_out"], clip["volume_db"]), (48.0, 24.0, -6.0))

    def test_fade_curve(self):
        """fixture_fadecurve-01.drp: fade out 96 frames, curve point (50 %, -20 = -2.0 dB).
        Rendered in Resolve the fade midpoint is exactly -2.0 dB (straight fade: -6.0 dB)."""
        tl = fr.read_edits(os.path.join(FX, "fixture_fadecurve-01.drp"))
        clip = [r for r in tl[0]["items"] if r["kind"] == "AudioClip"][0]
        self.assertEqual(clip["fade_out"], 96.0)
        self.assertEqual(clip["fade_out_curve"], [50.0, -20.0])
        self.assertIn("-2.0 dB", fr._curve_text("fade_out_curve", clip["fade_out_curve"]))
        self.assertIn("上に凸", fr._curve_text("fade_out_curve", clip["fade_out_curve"]))

    def test_clip_voice_isolation_and_leveler(self):
        """Clip-level built-in FX set with the API: Voice Isolation amount 55; Dialogue Leveler
        mode 2, background reduction on, output gain 6 dB."""
        vi = [r for r in fr.read_edits(os.path.join(FX, "fixture_clip_vi-01.drp"))[0]["items"] if r.get("clip_plugins")]
        self.assertEqual(vi[0]["clip_plugins"][0]["plugin"], "Voice Isolation")
        self.assertEqual(vi[0]["clip_plugins"][0]["params"]["amount"]["value"], "55.0")
        dl = [r for r in fr.read_edits(os.path.join(FX, "fixture_clip_dl-01.drp"))[0]["items"] if r.get("clip_plugins")]
        p = dl[0]["clip_plugins"][0]["params"]
        self.assertEqual(p["mode"]["value"], "2 MORE_LIFT_FOR_LOW_LEVELS")
        self.assertEqual((p["reduce_loud"]["value"], p["lift_soft"]["value"], p["background_reduction"]["value"]), ("OFF", "OFF", "ON"))
        self.assertEqual(p["output_gain"]["value"], "6.0 dB")
        self.assertFalse([r for r in fr.read_edits(DEFAULT)[0]["items"] if r.get("clip_plugins")])

    def test_volume_keyframes(self):
        """fixture_volume_keyframes-01.drp: clip volume keyframes 2 s 0 dB, 4 s -12, 6 s -12, 7 s 0 written into
        the drp, imported into Resolve and exported again. Rendering showed linear-in-dB interpolation
        (3 s = -6.0 dB, 6.5 s = -6.0 dB)."""
        clip = [r for r in fr.read_edits(os.path.join(FX, "fixture_volume_keyframes-01.drp"))[0]["items"] if r["track"] == "Track1"][0]
        self.assertEqual([(k["frame"], k["value"]) for k in clip["volume_db_keyframes"]], [(48, 0.0), (96, -12.0), (144, -12.0), (168, 0.0)])
        self.assertEqual(fr.decode_keyframes(fr.encode_keyframes([(10, -3.0), (5, 1.5)])),
                         [{"frame": 5, "value": 1.5, "flags": fr.KF_FLAGS_DEFAULT}, {"frame": 10, "value": -3.0, "flags": fr.KF_FLAGS_DEFAULT}])

    def test_no_fades_in_default(self):
        for r in fr.read_edits(DEFAULT)[0]["items"]:
            self.assertFalse(r.get("fade_in"))
            self.assertFalse(r.get("fade_out"))

    def test_bus_fader(self):
        def bus(path):
            return [s for s in fr.read(path)[0]["strips"] if s["name"] == "Bus 1"][0]["values"]
        self.assertEqual(bus(DEFAULT)["fader"]["value"], "0 dB")
        self.assertEqual(bus(DEFAULT)["mute"]["value"], "OFF")
        self.assertEqual(bus(DEFAULT)["bus_channels"]["value"], "2")
        self.assertEqual(bus(os.path.join(FX, "fixture_busfader_-20dB-01.drp"))["fader"]["value"], "-20 dB")


class WriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_only_requested_cells_change(self):
        out = os.path.join(self.tmp, "out.drp")
        fw.rewrite_drp(DEFAULT, out, SETS)
        a, b = raw_tables(DEFAULT), raw_tables(out)
        self.assertEqual(set(a), set(b))
        changed = {k for k in a if a[k] != b[k]}
        want = {(k[1], k[3]) for k in changed}
        self.assertEqual(want, {(n, i) for n, i, _ in SETS})
        self.assertEqual(raw_tables(out), raw_tables(WRITTEN))

    def test_refuses_overwrite(self):
        out = os.path.join(self.tmp, "exists.drp")
        open(out, "w").close()
        with self.assertRaises(SystemExit):
            fw.rewrite_drp(DEFAULT, out, SETS)

    def test_timeline_option(self):
        out = os.path.join(self.tmp, "tl.drp")
        fw.rewrite_drp(DEFAULT, out, SETS, timeline="Fixture")
        self.assertEqual(raw_tables(out), raw_tables(WRITTEN))
        bad = os.path.join(self.tmp, "bad.drp")
        with self.assertRaises(SystemExit):
            fw.rewrite_drp(DEFAULT, bad, SETS, timeline="NoSuchTimeline")
        self.assertFalse(os.path.exists(bad))

    def test_refuses_multiple_timelines_without_option(self):
        multi = os.path.join(self.tmp, "multi.drp")
        with zipfile.ZipFile(DEFAULT) as zin, zipfile.ZipFile(multi, "w", zipfile.ZIP_DEFLATED) as zout:
            mp = zin.read("MediaPool/Master/MpFolder.xml").decode("utf-8")
            for info in zin.infolist():
                zout.writestr(info.filename, zin.read(info.filename))
            zout.writestr("MediaPool/Master/Sub/MpFolder.xml",
                          mp.replace("<Name>Fixture</Name>", "<Name>Second</Name>").encode("utf-8"))
        out = os.path.join(self.tmp, "multi_out.drp")
        with self.assertRaises(SystemExit):
            fw.rewrite_drp(multi, out, SETS)
        self.assertFalse(os.path.exists(out))
        fw.rewrite_drp(multi, out, SETS, timeline="Second")
        tl = {m["timeline"]: m for m in fr.load_models(out)}
        orig = {m["timeline"]: m for m in fr.load_models(multi)}
        self.assertEqual(tl["Fixture"]["model"], orig["Fixture"]["model"])
        self.assertNotEqual(tl["Second"]["model"], orig["Second"]["model"])

    def test_no_partial_output_on_error(self):
        out = os.path.join(self.tmp, "partial.drp")
        with self.assertRaises(SystemExit):
            fw.rewrite_drp(DEFAULT, out, SETS + [("NoSuchTrack", 0x001, 1)])
        self.assertFalse(os.path.exists(out))
        with self.assertRaises(SystemExit):
            fw.rewrite_drp(DEFAULT, out, [("Track1", 0x7777, 1)])
        self.assertFalse(os.path.exists(out))

    def test_failed_write_leaves_no_file(self):
        import drpkit._atomic as atomic
        folder = tempfile.mkdtemp(dir=self.tmp)
        out = os.path.join(folder, "out.drp")
        real = atomic.os.fsync

        def boom(fd):
            raise OSError("disk full (simulated)")
        atomic.os.fsync = boom
        try:
            with self.assertRaises(OSError):
                fw.rewrite_drp(DEFAULT, out, SETS)
        finally:
            atomic.os.fsync = real
        self.assertEqual(os.listdir(folder), [])
        real_models = fr.models_from_drp
        fr.models_from_drp = lambda path: [] if str(path).endswith(".partial") else real_models(path)
        try:
            with self.assertRaises(SystemExit):
                fw.rewrite_drp(DEFAULT, out, SETS)
        finally:
            fr.models_from_drp = real_models
        self.assertEqual(os.listdir(folder), [])
        fw.rewrite_drp(DEFAULT, out, SETS)
        self.assertEqual(os.listdir(folder), ["out.drp"])
        self.assertEqual(raw_tables(out), raw_tables(WRITTEN))

    def test_resolve_preserved_written_values(self):
        """After a Resolve import/export cycle every raw value is still what the writer wrote."""
        a, b = raw_tables(WRITTEN), raw_tables(ROUNDTRIP)
        self.assertEqual({k: a[k] for k in a if a[k] != b.get(k)}, {})


if __name__ == "__main__":
    unittest.main()
