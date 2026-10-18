# Fairlight data in DaVinci Resolve projects — format notes

Observed with DaVinci Resolve Studio 21.1.1. Nothing here comes from official documentation. The machine-readable source of truth for ids and conversions is `drpkit/fairlight_map.yaml`.

## Where the findings come from

| Source | Items |
|---|---|
| Prior work: [samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp) (MIT, `resolve-advanced/vendor/fairlight/index.js`) — **checked against our data** | that the mixer is stored in the `FLStudioModelBA` blob; bus channel count `0x1B4`; strip id `0x458` |
| Our own work — comparing the UI with exported projects (change one control, export, diff), and measuring renders | everything else in this document: the other channel items, built-in Dynamics conversion tables, plugin knobs, bus first part (fader, mute), track selection, edit information (clip positions, colors, fade lengths, transitions) |

## Where the mixer lives

| Container | Location |
|---|---|
| `.drp` (zip) | `MediaPool/**/MpFolder.xml` → `Sm2Timeline` → `Sm2Sequence` → `<FieldsBlob>` (hex) |
| `Project.db` (SQLite) | `Sm2Sequence.FieldsBlob`, joined via `Sm2Timeline.Sequence` to get the timeline name (`Sm2Timeline.FieldsBlob` is empty) |

`FieldsBlob` is a Qt `QDataStream` serialization of a `QVariantMap` (u32 version, u32 count, then key `QString` (UTF-16BE) + `QVariant`). The key `FLStudioModelBA` holds a `QByteArray` produced by `qCompress`: 4-byte big-endian uncompressed size followed by a zlib stream. Other keys include `SeqRef` and `ModTimeInSecs`.

## Inside FLStudioModelBA

### Channel settings tables

A run of little-endian records:

```
u32 1 | u32 item_id | u32 n_columns | n_columns × int32
```

One column per channel (a stereo track occupies two columns with the same name). Item `0xBC` is the exception: it holds `n_columns` length-prefixed UTF-8 strings — the channel names. There are several tables, told apart by their names:

| Table | Names look like |
|---|---|
| track table | the track names |
| bus table | `Bus 1`, `Bus 2`, … (starts at item `0x1D`). Its first part (fader `0x001`, mute `0x002`, pre-gain `0x019`, pan …) is stored **separately**, earlier in the blob, right after a header `u32 0, u32 7` (7 = the bus kind, same as in plugin ownership). The reader takes the last such run before the bus table whose column count equals the bus count. |
| others | `VCA…`, `Mapping…`, `Folder…` |

The reader finds every `0xBC` record, walks backwards to the start of its table, and parses forward until the record pattern breaks. If an item id appears twice in a table, the first occurrence is used.

### Plugins

Each plugin instance appears as an ASCII tag `bmd:<Name>:<ID>`.

- 12 bytes before the tag: `[kind][column][0][slot]` — kind `0` = track, `7` = bus; slot `0–5` = insert slots 1–6, `6–10` = track built-in FX (Voice Isolation, Dialogue Leveler, Dialogue Separator, Music Remixer, Ducker).
- 4 bytes before the tag: `2` for mixer-owned instances (`0`/`1` for built-in FX). Other values are templates and are ignored.
- Parameters follow until the next tag: a 64-byte zero-padded name (`Plugin::PARAM`) followed by a float32 normalized value (0–1).
- Record head, counted from the tag: a 256-byte zero-padded name field (`bmd:<Name>:<ID>`), 4 × int32 (the plugin window rectangle; all −1 until the window was opened), then a u32 **state flags** word at offset 272. For track built-in Voice Isolation (slot 6) bit `0x10` set = disabled, clear = enabled; the amount is kept while disabled. Verified with UI on/off toggles on two tracks (only that one byte changes, records 768 bytes apart) and with `Timeline.SetVoiceIsolationState` (which reports amount 0 for a disabled track although the stored amount stays). Unused built-in slots also carry `0x10`. The flags of insert plugins and of the other built-in FX are not decoded (`--all` prints them raw).

## Channel items

| Item | Id | Conversion |
|---|---|---|
| fader | `0x001` | ÷10 dB; post-dynamics. Track: −60 / −200 rendered −6.0 / −20.0 dB. Bus: in the bus table's first part; −60 / −200 / +60 rendered exactly −6.0 / −20.0 / +6.0 dB |
| bus channel count | `0x1B4` | as-is (2 = stereo) |
| strip id | `0x458` | tracks 0…n−1 (second column of a stereo track = −1), bus = number of tracks + 1 |
| track selected | `0x0AA` | 1 = the track header is selected (UI state only, no effect on sound). Selecting A1 then A2 changed `[1,0,0,0]` → `[0,1,0,0]` |
| pre-dynamics gain | `0x019` | ÷10 dB; pre-dynamics (UI name not confirmed) |
| mute | `0x002` | 1 = muted. Bus: in the bus table's first part; 1 rendered silence |
| solo | `0x011` | 1 = solo |
| pan bypass | `0x00D` | 1 = pan OFF (reported inverted as `pan_on`) |
| pan L/R | `0x004` | ÷10 = %, −100…+100 |
| Effects In | `0x01D` | 1 = on (toggled in the UI: 0 → 1) |
| EQ master switch | `0x0DF` | 1 = on (default 1; switching it off in the UI gave 0) |
| processing order | `0x0DE` | 0 EQ→DY→FX, 1 EQ→FX→DY, 2 DY→EQ→FX, 3 DY→FX→EQ, 4 FX→EQ→DY, 5 FX→DY→EQ (default); all six orders selected in the UI one by one |
| EQ band k on (k = 1…6) | `0x100+k` | 1 = on |
| EQ band k filter type | `0xF8+k` | 1 low shelf, 2 bell, 3 high shelf, 4 notch, 5 low-pass (band 6 default), 6 high-pass (band 1 default) |
| EQ band k frequency | `0xF0+k` | Hz as-is |
| EQ band k gain | `0xE0+k` | ÷10 dB |
| EQ band k Q | `0xE8+k` | Q ≈ −0.615 + 0.06567 × raw (fit to 6 UI points 0.8…5.0, all match to the displayed digit; UI range 0.3–10.3, ends not checked) |
| EQ band k range (k = 2…5) | `0x287+k` | 0 L, 1 ML, 2 MH, 3 H (H observed; defaults 0,1,2,3 for bands 2–5) |
| EQ band 1 / band 6 slope | `0x4BE` / `0x4C3` | 0 = 6, 1 = 12, 2 = 18, 3 = 24 dB/oct |
| EQ band k knob (raw) | `0x333+k` | follows the frequency (≈ 94 per natural-log unit of Hz, 0–256); probably the knob position, not used for display |
| Dynamics make-up | `0x109` | ÷10 dB |
| compressor on / threshold / knee / mix | `0x10C` / `0x10E` / `0x10F` / `0x117` | flag / ÷10 dB / as-is / as-is |
| compressor ratio / attack / hold / release | `0x10D` / `0x110` / `0x111` / `0x112` | Dynamics law (below) |
| expander on / mode / threshold / range | `0x114` / `0x11B` / `0x116` / `0x115` | flag / 0 = expander (non-zero shows gate) / ÷10 dB / ×0.6 dB |
| expander ratio | `0x253` | Dynamics law `exp_ratio` (UI `1:x`) |
| expander attack / hold / release | `0x118` / `0x119` / `0x11A` | Dynamics law |
| limiter on / threshold | `0x11D` / `0x11E` | flag / ÷10 dB |
| limiter attack / hold / release | `0x11F` / `0x120` / `0x121` | Dynamics law |
| output connected / output bus | `0x400` / `0x40B` | flag / bus index (0 = Bus 1, −1 = none) |

## Built-in Dynamics conversion

A stored value `r` uses one of two encodings, and both can appear in the same project.

| Encoding | Condition | UI value |
|---|---|---|
| legacy (templates, factory defaults) | `r ≤ 100` | knob position %; log-interpolate the `legacy` table |
| current (values set in Resolve 21) | `r ≥ 5000` | `M = (r+5) // 100` (knob position 0–1000), `d = r − 100·M` (−5…94); UI = `law[M] + d × fine` |
| out of range | `101 ≤ r ≤ 4999` | the UI field is blank |

- `fine` is 1 ms for time knobs and 0 for ratio. Values typed into the UI have so far always been stored with `d = −4` (e.g. 4.0 ms = 40496 → M = 405 (8.0 ms) − 4).
- Tables (`dyn_laws` in the map): ratio; attack (compressor and expander share it, only the minimum differs: 0.70 / 0.50 ms); limiter attack; hold (shared by compressor, expander, limiter); release (shared; equal to hold for M ≥ 200).
- `law[M]` is defined every 50 steps plus a few measured points; values in between are log-interpolated.
- How the tables were made: write values into a copy with `fairlight_writer.py`, import it into Resolve, read the Dynamics window. 23 projects × 10 knobs plus individual points; see `tests/test_dyn_law.py`.
- Blind check on 20 points that were not used to build the tables: 11 exact, 5 off by one in the last displayed digit, 3 off by 0.2–0.8 %, 1 outlier (hold at M = 165; the point was then added to the table).

## Plugin knobs

| Plugin | Parameter | Conversion |
|---|---|---|
| De-Esser | `BMDDeesser::RANGE` | 700·(9000/700)^p Hz, 3 significant digits |
| | `BMDDeesser::AMOUNT` | ×100 % |
| | `BMDDeesser::MODE` | 0 = narrow band, 0.5 = centered bell |
| | `BMDDeesser::ESS_ONLY` | flag |
| Vocal Channel | `COMP_THRES` | −40 + 40p dB |
| | `COMP_RATIO` | 1.1 + 5.9p |
| | `COMP_GAIN` | 20p dB |
| | `COMP_REACTION` | as-is |
| | `HPF_IN` / `EQ_IN` / `COMP_IN` | flags |
| Voice Isolation (track built-in FX slot 6, or clip) | `BMDVoiceIsolationControl::DRY_MIX` | ×100 = amount (37 → 0.3701, 82 → 0.8201, 55 → 0.55) |
| Dialogue Leveler (clip) | `UI_BAS_PRESET` | mode / 3 (0 allow wider dynamics, 1 optimize moderate levels, 2 more lift for low levels, 3 lift soft whispery sources) |
| | `UI_ADV_RIDER_ON` / `UI_BAS_LIFTER_ON` / `UI_BAS_CLEANER_ON` | flags: reduce loud dialogue / lift soft dialogue / background reduction |
| | `UI_BAS_OUTPUT_GAIN` | 6p dB (range 0–6 dB) |
| Limiter | `INPUT_GAIN` | −18 + 36p dB |
| | `THRESHOLD` | −24 + 24p dBTP |
| | `RELEASE` | lookup (0.8829 = 190.55 ms) |
| | `SOFT` | flag |

## Edit information (`--edits`)

| Data | `.drp` | `Project.db` | Format |
|---|---|---|---|
| clips | `SeqContainer/*.xml`, `Sm2TiAudioClip` | `Sm2TiItem` via `Sm2TiTrack` | `Start` = timeline frame; `Duration` = `integer|hex(double LE fraction)` frames; `In` = source frame (empty = 0) |
| transitions | `Sm2TiTransition` | same | `PrettyType` (e.g. Cross Fade 0dB / +3dB / −3dB), `Start`, `Duration`, `AlignmentType` (1 = starts at edit point, 2 = centered, 3 = ends at edit point); `Position` holds the same value |
| clip volume and fades | `<EffectFiltersBA>` of the clip (hex) | `Sm2TiItem.EffectFiltersBA` | `u32BE 2`, `u32BE length` (includes the flag byte), flag `0x80` = raw / `0x81` = zstd, then protobuf: repeated field 1 = effect {1: type, 9 (repeated): param {1: id, 3: {1: {2: double}}}}. Effect type 124 ("Fairlight Clip Volume and Fades"): param 95 = clip volume dB, 97 = fade in, 98 = fade out (frames) |
| clip volume keyframes | inside `EffectFiltersBA`, param 95 (clip volume) message, field 10 | same | `int32BE (−16 × count)` then per key `u32LE frame (source frame number — the clip start is the source In; verified with In = 144) · u32LE flags (0x000C0000 for UI-made keys) · double LE dB`. Linear-in-dB between keys, first value before the first key, last value after the last (verified by rendering). The static value (field 3) equals the first key in UI-made data |
| clip built-in FX (Voice Isolation, Dialogue Leveler) | the clip's own `<FieldsBlob>` | `Sm2TiItem.FieldsBlob` | same header as `EffectFiltersBA` (`0x81` = zstd); after the string `FL::ClipFX` a zlib stream holds plugin records in the track format (`bmd:<Name>:<ID>` + 64-byte names + float32). Parameter names may lack `::` (Dialogue Leveler `UI_…`). Disabling the effect removes the record, so a record means enabled |
| clip color | `project.xml`, `Sm2TiItemLockableBlob` | `BtLockableBlob` | `BlobOwner` = clip DbId; BlobData `00002711 00000003 80 28 <code>` (16 colors in `clip_colors`); no record when uncolored |
| timeline markers | `project.xml`, `Sm2SequenceLockableBlob` | `BtLockableBlob` | `BlobOwner` = the timeline's `Sm2Sequence` DbId. FieldsBlob = QVariantMap `{BlobData}`; BlobData = `00002711`, `u32BE length`, `0x80` raw / `0x81` zstd, protobuf. Field 2 = marker list: repeated field 2 = `{1: {1: zigzag(frame)}, 2: u32BE 2 · u32BE length · {1: {1: color bit, 3: note, 3: duration (decimal string, frames), 3: name, 6: customData}}}`. Frames count from the timeline start (as `Timeline.GetMarkers()`). Color bits in `marker_colors` (Blue 2 … Cream 131072; 256 unused). No record without markers. Re-encoding the four API-made exports reproduces them byte for byte |
| timeline start | `Sm2Sequence/MediaExtents` | — | two doubles LE: start seconds, span seconds. Start × fps = `Timeline.GetStartFrame()` (checked 3600 s → 86400 and 0 → 0 at 24 fps after import) |

The timeline frame rate comes from `Sm2Timeline/FrameRate` (double LE) in the `.drp`; `Project.db` output is frames only.

## Unresolved

- (solved) Fade curve: param 99 = fade-in, 100 = fade-out curve point, two big-endian doubles in field 7: `(position %, level in 0.1 dB)`. Position is measured from the start of the fade; the level is relative to the clip volume (param 95). A straight fade (linear amplitude) stores nothing. The rendered curve passes exactly through the point (checked at 25 / 50 / 75 / 78 %). With the point at 50 % the curve is the straight fade's dB curve times a constant (`(50, -20)` → −0.8 / −2.0 / −4.0 dB at 25 / 50 / 75 %, straight −2.5 / −6.0 / −12.0); for other positions the shape between the ends and the point is not modelled. The reader prints e.g. `Out カーブ点 位置49%で -2.0 dB・直線 -5.8 dB より上に凸`.
- FCPXML `fadeIn` / `fadeOut` are ignored by Resolve on import (only the clip volume comes through).
- Bus solo and bus pan items exist in the bus first part but are not verified.
- Expander ratio is item `0x253` (UI `1:x`, law `exp_ratio`): legacy 0 → 1.1, 55 → 2.1, 75 → 2.5, 100 → 3.0; legacy 10 → 1.3, 25 → 1.6, 40 → 1.8, 90 → 2.8; current encoding M = 152 → 1.3, 263 → 1.5, 400 → 1.7, 600 → 2.1, 800 → 2.5, 1000 → 2.9. All 14 points were read on the UI (8 of them after writing values with the writer); they are all in the table, so the test is not an independent check for this knob.
- Meaning of non-zero `0x11B` values beyond "shows gate".
- Plugin bypass.
- (solved) Track-level Voice Isolation on/off: bit `0x10` of the plugin record's state flags (see Plugins). The parameter registry (marker `0x77668866`) also changes, but is not needed.
- Flags of insert plugins (`2` seen on some) and of the other built-in FX.
- Track automation (fader / plugin automation lanes) and the meaning of the keyframe flags (`0x000C0000` for UI-made keys).
- Track-level Dialogue Leveler settings (not settable by the API; the track record carries no `UI_…` parameters until set in the UI).
- (solved) EQ bands: see the channel items table. The old `eq_band1_type` → `0x0DE` mapping was wrong (that item is the processing order) and has been removed.
- `0x0B9`: non-zero on exactly one track per timeline (1, 2 = channel within that track). It is **not** the track selection (`0x0AA`); meaning unknown, printed raw as `unknown_0b9`.
- `0x13B` (meaning unknown), `0x008` / `0x009` (possibly pan related).
