"""0.1.0 additions: track Voice Isolation on/off, timeline markers (read + compose), several media files per track,
the `drpkit` command line, and a privacy scan of every committed .drp.

fixtures/ (Resolve 21.1.1 exports of a fresh synthetic project `drpkit-fixture-02`, timeline `Fixture`, 24 fps,
start 01:00:00:00, two mono tracks with a generated 1 kHz / 440 Hz sine):
  fixture_base_wav-01.drp       no markers
  fixture_markers-01.drp        4 markers via Timeline.AddMarker: frames 0/48/100/200, Blue/Red/Yellow/Lemon,
                                durations 1/1/24/1, a note with XML characters, Japanese name and note, customData
  fixture_marker_colors-01.drp  16 markers, one per color, durations 1..16
  fixture_track_vi_off-01.drp   track Voice Isolation: track 1 amount 40 then disabled, track 2 amount 70 enabled
All of them went through tools/sanitize_drp.py (machine id and settings paths neutralized).
"""
import json
import os
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from drpkit import compose as c  # noqa: E402
from drpkit import reader as fr  # noqa: E402
from drpkit import cli  # noqa: E402

FX = ROOT / "tests" / "fixtures"
BASE = FX / "fixture_base_wav-01.drp"
MARKERS = FX / "fixture_markers-01.drp"
COLORS = FX / "fixture_marker_colors-01.drp"
VI_OFF = FX / "fixture_track_vi_off-01.drp"
SYNTH = ROOT / "tests" / "compose" / "template-synthetic-01.drp"
TONES = ROOT / "tests" / "compose" / "examples" / "audio"
FORMATS = ROOT / "tests" / "compose" / "formats" / "audio"
ALL_COLORS = ["Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia", "Rose", "Lavender", "Sky", "Mint",
              "Lemon", "Sand", "Cocoa", "Cream"]


def _have_zstd():
    try:
        from compression import zstd  # noqa: F401
        return True
    except ImportError:
        try:
            import zstandard  # noqa: F401
            return True
        except ImportError:
            return False


def entries(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


class Work(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="drpkit-t-"))

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def out(self, name="out.drp"):
        return self.work / name


class TrackVoiceIsolation(unittest.TestCase):
    def vi(self, path):
        res = fr.read(str(path))
        return [p["params"] for s in res[0]["strips"] for p in s["plugins"]
                if p["plugin"] == "Voice Isolation" and p["slot"] == "内蔵FX(6)"]

    def test_disabled_track_keeps_amount(self):
        t1, t2 = self.vi(VI_OFF)
        self.assertEqual((t1["enabled"]["value"], t1["amount"]["value"], t1["enabled"]["raw"] & 0x10), ("OFF", "40.01", 0x10))
        self.assertEqual((t2["enabled"]["value"], t2["amount"]["value"], t2["enabled"]["raw"] & 0x10), ("ON", "70.0", 0))

    def test_enabled_in_clip_fixture(self):
        (t1,) = self.vi(FX / "fixture_clip_vi-01.drp")
        self.assertEqual(t1["enabled"]["value"], "ON")

    def test_state_is_read_from_record_layout(self):
        model = fr.load_models(str(VI_OFF))[0]["model"]
        recs = [p for p in fr.plugins(model) if p["name"] == "Voice Isolation" and p["slot"] == 6]
        self.assertEqual([p["state"] for p in recs], [0x10, 0])
        for p in fr.plugins(model):
            self.assertIsNotNone(p["state"])

    def test_expect_key(self):
        res = fr.read(str(VI_OFF))
        names = [s["name"] for s in res[0]["strips"] if any(p["plugin"] == "Voice Isolation" for p in s["plugins"])]
        exp = {"strips": {names[0]: {"Voice Isolation.enabled": "OFF"}, names[1]: {"Voice Isolation.enabled": "ON"}}}
        self.assertEqual(fr.check_expect(res, exp), (2, []))


class ReadMarkers(unittest.TestCase):
    def test_markers(self):
        tl = fr.read_edits(str(MARKERS))[0]
        self.assertEqual(tl["start_frame"], 86400)
        got = [(m["offset"], m["frame"], m["color"], m["name"], m["note"], m["duration"], m["custom_data"]) for m in tl["markers"]]
        self.assertEqual(got, [
            (0, 86400, "Blue", "Intro", "", 1, ""),
            (48, 86448, "Red", "Cut here", "note with spaces & <xml> chars", 1, ""),
            (100, 86500, "Yellow", "区間", "日本語のメモ", 24, ""),
            (200, 86600, "Lemon", "L", "", 1, "custom-data-1")])

    def test_sixteen_colors(self):
        tl = fr.read_edits(str(COLORS))[0]
        self.assertEqual([(m["offset"], m["color"], m["duration"]) for m in tl["markers"]],
                         [(10 * i, col, i + 1) for i, col in enumerate(ALL_COLORS)])

    def test_no_markers(self):
        self.assertEqual(fr.read_edits(str(BASE))[0]["markers"], [])

    def test_encode_is_byte_exact(self):
        with open(fr.MAP_PATH, encoding="utf-8") as f:
            cfg = fr.yaml.safe_load(f)
        for path in (MARKERS, COLORS):
            pj = entries(path)["project.xml"].decode()
            import re
            hx = re.search(r'<Sm2SequenceLockableBlob DbId="[^"]+">\s*<FieldsBlob>([0-9a-f]+)</FieldsBlob>', pj)[1]
            payload = fr.lockable_payload(bytes.fromhex(hx))
            marks = fr.decode_markers(payload, cfg["marker_colors"])
            self.assertEqual(fr._pb(payload), [(2, 2, fr.encode_markers(marks, cfg["marker_colors"]))])


MARKS = [{"frame": 86400, "color": "Green", "name": "Start"},
         {"frame": 86496, "color": "Red", "name": "BGM A", "note": "note & <xml>", "duration": 48},
         {"offset": 144, "color": "Cream", "name": "BGM B 日本語", "custom_data": "x1"}]


class ComposeMarkers(Work):
    media = {1: TONES / "tone-01.flac", 2: TONES / "tone-02.flac"}
    cuts = [{"tracks": "all", "source_in": 0, "source_out": 192, "timeline_start": 86400}]

    def compose(self, template, markers, dst=None, cuts=None):
        dst = dst or self.out()
        table = {"units": "frames", "cuts": cuts or self.cuts}
        if markers is not None:
            table["markers"] = markers
        return dst, c.compose(template, dst, self.media, table)

    def read_marks(self, path):
        return [(m["offset"], m["color"], m["name"], m["note"], m["duration"], m["custom_data"])
                for m in fr.read_edits(str(path))[0]["markers"]]

    def test_add_to_template_without_markers(self):
        dst, res = self.compose(BASE, MARKS)
        self.assertEqual(self.read_marks(dst), [(0, "Green", "Start", "", 1, ""), (96, "Red", "BGM A", "note & <xml>", 48, ""),
                                                (144, "Cream", "BGM B 日本語", "", 1, "x1")])
        self.assertTrue(res["preservation"]["mixer_byte_identical"])
        self.assertEqual(fr.load_models(str(BASE))[0]["model"], fr.load_models(str(dst))[0]["model"])

    def test_replace_existing_and_keep_when_omitted(self):
        dst, _ = self.compose(MARKERS, MARKS[:1])
        self.assertEqual(self.read_marks(dst), [(0, "Green", "Start", "", 1, "")])
        kept, _ = self.compose(MARKERS, None, self.out("kept.drp"))
        self.assertEqual(self.read_marks(kept), self.read_marks(MARKERS))
        self.assertEqual(entries(kept)["project.xml"], entries(MARKERS)["project.xml"])
        cleared, _ = self.compose(MARKERS, [], self.out("cleared.drp"))
        self.assertEqual(self.read_marks(cleared), [])
        self.assertNotIn(b"Sm2SequenceLockableBlob", entries(cleared)["project.xml"])

    def test_absolute_frames_follow_first_cut(self):
        cuts = [{"tracks": "all", "source_in": 24, "source_out": 120, "timeline_start": 86448}]
        dst, res = self.compose(BASE, [{"frame": 86448, "color": "Blue", "name": "a"}, {"frame": 86500, "color": "Sky", "name": "b"}],
                                cuts=cuts)
        self.assertEqual(res["timeline_start_frame"], 86448)
        self.assertEqual([m[0] for m in self.read_marks(dst)], [0, 52])
        self.assertEqual(fr.read_edits(str(dst))[0]["start_frame"], 86448)

    def test_invalid_markers_leave_no_output(self):
        bad = [[{"frame": 86400, "color": "Orange", "name": "x"}], [{"frame": 86400, "color": "Blue"}],
               [{"frame": 86400, "name": "x"}, {"offset": 0, "name": "y"}], [{"frame": 86399, "name": "x"}],
               [{"frame": 86400, "offset": 0, "name": "x"}], [{"offset": 0, "name": "x", "duration": 0}],
               [{"offset": 0, "name": "x", "colour": "Blue"}], "Blue"]
        for markers in bad:
            with self.subTest(markers=markers):
                dst = self.out()
                with self.assertRaises(ValueError):
                    self.compose(BASE, markers, dst)
                self.assertFalse(dst.exists())


class ComposeSeveralMedia(Work):
    def test_bgm_files_on_one_track(self):
        a = self.work / "bgm-a.flac"
        b = self.work / "bgm-b.wav"
        shutil.copy2(FORMATS / "T_FLAC16_48000_1ch-01.flac", a)
        shutil.copy2(FORMATS / "T_WAV24_48000_2ch-01.wav", b)
        cuts = {"units": "frames", "cuts": [
            {"tracks": [1, 2, 3], "source_in": 0, "source_out": 96, "timeline_start": 86400},
            {"track": 4, "source_in": 0, "source_out": 48, "timeline_start": 86400, "media": "bgm-a.flac"},
            {"track": 4, "source_in": 0, "source_out": 48, "timeline_start": 86448, "media": "bgm-b.wav", "fade_out": 12},
            {"track": 4, "source_in": 48, "source_out": 96, "timeline_start": 86496}]}
        (self.work / "cuts.json").write_text(json.dumps(cuts))
        dst = self.out()
        cmd = [sys.executable, "-m", "drpkit", "compose", str(SYNTH), str(dst), "--cuts", str(self.work / "cuts.json")]
        for t in range(1, 5):
            cmd += ["--media", "%d=%s" % (t, TONES / ("tone-%02d.flac" % t))]
        res = json.loads(subprocess.check_output(cmd, cwd=str(ROOT)))
        self.assertEqual([(e["track"], Path(e["path"]).name, e["channels"]) for e in res["extra_media"]],
                         [(4, "bgm-a.flac", 1), (4, "bgm-b.wav", 2)])
        rows = [r for r in fr.read_edits(str(dst))[0]["items"] if r["track"] == "Track 4"]
        self.assertEqual([(r["name"], r["start"], r["src_in"]) for r in rows],
                         [("bgm-a.flac", 86400, 0), ("bgm-b.wav", 86448, 0), ("tone-04.flac", 86496, 48)])
        # one new media-pool item per extra file; every clip points at an item that exists
        after = entries(dst)
        mp = after["MediaPool/Master/MpFolder.xml"].decode()
        pool = {m[1]: c.get(m[0], "Name") for m in
                [(b.group(0), __import__("re").search('DbId="([^"]+)"', b.group(0))[1]) for b in c.blocks(mp, "Sm2MpAudioClip")]}
        self.assertEqual(sorted(pool.values()), ["bgm-a.flac", "bgm-b.wav", "tone-01.flac", "tone-02.flac", "tone-03.flac", "tone-04.flac"])
        seq = next(v.decode() for k, v in after.items() if k.startswith("SeqContainer/"))
        refs = [c.get(m[0], "MediaRef") for m in c.blocks(seq, "Sm2TiAudioClip")]
        self.assertTrue(set(refs) <= set(pool))
        self.assertEqual(fr.load_models(str(SYNTH))[0]["model"], fr.load_models(str(dst))[0]["model"])
        ids = __import__("re").findall('DbId="([^"]+)"', "".join(v.decode() for v in after.values()))
        self.assertEqual(len(ids), len(set(ids)))

    def test_same_file_on_two_tracks_rejected(self):
        media = {t: TONES / ("tone-%02d.flac" % t) for t in range(1, 5)}
        table = {"units": "frames", "cuts": [{"track": 1, "source_in": 0, "source_out": 48, "timeline_start": 86400,
                                              "media": str(TONES / "tone-02.flac")}]}
        dst = self.out()
        with self.assertRaises(ValueError):
            c.compose(SYNTH, dst, media, table)
        self.assertFalse(dst.exists())

    def test_media_column_must_be_path(self):
        media = {t: TONES / ("tone-%02d.flac" % t) for t in range(1, 5)}
        for bad in (3, "@template"):
            table = {"units": "frames", "cuts": [{"track": 1, "source_in": 0, "source_out": 48, "timeline_start": 86400, "media": bad}]}
            with self.assertRaises(ValueError):
                c.compose(SYNTH, self.out(), media, table)


class CommandLine(Work):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "drpkit"] + list(args), cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")

    def test_version_and_help(self):
        import drpkit
        self.assertEqual(self.run_cli("--version").stdout.strip(), "drpkit " + drpkit.__version__)
        r = self.run_cli()
        self.assertEqual(r.returncode, 2)
        self.assertIn("compose", r.stdout)
        self.assertEqual(self.run_cli("nope").returncode, 2)

    def test_read_matches_wrapper(self):
        a = self.run_cli("read", str(MARKERS), "--edits", "--json")
        b = subprocess.run([sys.executable, str(ROOT / "fairlight_reader.py"), str(MARKERS), "--edits", "--json"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(a.returncode, 0)
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(json.loads(a.stdout)[0]["markers"][0]["name"], "Intro")

    def test_write_refuses_existing_output(self):
        dst = self.out()
        dst.write_bytes(b"KEEP")
        r = self.run_cli("write", str(BASE), str(dst), "--set", "Track1:0x001=-60")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(dst.read_bytes(), b"KEEP")

    def test_main_entry_point(self):
        self.assertEqual(cli.main(["--version"]), 0)


@unittest.skipUnless(_have_zstd(), "needs compression.zstd (Python 3.14+) or zstandard")
class Privacy(unittest.TestCase):
    def test_committed_drps_have_no_private_details(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import sanitize_drp
        files = sorted((ROOT / "tests").rglob("*.drp"))
        self.assertGreater(len(files), 40)
        for f in files:
            with self.subTest(f=f.name):
                self.assertEqual(sanitize_drp.findings(entries(f)), [])


    def _sanitizer(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import sanitize_drp
        return sanitize_drp

    def test_check_finds_private_details_in_nested_streams(self):
        sd = self._sanitizer()
        import zlib as _zlib
        _, zcomp = sd._zstd()
        user = "<User>12345678-9abc-4def-8123-456789abcdef</User>"
        secrets = {
            "linux path": b"/home/x/projects/a.wav",
            "mac path": b"/Users/someone/a.wav",
            "windows path": b"C:\\Users\\someone\\a.wav",
            "e-mail": b"someone.else@example.org",
            "user uuid": user.encode(),
        }
        for label, secret in secrets.items():
            utf16 = secret.decode().encode("utf-16-be")
            wrapped = {
                "plain": secret,
                "utf-16": utf16,
                "hex": ("<FieldsBlob>%s</FieldsBlob>" % (b"\x00\x01" + secret).hex()).encode(),
                "zlib": _zlib.compress(b"pad" + utf16),
                "qCompress in hex": ("<B>%s</B>" % (struct.pack(">I", len(utf16)) + _zlib.compress(utf16)).hex()).encode(),
                "zstd > hex > zlib": zcomp(("<X>%s</X>" % _zlib.compress(utf16).hex()).encode() * 20) + b"tail",
            }
            self.assertNotIn(_zlib.compress(utf16).hex().encode(), wrapped["zstd > hex > zlib"])
            for how, blob in wrapped.items():
                with self.subTest(label=label, how=how):
                    self.assertTrue(sd.findings({"project.xml": b"<a>" + blob + b"</a>"}), (label, how))
        clean = {"project.xml": ("<User>%s</User><SysId>000000000000</SysId><P>/tmp/rfr-fixture/a.wav</P>"
                                 % sd.PUBLIC_USER).encode()}
        self.assertEqual(sd.findings(clean), [])

    def test_sanitize_replaces_user_uuid(self):
        sd = self._sanitizer()
        text = "<x><User>fedcba98-7654-4321-8fed-cba987654321</User><UserId>-1</UserId></x>"
        out = sd.scrub_xml(text)
        self.assertEqual(out, "<x><User>%s</User><UserId>-1</UserId></x>" % sd.PUBLIC_USER)
        self.assertEqual(len(out), len(text))
        self.assertEqual(sd.findings({"project.xml": out.encode()}), [])

if __name__ == "__main__":
    unittest.main()
