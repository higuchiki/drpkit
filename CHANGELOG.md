# Changelog

## Unreleased

### Added
- `write --eq-freq NAME:BAND=HZ`: set an EQ band frequency in whole Hz; the linked knob and range items are written in
  the same request. Fractional, out-of-range and conflicting raw `--set` requests are refused.
- `write --verify-eq`: read-only check of a re-export from Resolve against `--eq-freq` requests (exit 0 match,
  1 mismatch, 2 invalid arguments). Resolve can change a value on import (free version 19.1.3: 1399 Hz → 1392 Hz).
- `@A1` / `@A2` selectors for unnamed tracks (by strip id), including stereo continuation columns.
- `read`: Resolve 19 timeline marker format, alongside the 21 format; unnamed edit tracks shown as `@A1` etc.
- GitHub Actions: Windows added to the test matrix (Ubuntu, macOS, Windows × Python 3.9, 3.12).
- Checked with the free version DaVinci Resolve 19.1.3 (build 7) on Windows 11 with Python 3.10.6 — see Verification.
  Other free versions, including 21.1.1, are untested.

### Fixed
- `read --edits`: Start / Duration / In stored as `frames|hex double` (fractional frames, e.g. a 24 fps clip on a 60 fps timeline) no longer raise `ValueError`; fractions are kept, Project.db items are ordered by numeric start.
- Windows: command line output is UTF-8 (was `UnicodeEncodeError` on CP932); tests read output as UTF-8.
- Bus fader position lookup in `write`; the post-write check keys cells by table number, so unnamed tables no longer collide.
- `write` refuses an EQ band 2–5 Hz write without the matching knob and range items (Resolve ignores Hz alone).

### Added (docs)
- Documentation site (MkDocs Material, English and Japanese) at https://higuchiki.github.io/drpkit/ : CLI reference,
  cut list, `.drp` / `Project.db` structure, Fairlight model with every item, conversions, plugins, clips and edits,
  media, unresolved items, verification. Item tables are generated from `drpkit/fairlight_map.yaml`
  (`tools/gen_map_docs.py`). Deployed by GitHub Actions.

## 0.1.0 — 2026-10-18

First packaged release. Checked with DaVinci Resolve Studio 21.1.1 (macOS).

### Added
- Python package `drpkit` (Python 3.9+, PyYAML; optional `zstandard`) with one command, `drpkit read | write | compose`.
  `fairlight_reader.py`, `fairlight_writer.py` and `drp_compose.py` remain as thin compatibility wrappers.
- `read`: track built-in Voice Isolation on/off (`Voice Isolation.enabled`), from the plugin record's state flags (bit `0x10`).
  `--all` also prints the raw state flags of other plugins.
- `read --edits`: timeline markers (frame, offset from the timeline start, 16 colors, name, note, duration, customData)
  and the timeline start frame.
- `compose`: a `media` column in the cut list — several audio files on one track (for example BGM), each becoming its own
  media-pool item.
- `compose`: `markers` in the cut list — write, replace or clear timeline markers (absolute `frame` or `offset`).
- `tools/sanitize_drp.py`: neutralize the machine id and stored absolute paths before committing a `.drp` fixture;
  `--check` reports anything left.
- GitHub Actions: unit tests on Ubuntu and macOS with Python 3.9 and 3.12, plus the privacy scan.

### Changed
- The item map moved from `configs/fairlight_map.yaml` to `drpkit/fairlight_map.yaml` (package data).
- All committed `.drp` fixtures were re-sanitized: the machine id and the absolute paths in the project settings are
  replaced; everything the tests use is unchanged.

### Not decoded yet
Track-level Dialogue Leveler settings, track automation lanes, keyframe flags, item `0x0B9`, plugin bypass, bus solo.
