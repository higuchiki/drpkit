# Clips & edits

What `drpkit read --edits` reads and `drpkit compose` writes: clips, clip volume and fades, keyframes, transitions, clip colors, clip built-in FX and timeline markers. All positions are **frames at the timeline frame rate**.

| Data | `.drp` | `Project.db` |
|---|---|---|
| clips, transitions | `SeqContainer/*.xml`: `Sm2TiAudioClip`, `Sm2TiTransition` | `Sm2TiItem` via `Sm2TiTrack` |
| clip volume, fades, keyframes | the clip's `<EffectFiltersBA>` (hex) | `Sm2TiItem.EffectFiltersBA` |
| clip built-in FX | the clip's own `<FieldsBlob>` | `Sm2TiItem.FieldsBlob` |
| clip colors | `project.xml`: `Sm2TiItemLockableBlob` | `BtLockableBlob` |
| timeline markers | `project.xml`: `Sm2SequenceLockableBlob` | `BtLockableBlob` |
| timeline start | `Sm2Sequence/MediaExtents` | — |
| frame rate | `Sm2Timeline/FrameRate` (double LE) | — (frames only) |

## Clip records

| Field | Meaning |
|---|---|
| `Name` | clip name (the media file name for audio) |
| `Start` | timeline frame of the clip start (integer) |
| `Duration` | `integer|hex(double LE)` — whole frames, then the fractional part as a little-endian double, e.g. `16816|00009a999999e93f`. Plain numbers also occur |
| `In` | source frame of the clip start; empty = 0 |
| `MediaRef` | `DbId` of the media-pool item (`Sm2MpAudioClip`) |
| `MediaFilePath` | absolute path of the media file |
| `MediaTimemapBA` | `02` + big-endian double: media duration − one frame, in seconds (as written by `compose`) |
| `EffectFiltersBA` | clip volume, fades, keyframes (below) |
| `FieldsBlob` | clip built-in FX (below) |
| `VirtualAudioTrackBA` | channel mapping of the clip |

The reader reports `end = start + duration`, `src_out = src_in + duration`, and the timecode of `start` (`.drp` only).

## Clip volume and fades: `EffectFiltersBA`

A [versioned blob](file-format.md#versioned-blob) (`u32BE 2`, `u32BE length`, flag `0x80` / `0x81` zstd) whose payload is protobuf:

```text
field 1 (repeated) = effect
    1: effect type (varint)
    9 (repeated) = parameter
        1: parameter id (varint)
        3: { 1: { 2: double LE  (static value)
                  7: big-endian doubles  (curve points) } }
        10: keyframes (bytes, below)
```

Effect type **124** is “Fairlight Clip Volume and Fades”:

--8<-- "map_clip_effects.en.md"

| Param | Meaning | Unit |
|---|---|---|
| 95 | clip volume | dB |
| 97 / 98 | fade in / fade out length | frames (double) |
| 99 / 100 | fade in / fade out curve point | see [Fade curves](#fade-curves) |

Checked with `SetFades` 0/0, 48/24 and 100/7 and an FCPXML clip volume of −6 dB; the values survive re-import of the `.drp`. Note: `Project.ExportProject` writes the last **saved** state — save after `SetFades` before exporting.

## Volume keyframes

Inside the param 95 (clip volume) message, field 10:

```text
int32BE (−16 × count)
count × ( u32LE frame | u32LE flags | double LE dB )
```

- `frame` is the **source frame number**: the clip start is the source In. Verified with a clip whose In is 144: keys at source 24 / 48 left the whole clip at the last value; keys at source 168 / 192 took effect at clip +1 s / +2 s.
- `flags` is `0x000C0000` for keys made in the UI (probably the interpolation type; not decoded). `compose` writes the same value.
- Playback, verified by rendering: linear in dB between keys, the first value before the first key, the last value after the last.
- The static value (field 3) equals the first key in UI-made data.
- UI-made keys at 24 fps: +20 s → 480, +25 s → 600, +30 s 12 f → 732; values −3 / −15 / +6 dB.

## Fade curves {#fade-curves}

Params 99 (fade in) and 100 (fade out) hold one curve point: two big-endian doubles in field 7, **(position %, level in 0.1 dB)**.

- Position is measured from the start of the fade; the level is relative to the clip volume (param 95).
- A straight fade (linear amplitude) stores **nothing** for 99 / 100.
- The rendered curve passes exactly through the point (checked at 25 / 50 / 75 / 78 %).
- With the point at 50 % the curve is the straight fade's dB curve times a constant: `(50, −20)` gives −0.8 / −2.0 / −4.0 dB at 25 / 50 / 75 %, where the straight fade gives −2.5 / −6.0 / −12.0. For other positions the shape between the ends and the point is **not modelled**.
- The reader prints e.g. `Out カーブ点 位置49%で -2.0 dB・直線 -5.8 dB より上に凸` (Out curve point: −2.0 dB at 49 %, above the straight fade's −5.8 dB, i.e. convex).
- `compose` writes straight fades only; with `--keep-clip-fx` an inherited curve point is cleared.

FCPXML `fadeIn` / `fadeOut` are ignored by Resolve on import (only the clip volume comes through).

## Transitions

`Sm2TiTransition` items on the track, between the clips:

| Field | Meaning |
|---|---|
| `PrettyType` | e.g. `Cross Fade 0DB`, `Cross Fade +3dB`, `Cross Fade -3dB` |
| `Start` | timeline frame of the transition start |
| `Duration` | length in frames |
| `AlignmentType` | below; `Position` holds the same value |

--8<-- "map_alignment.en.md"

`compose` writes `Cross Fade 0DB`, centered (`AlignmentType` 2), starting `crossfade/2` frames before the joint. The transition body (`FieldsBlob`) is the constant taken from a Resolve 21.1.1 export; it contains no clip references.

## Clip colors {#clip-colors}

One `Sm2TiItemLockableBlob` (`.drp`) / `BtLockableBlob` row (`Project.db`) per colored clip; **no record** when the clip has no color.

- `BlobOwner` = the clip's `DbId` / `Sm2TiItem_id`.
- `BlobData` = `00002711 00000003 80 28 <code>`: the lockable header, length 3, flag `0x80`, then protobuf field 5 (`0x28`) = color code.

--8<-- "map_clip_colors.en.md"

## Clip built-in FX {#clip-built-in-fx}

Voice Isolation and Dialogue Leveler set on a clip live in the clip's own `FieldsBlob`:

1. a versioned blob (`u32BE 2`, length, `0x80` / `0x81` zstd), payload protobuf;
2. after the ASCII string `FL::ClipFX`, a zlib stream (`78 9C …`);
3. inside it, plugin records in the track format: `bmd:<Name>:<ID>` + 64-byte parameter names + float32 normalized values. Parameter names may lack `::` (Dialogue Leveler `UI_…`).

Disabling the effect **removes the record**, so a record means enabled. Checked with the API `SetVoiceIsolationState` and `SetProperty`. Conversions: [Plugins](plugins.md). `compose` builds every new clip of a track from the template's earliest clip on that track and copies its `FieldsBlob` as is, so its clip built-in FX carry over to every new clip — with or without `--keep-clip-fx` (that option is about `EffectFiltersBA`: clip volume, keyframes and other effects).

## Timeline markers

One `Sm2SequenceLockableBlob` (`.drp`) / `BtLockableBlob` row (`Project.db`) per timeline that has markers; **no record** without markers.

- `BlobOwner` = the timeline's `Sm2Sequence` `DbId`.
- `FieldsBlob` = `QVariantMap {BlobData}`; `BlobData` = `00002711`, `u32BE length`, `0x80` raw / `0x81` zstd, protobuf.
- Protobuf field 2 = the marker list (other fields of the message are kept verbatim by `compose`):

```text
field 2 (repeated) = marker
    1: { 1: zigzag(frame) }           frame from the timeline start (omitted when 0)
    2: u32BE 2 | u32BE length | {
         1: {
           1: color bit (varint)
           3: note      (text)
           3: duration  (decimal string, frames)
           3: name      (text)
           6: customData (text, optional)
         } }
```

The three field-3 strings are, in order, note, duration and name. Frames count from the timeline start, as `Timeline.GetMarkers()` returns them; the reader also reports the absolute frame (`offset + start frame`, `.drp` only).

--8<-- "map_marker_colors.en.md"

Bit 256 is unused. Verified with markers made by `Timeline.AddMarker` in all 16 colors, durations 1–24, Japanese text, XML characters and customData; re-encoding the four API-made exports reproduces them **byte for byte**.

## Timeline start

`Sm2Sequence/MediaExtents` holds two little-endian doubles: start seconds and span seconds. Start × fps = `Timeline.GetStartFrame()` (checked: 3600 s → 86400 and 0 → 0 at 24 fps after import). `compose` sets it to the first and last cut.
