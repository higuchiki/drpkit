# .drp and Project.db

Observed with DaVinci Resolve Studio 21.1.1. Nothing here comes from official documentation.

A Resolve project exists in two forms that hold the same records:

| Form | What it is | drpkit |
|---|---|---|
| `.drp` | *File → Export Project*: a zip archive of XML files | read, write, compose |
| `Project.db` | a project inside a disk-database project library: one SQLite file per project | read only |

## .drp: the zip archive

| Entry | Holds |
|---|---|
| `project.xml` | project settings and the `LocableBlobSet` (sic) of lockable blobs: clip colors (`Sm2TiItemLockableBlob`) and timeline markers (`Sm2SequenceLockableBlob`) |
| `MediaPool/<folder path>/MpFolder.xml` | one per media-pool folder: media-pool items (`Sm2MpAudioClip`, …) and timelines (`Sm2MpTimelineClip` → `Sm2Timeline` → `Sm2Sequence`) |
| `SeqContainer/<uuid>.xml` | one per timeline: `Sm2SequenceContainer` with the tracks (`Sm2TiTrack`) and their items |
| `Gallery.xml` | color page stills (not read) |

Element names in the XML are the database table names (`Sm2…`, `Bt…`); each record carries a `DbId` attribute (a UUID) that other records reference.

### Timeline records (MpFolder.xml)

| Element | Field | Meaning |
|---|---|---|
| `Sm2Timeline` | `Name` | timeline name |
| | `Sequence` | `DbId` of its `Sm2Sequence` |
| | `FrameRate` | timeline frame rate, **hex of a little-endian double** (the first 16 hex digits) |
| `Sm2Sequence` | `FieldsBlob` | hex of a QDataStream `QVariantMap` (below) — holds `FLStudioModelBA`, the Fairlight mixer |
| | `MediaExtents` | hex of two little-endian doubles: start seconds and span seconds. Start × fps = `Timeline.GetStartFrame()` |

### Tracks and items (SeqContainer/*.xml)

```text
Sm2SequenceContainer
 ├ VideoTrackVec / AudioTrackVec
 │   └ Element → Sm2TiTrack   Type (1 = audio), UserDefinedName, Sequence, Items
 │        └ Items → Element → Sm2TiAudioClip | Sm2TiTransition | …
 └ Sequence  (DbId of the Sm2Sequence, links the container to its timeline)
```

The fields of clips and transitions are listed in [Clips & edits](clips-edits.md).

## Project.db: the SQLite database

drpkit opens it with `file:<path>?mode=ro&immutable=1` (no lock, no write, no journal). The same records are tables; column names match the XML element names.

| Table | Columns used | Meaning |
|---|---|---|
| `Sm2Timeline` | `Name`, `Sequence`, `FieldsBlob` | timelines. `FieldsBlob` is **empty** here |
| `Sm2Sequence` | `Sm2Sequence_id`, `FieldsBlob` | the timeline's sequence; `FieldsBlob` holds `FLStudioModelBA` |
| `Sm2TiTrack` | `Sm2TiTrack_id`, `Sequence`, `Type`, `UserDefinedName` | tracks of a sequence |
| `Sm2TiItem` | `Sm2TiItem_id`, `Sm2TiTrack_id`, `DbType`, `Name`, `PrettyType`, `Start`, `Duration`, `In`, `AlignmentType`, `Position`, `EffectFiltersBA`, `FieldsBlob` | clips and transitions; `DbType` is the XML element name (`Sm2TiAudioClip`, `Sm2TiTransition`) |
| `BtLockableBlob` | `BlobOwner`, `FieldsBlob` | clip colors and timeline markers (one table for both) |

Joins:

```sql
-- mixer: timeline name + its Fairlight model
SELECT t.Name, s.FieldsBlob
  FROM Sm2Sequence s JOIN Sm2Timeline t ON t.Sequence = s.Sm2Sequence_id;

-- clips and transitions of one timeline, in track order
SELECT k.Type, k.UserDefinedName, i.DbType, i.Sm2TiItem_id, i.Name, i.PrettyType, i.Start, i.Duration,
       i."In", i.AlignmentType, i.Position, i.EffectFiltersBA, i.FieldsBlob
  FROM Sm2TiItem i JOIN Sm2TiTrack k ON i.Sm2TiTrack_id = k.Sm2TiTrack_id
 WHERE k.Sequence = :sequence ORDER BY k.rowid, i.Start;

-- colors (BlobOwner = Sm2TiItem_id) and markers (BlobOwner = Sm2Sequence_id)
SELECT FieldsBlob, BlobOwner FROM BtLockableBlob WHERE FieldsBlob IS NOT NULL;
```

`Project.db` has no frame rate in the tables drpkit reads, so `--edits` from a database reports frames only (no timecode, no absolute marker frames).

## Encodings

Four container formats appear inside these fields.

### QDataStream `QVariantMap` (`FieldsBlob`)

Qt's big-endian serialization:

```text
u32 version | u32 count | count × ( key: QString, value: QVariant )
QString  = u32 byte length (0xFFFFFFFF = null) + UTF-16BE
QVariant = u32 type id + u8 null flag + value
```

| Type id | Value |
|---|---|
| 1 | bool (1 byte) |
| 2 / 3 | int32 / uint32 (BE) |
| 4 / 5 | int64 / uint64 (BE) |
| 6 | double (BE) |
| 8 | nested `QVariantMap` (u32 count + entries) |
| 9 | `QVariantList` (u32 count + QVariants) |
| 10 | QString |
| 11 | `QStringList` |
| 12 | `QByteArray` (u32 length, 0xFFFFFFFF = null, + bytes) |

The `Sm2Sequence` `FieldsBlob` has keys such as `FLStudioModelBA`, `SeqRef`, `ModTimeInSecs`, `FirstMainBusFormat`, `Thumbnail`.

### qCompress (`FLStudioModelBA`)

`FLStudioModelBA` is a `QByteArray` produced by Qt's `qCompress`: a 4-byte big-endian uncompressed size followed by a zlib stream. Its content is described in [Fairlight model](fairlight-model.md).

### Versioned blob (`EffectFiltersBA`, clip `FieldsBlob`, media `Clip` / `FieldsBlob`) {#versioned-blob}

```text
u32BE 2 (version) | u32BE length (includes the flag byte) | u8 flag | payload
flag 0x80 = payload stored as-is, 0x81 = payload compressed with zstd
```

The payload is a protobuf message (field numbers and wire types, no schema). Resolve writes most of these zstd-compressed; drpkit writes `0x80`, which Resolve accepts. Reading `0x81` needs Python 3.14+ (`compression.zstd`) or the `zstandard` package.

### Lockable blob (`Sm2…LockableBlob` / `BtLockableBlob`) {#lockable-blob}

`FieldsBlob` is a `QVariantMap` with one key, `BlobData` (a `QByteArray`):

```text
u32BE 0x00002711 | u32BE length (includes the flag byte) | u8 flag (0x80 raw / 0x81 zstd) | protobuf
```

Clip colors store a fixed 3-byte payload (`80 28 <code>`), markers a protobuf list — see [Clips & edits](clips-edits.md#clip-colors).

### Protobuf

Standard protobuf wire format: varint keys `field << 3 | wiretype`; wire type 0 = varint, 1 = 8 bytes, 2 = length-delimited, 5 = 4 bytes. Signed positions use zigzag encoding. Inside the length-delimited fields Resolve mixes little-endian values (doubles of scalar knobs, keyframe records) and big-endian ones (fade curve points, nested length headers) — each is noted where it occurs.
