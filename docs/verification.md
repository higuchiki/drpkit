# Verification

Everything below was checked with **DaVinci Resolve Studio 21.1.1 on macOS**, except the section [Windows, free version 19.1.3](#windows-free-1913). Other versions, including the free version of 21.1.1, are untested. The method is always the same: change one thing (in the UI, with the scripting API, or by writing a stored value with `drpkit write`), export, compare — and where sound is involved, **render and measure**.

## Reader

| What | How |
|---|---|
| factory defaults | a new project's mixer, compared with the defaults shown in the UI and the user manual (`tests/expect_fixture_default-01.yaml`) |
| built-in Dynamics | 309 values read on the UI: a write sweep of 23 projects × 10 knobs plus individual points ([Conversions](conversions.md#built-in-dynamics)); a blind check on 20 points not used for the tables |
| writer round trip | writer → import into Resolve → export: every written value is kept (`tests/expect_fixture_roundtrip-01.yaml`) |
| fader | track −60 / −200 and bus −60 / −200 / +60 rendered −6.0 / −20.0 / +6.0 dB; bus fader −20 dB renders exactly 20.0 dB quieter; bus mute renders silence |
| EQ | type, frequency, gain, Q (6 points), range, slope set in the UI one control at a time |
| processing order | all six orders selected in the UI |
| plugin knobs | two or more UI points per linear knob plus the knob scale seen in the UI |
| track Voice Isolation on/off | toggled in the UI on two tracks and with `Timeline.SetVoiceIsolationState` |
| clip volume and fades | `SetFades` 0/0, 48/24, 100/7 and an FCPXML clip volume of −6 dB; kept after re-import |
| fade curves | rendered at curve points 25 / 50 / 75 / 78 %, plus 7 curves made in the UI |
| volume keyframes | keys made in the UI at +20 s / +25 s / +30 s 12 f; a clip with In = 144 to fix the frame origin; playback interpolation measured by rendering a synthetic tone |
| clip built-in FX | set and removed with `SetVoiceIsolationState` and `SetProperty` |
| markers | 16 colors, durations 1–24, Japanese text, XML characters and customData made with `Timeline.AddMarker`; re-encoding the four exports reproduces them byte for byte |
| timeline start | 3600 s → `GetStartFrame()` 86400 and 0 → 0 at 24 fps after import |

## Compose

| What | How |
|---|---|
| media formats | 56 composed projects covering all 28 media format combinations (WAV 16/24/32f, FLAC 16/24, AAC, MP3 × 44.1/48 kHz × mono/stereo) imported with every clip *Online* at the requested positions, In points and fades, audible on both channels |
| mixer preserved | a 4-speaker template with plugins and Dynamics, composed with cuts, a crossfade, a fade-out and keyframes, kept its mixer and matched the original's loudness section by section (0.0 LU) |
| several files on one track | mono FLAC and stereo WAV on a mono track imported *Online* with one media-pool item each |
| markers | written into a template without markers, replacing existing markers, and with absolute frames on a timeline whose first cut is not at the template start — all read back identically by `Timeline.GetMarkers()` |


## Windows, free version 19.1.3 {#windows-free-1913}

Windows 11, DaVinci Resolve 19.1.3 (build 7, free version), Python 3.10.6. Results apply to this version only; they are not a statement about the free version in general or about 21.1.1.

| What | Result |
|---|---|
| read, `write`, `compose` | exports read; written and composed projects imported. Fixes made for this setup: UTF-8 command line output (was `UnicodeEncodeError` on CP932), Resolve 19 marker format, unnamed tracks as `@A1` / `@A2`, bus fader position |
| EQ frequency (`--eq-freq`) | 18 whole-Hz settings imported and exported again: 17 came back exactly. Bus band 5 at 1399 Hz became 1392 Hz; entering 1399 Hz in the UI, saving and reloading gives the same result. The rule behind it is not known, so use `--verify-eq` on the re-export |
| fader | −6 dB rendered as −6.000001 dB |
| EQ gain vs. type | 440 Hz, Q 2, +6 dB rendered +8.108108 dB with the *Fire* type and +6.000000 dB with *Earth*; only the type differed. This is the EQ type's response, not a write error. Fix the type when you compare gain |
| compressor Mix | −30 dB, 3:1, makeup 0: Mix 0 rendered compressed audio only. Mix 50 / 75 / 100 matched `Mix0 audio + (Mix/100)² × unprocessed audio` within one 24-bit step in two separate windows; Mix 100 measured +3.028825 dB. Mix is not a wet percentage, but the `.drp` stores the UI value as it is — write the UI value, do not invert or square it |

The renders used a steady 440 Hz tone, with the right channel silent in the original routing. They do not cover audio in general, every setting, left/right behaviour or listening quality. Not decoded: Dialogue Leveler and other items listed in [Unresolved](unresolved.md); writing a `Project.db` directly is not supported.

## Automated tests {#automated-tests}

```bash
python3 -m unittest discover -s tests -t . -v
```

GitHub Actions runs them on Ubuntu, macOS and Windows with Python 3.9 and 3.12 (tests that need a local Resolve 19 export are skipped there), plus a privacy scan of every committed `.drp`. The compose tests need `ffmpeg` / `ffprobe`.

| Test | What it checks |
|---|---|
| `test_dyn_law` | Dynamics conversion vs. values read on the Resolve UI |
| `test_fixtures` | reader defaults and round trip, fades, bus fader, writer (only requested cells change, refuses to overwrite, no output and no temporary file left on error, `--timeline` with several timelines) |
| `test_drp_compose` | composition: reader round trip, mixer and archive preserved byte for byte, media metadata for 28 formats against Resolve's own exports, invalid cut lists rejected without output, written file read back and checked against the cut table (a tampered Duration / In / media path / crossfade is refused), no file left on a failed write, crossfade handles, keyframes, clip FX inheritance |
| `test_markers_media_cli` | track Voice Isolation on/off, markers (read, byte-exact re-encode, compose add / replace / keep / clear, invalid input), several media files per track, the `drpkit` command line, and the privacy scan itself |

The docs build checks that the generated tables match `drpkit/fairlight_map.yaml` (`python tools/gen_map_docs.py --check`).

## Fixtures

Fixtures are synthetic: new Resolve projects with generated sine tones. **No real projects or recordings are included**, and fixtures carry only `.drp` exports — imported into Resolve their media shows as offline (the tests do not need it).

Before a `.drp` is committed it goes through `tools/sanitize_drp.py`, which neutralizes the machine id, the Resolve user UUID (replaced by a fixed public one) and the absolute paths Resolve stores in the project settings; `tools/sanitize_drp.py --check` must report nothing. The check looks for home / volume paths (macOS, Linux, Windows), any e-mail address, machine ids and user UUIDs, also inside hex blobs and zlib / zstd streams, unpacked recursively.

To relink the first fixtures in Resolve, generate the two files (10 s, 48 kHz, mono, 16-bit) at the paths the project expects:

```bash
mkdir -p /tmp/rfr-fixture
ffmpeg -f lavfi -i "sine=frequency=1000:sample_rate=48000:duration=10" -ac 1 -c:a pcm_s16le /tmp/rfr-fixture/sine1k.wav
ffmpeg -f lavfi -i "anullsrc=r=48000:cl=mono" -t 10 -c:a pcm_s16le /tmp/rfr-fixture/silence.wav
```

## Limits of the evidence

- Calibration tables (※) checked against the same Resolve version they were built from are circular; the independent evidence is the blind check and renders.
- A byte-identical mixer is not the same as identical sound in every case; the loudness comparison covers one template.
- Everything may change in any Resolve release.
