# Media

How an audio file in the media pool is recorded, and what `compose` writes when it points a template's media-pool item at your file. Values are read with `ffprobe`; nothing is guessed — unsupported files are refused.

## Supported formats {#supported-formats}

| Container | `ffprobe` codec | Bit depth | `CodecName` | `BitDepth` | Clip field 18 (format flags) |
|---|---|---|---|---|---|
| WAV | `pcm_s16le` | 16-bit | `Linear PCM` | 1 | 32768 (`0x8000`) |
| WAV | `pcm_s24le` | 24-bit | `Linear PCM` | 2 | 32768 (`0x8000`) |
| WAV | `pcm_f32le` | 32-bit float | `Linear PCM` | 3 | 32768 (`0x8000`) |
| FLAC | `flac` | 16-bit | `FLAC` | 1 | 32778 (`0x800A`) |
| FLAC | `flac` | 24-bit | `FLAC` | 2 | 32778 (`0x800A`) |
| M4A | `aac` (profile LC) | — | `AAC` | 3 | 32772 (`0x8004`) |
| MP3 | `mp3` | — | `MP3` | 3 | 32776 (`0x8008`) |

- **`BitDepth`: 1 = 16-bit, 2 = 24-bit, 3 = 32-bit float.** Compressed formats are stored as 3.
- Sample rate 44100 or 48000 Hz; 1 or 2 channels; exactly one audio stream.
- Anything else (other codecs, 8/32-bit integer PCM, other rates, more channels, video files) is rejected.

## The media-pool item (`Sm2MpAudioClip`)

In `MediaPool/**/MpFolder.xml`:

| Field | Encoding | Content |
|---|---|---|
| `Name` | text | file name |
| `UniqueMediaPoolItemId` | UUID | item id; a fresh one for each extra media file `compose` adds |
| `Clip` | [versioned blob](file-format.md#versioned-blob), protobuf | file location and format (below) |
| `TracksBA` | QDataStream | per-stream audio description (below) |
| `FieldsBlob` | versioned blob, protobuf | embedded audio info (below) |
| `EmbeddedAudioVec` → `BtAudioInfo` | XML | the embedded audio stream record (`DbId` referenced from the channel mapping) |
| `VirtualAudioTracksBA` | hex | virtual audio track layout |

### `Clip` (protobuf)

| Field | Type | Content |
|---|---|---|
| 1 | text | folder of the file |
| 2 | text | file name |
| 3 | text | modification time, C `ctime` format (`Sun Oct 18 17:34:12 2026`) |
| 5 | text | codec name (`Linear PCM`, `FLAC`, `AAC`, `MP3`) |
| 13 | varint | modification time, microseconds since the epoch |
| 15, 16 | varint | not decoded (kept) |
| 18 | varint | format flags (table above) |

### `TracksBA` (QDataStream)

A `QVariantMap` with one key, `"0"`, whose `QByteArray` value is a nested `QVariantMap` describing the first audio stream:

| Key | Content |
|---|---|
| `UniqueId` | stream id |
| `DbType` | `BtAudioTrack` |
| `IdxTrack` | stream index (0) |
| `StartTime` | 0.0 |
| `SampleRate` | Hz |
| `NumChannels` | 1 or 2 |
| `Duration` | length in **samples** |
| `CodecName` | as in `Clip` field 5 |
| `BitDepth` | 1 / 2 / 3 |
| `ChannelLayout` | channel layout; present when `ffprobe` reports `mono` / `stereo` |

### `FieldsBlob` (protobuf)

Field 1 → field 5 holds the embedded audio info, again as a one-entry `QVariantMap` around a nested map:

| Key | Content |
|---|---|
| `MediaExtents` | two little-endian doubles: 0 and the duration in seconds |
| `CodecName` | codec name |
| `SampleRate` | Hz — **omitted at 48000** |
| `BitDepth` | 1 / 2 — **omitted for 3** (32-bit is the default in every capture) |
| `Type` | 0 for stereo; omitted for mono |
| `ChannelVecBA` | channel mapping: a map `{"0": {MediaRef}, "1": {MediaRef, ChannelIdx: 1}}`, one entry per channel, `MediaRef` = the `BtAudioInfo` `DbId` |

## Durations

- `Duration` (samples) is the stream's `duration_ts × time_base × rate` (or `duration × rate`).
- **MP3**: Resolve counts all encoded MP3 frames, unlike `ffprobe`'s gapless duration, so drpkit sums the packet durations instead.
- `source_out` in the cut list may not exceed the shorter of the two durations (stored length and playable content).

## Channel changes

When the new file has a different channel count than the template's media (mono ↔ stereo), `compose` also rewrites `NumChannels`, `ChannelVecBA`, `Type` and each clip's `VirtualAudioTrackBA` (`ChannelsBA` = `u32BE 2, count` + `0x4001 + i` per channel; `AudioType` 1 for mono, 0 for stereo). It does so only when the template uses Resolve's default channel mapping; otherwise the change is refused.

## Several files on one track

A cut row with its own `media` creates a new media-pool item, cloned from the track's template item under fresh ids (item `DbId`, embedded `BtAudioInfo` `DbId` — also renamed inside the channel mapping, where it is stored as UTF-16 — and `UniqueMediaPoolItemId`), then filled with that file's metadata. The same file on two tracks, and one media-pool item shared by two template tracks, are refused.

## Verification

Media metadata for all 28 combinations (WAV 16/24/32f, FLAC 16/24, AAC, MP3 × 44.1/48 kHz × mono/stereo) is compared field by field with Resolve's own exports of the same files (`tests/compose/formats/`). 56 composed projects covering all 28 combinations were imported into Resolve 21.1.1 with every clip *Online* at the requested positions, In points and fades, audible on both channels.
