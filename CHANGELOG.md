# Changelog

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
