# Cut list format

The cut list tells `drpkit compose` which parts of which audio go where. It is JSON, or CSV with the same column names (CSV has no `markers`).

## Units

- All values are **integer frames at the timeline frame rate** (the template timeline's `FrameRate`). `"units": "frames"` is required in JSON; seconds, timecode and sub-frames are not accepted.
- `source_in` is inclusive, `source_out` is **exclusive** (the clip is `source_out − source_in` frames long).
- `timeline_start` is the **absolute** timeline frame: a timeline starting at 01:00:00:00 at 24 fps begins at 86400.
- The output timeline starts at the earliest cut (`min(timeline_start)`).

## Example (JSON)

```json
{"units": "frames",
 "cuts": [
  {"tracks": [1, 2],  "source_in": 0,    "source_out": 3600,  "timeline_start": 86400},
  {"tracks": [1, 2],  "source_in": 7200, "source_out": 10800, "timeline_start": 90000, "crossfade": 60},
  {"track": 3,        "source_in": 0,    "source_out": 1200,  "timeline_start": 86400, "media": "bgm/intro.wav"},
  {"track": 3,        "source_in": 0,    "source_out": 2400,  "timeline_start": 87600, "media": "bgm/loop.flac",
   "fade_out": 48, "volume_keyframes": [[0, -12.0], [1200, -18.0]]},
  {"tracks": "all",   "source_in": 18000, "source_out": 19800, "timeline_start": 93600, "fade_out": 60, "color": "Orange"}
 ],
 "markers": [
  {"frame": 86400, "color": "Blue", "name": "Opening"},
  {"frame": 90000, "color": "Red",  "name": "Topic 2", "note": "check levels", "duration": 48},
  {"offset": 7200, "color": "Green", "name": "Ending", "custom_data": "any text"}
 ]}
```

## Cut columns

| Column | Required | Type | Meaning |
|---|---|---|---|
| `track` / `tracks` | yes (one of them) | int / list of int / `"all"` | 1-based audio track index (template order). A row with several tracks becomes one clip on each |
| `source_in` | yes | int ≥ 0 | first source frame |
| `source_out` | yes | int > `source_in` | source frame after the last one (exclusive). Must not exceed the media length |
| `timeline_start` | yes | int ≥ 0 | absolute timeline frame of the clip start |
| `media` | no | path | this cut's own audio file (for example several BGM files on one track). Relative paths are relative to the cut list file. Empty = the track's `--media`. Each extra file becomes a new media-pool item; the same file may not be used on two tracks. `@template` is not allowed here |
| `fade_in`, `fade_out` | no | int ≥ 0 | fade lengths in frames; `fade_in + fade_out` must not exceed the clip length. Fades are linear (no curve point) |
| `crossfade` | no | even int | Cross Fade 0 dB transition of this many frames, **centered** on the joint with the directly preceding cut on that track. Needs source handles of `crossfade/2` on both sides, the two cuts must touch exactly, and there must be no fade at that joint |
| `volume_keyframes` | no | `[[source frame, dB], ...]` | clip volume keyframes. Frames are **source** frame numbers (the clip starts at `source_in`). Linear in dB between keys; the first value holds before the first key, the last after the last. In CSV, write the JSON list as text |
| `color` | no | name | one of the 16 clip colors: Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate |

Any other column is an error. Clips on one track may not overlap; use adjacent cuts and `crossfade` instead.

## Markers (JSON only)

| Key | Required | Meaning |
|---|---|---|
| `frame` **or** `offset` | exactly one | `frame` = absolute timeline frame (same scale as `timeline_start`, must not be before the first cut); `offset` = frames from the timeline start (what `Timeline.GetMarkers()` returns) |
| `name` | yes | marker name (Resolve does not create unnamed markers) |
| `color` | no | Blue (default), Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream |
| `note`, `custom_data` | no | text |
| `duration` | no | frames ≥ 1, default 1 |

- Without `markers` the template's markers are kept as they are; with `markers` they are replaced; `"markers": []` removes them.
- Two markers at the same frame are refused.

## CSV

```csv
track,source_in,source_out,timeline_start,fade_in,fade_out,crossfade,color,media,volume_keyframes
1,0,3600,86400,,,,,,
2,0,3600,86400,,,,,,
1,7200,10800,90000,,,60,,,
3,0,1200,86400,,24,,Orange,bgm/intro.wav,"[[0,-12.0],[600,-18.0]]"
```

- Header row with the column names above; UTF-8 (a BOM is accepted). `units` is implied (`frames`).
- Use either a `track` column or a `tracks` column, not both. In CSV a cell holds one track number (repeat the row for each track) or, in a `tracks` column, `all`.
- Empty cells mean "not set".

## Validation

The cut list is checked completely before anything is written. Refused, with no output file:

- `units` missing or not `frames`; unknown columns; both `track` and `tracks`; unknown track index
- non-integer, negative, empty or reversed cuts; fades longer than the clip
- `source_out` beyond the media; overlapping clips on one track
- an odd `crossfade`, a crossfade without an adjacent preceding cut, without source handles, or together with a fade at that joint
- an unknown clip or marker color; a marker without name, with both or neither of `frame` / `offset`, before the timeline start, or two markers at one frame

After writing, the temporary file is read back with the reader and every audio clip and crossfade is compared with the cut table (track, order, position, source In/Out, fades, volume keyframes, color, media file).
