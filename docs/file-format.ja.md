# .drp と Project.db

DaVinci Resolve Studio 21.1.1 で観察した内容です。公式資料に基づくものはありません。

Resolve のプロジェクトには、同じ記録を持つ2つの形があります。

| 形 | 中身 | drpkit |
|---|---|---|
| `.drp` | *ファイル → プロジェクトの書き出し* で作る、XML ファイルの zip | 読み・書き・compose |
| `Project.db` | ディスクDB方式のプロジェクトライブラリ内のプロジェクト。1プロジェクト1つの SQLite ファイル | 読み取りのみ |

## .drp：zip の中身

| エントリ | 持っているもの |
|---|---|
| `project.xml` | プロジェクト設定と、ロック可能ブロブの集合 `LocableBlobSet`（綴りは原文どおり）：クリップ色（`Sm2TiItemLockableBlob`）とタイムラインマーカー（`Sm2SequenceLockableBlob`） |
| `MediaPool/<フォルダのパス>/MpFolder.xml` | メディアプールのフォルダごとに1つ：メディアプール項目（`Sm2MpAudioClip` など）とタイムライン（`Sm2MpTimelineClip` → `Sm2Timeline` → `Sm2Sequence`） |
| `SeqContainer/<uuid>.xml` | タイムラインごとに1つ：トラック（`Sm2TiTrack`）とそのアイテムを持つ `Sm2SequenceContainer` |
| `Gallery.xml` | カラーページのスチル（読まない） |

XML の要素名はデータベースの表名（`Sm2…`・`Bt…`）と同じで、各記録は他の記録から参照される `DbId` 属性（UUID）を持ちます。

### タイムラインの記録（MpFolder.xml）

| 要素 | 項目 | 意味 |
|---|---|---|
| `Sm2Timeline` | `Name` | タイムライン名 |
| | `Sequence` | 対応する `Sm2Sequence` の `DbId` |
| | `FrameRate` | タイムラインのフレームレート。**リトルエンディアンの double の16進**（先頭16桁） |
| `Sm2Sequence` | `FieldsBlob` | QDataStream の `QVariantMap` の16進（下記）。Fairlight ミキサー `FLStudioModelBA` を含む |
| | `MediaExtents` | リトルエンディアン double 2つの16進：開始秒と長さ秒。開始秒 × fps＝`Timeline.GetStartFrame()` |

### トラックとアイテム（SeqContainer/*.xml）

```text
Sm2SequenceContainer
 ├ VideoTrackVec / AudioTrackVec
 │   └ Element → Sm2TiTrack   Type（1＝オーディオ）, UserDefinedName, Sequence, Items
 │        └ Items → Element → Sm2TiAudioClip | Sm2TiTransition | …
 └ Sequence  （Sm2Sequence の DbId。コンテナとタイムラインを結ぶ）
```

クリップとトランジションの項目は [クリップと編集](clips-edits.md) にあります。

## Project.db：SQLite データベース

drpkit は `file:<パス>?mode=ro&immutable=1` で開きます（ロックなし・書き込みなし・ジャーナルなし）。同じ記録が表として入っていて、列名は XML の要素名と同じです。

| 表 | 使う列 | 意味 |
|---|---|---|
| `Sm2Timeline` | `Name`・`Sequence`・`FieldsBlob` | タイムライン。ここでは `FieldsBlob` は**空** |
| `Sm2Sequence` | `Sm2Sequence_id`・`FieldsBlob` | タイムラインのシーケンス。`FieldsBlob` に `FLStudioModelBA` |
| `Sm2TiTrack` | `Sm2TiTrack_id`・`Sequence`・`Type`・`UserDefinedName` | シーケンスのトラック |
| `Sm2TiItem` | `Sm2TiItem_id`・`Sm2TiTrack_id`・`DbType`・`Name`・`PrettyType`・`Start`・`Duration`・`In`・`AlignmentType`・`Position`・`EffectFiltersBA`・`FieldsBlob` | クリップとトランジション。`DbType` は XML の要素名（`Sm2TiAudioClip`・`Sm2TiTransition`） |
| `BtLockableBlob` | `BlobOwner`・`FieldsBlob` | クリップ色とタイムラインマーカー（両方が1つの表に入る） |

結合：

```sql
-- ミキサー：タイムライン名とその Fairlight モデル
SELECT t.Name, s.FieldsBlob
  FROM Sm2Sequence s JOIN Sm2Timeline t ON t.Sequence = s.Sm2Sequence_id;

-- 1つのタイムラインのクリップとトランジション（トラック順）
SELECT k.Type, k.UserDefinedName, i.DbType, i.Sm2TiItem_id, i.Name, i.PrettyType, i.Start, i.Duration,
       i."In", i.AlignmentType, i.Position, i.EffectFiltersBA, i.FieldsBlob
  FROM Sm2TiItem i JOIN Sm2TiTrack k ON i.Sm2TiTrack_id = k.Sm2TiTrack_id
 WHERE k.Sequence = :sequence ORDER BY k.rowid, i.Start;

-- 色（BlobOwner＝Sm2TiItem_id）とマーカー（BlobOwner＝Sm2Sequence_id）
SELECT FieldsBlob, BlobOwner FROM BtLockableBlob WHERE FieldsBlob IS NOT NULL;
```

drpkit が読む表にはフレームレートがないため、データベースからの `--edits` はフレーム数だけを出します（タイムコードなし、マーカーの絶対フレームなし）。

## 符号化

これらの項目の中には、次の4種類の入れ物が出てきます。

### QDataStream の `QVariantMap`（`FieldsBlob`）

Qt のビッグエンディアンの直列化です。

```text
u32 版 | u32 個数 | 個数 × （キー：QString, 値：QVariant）
QString  = u32 バイト長（0xFFFFFFFF＝null）＋ UTF-16BE
QVariant = u32 型番号 ＋ u8 null フラグ ＋ 値
```

| 型番号 | 値 |
|---|---|
| 1 | bool（1バイト） |
| 2 / 3 | int32 / uint32（BE） |
| 4 / 5 | int64 / uint64（BE） |
| 6 | double（BE） |
| 8 | 入れ子の `QVariantMap`（u32 個数＋要素） |
| 9 | `QVariantList`（u32 個数＋QVariant） |
| 10 | QString |
| 11 | `QStringList` |
| 12 | `QByteArray`（u32 長さ、0xFFFFFFFF＝null、＋バイト列） |

`Sm2Sequence` の `FieldsBlob` には `FLStudioModelBA`・`SeqRef`・`ModTimeInSecs`・`FirstMainBusFormat`・`Thumbnail` などのキーがあります。

### qCompress（`FLStudioModelBA`）

`FLStudioModelBA` は Qt の `qCompress` で作られた `QByteArray` です。先頭4バイトがビッグエンディアンの展開後サイズで、その後に zlib ストリームが続きます。中身は [Fairlight ミキサー](fairlight-model.md) に書いています。

### 版つきブロブ（`EffectFiltersBA`・クリップの `FieldsBlob`・素材の `Clip`／`FieldsBlob`） {#versioned-blob}

```text
u32BE 2（版） | u32BE 長さ（フラグの1バイトを含む） | u8 フラグ | 中身
フラグ 0x80＝そのまま、0x81＝zstd で圧縮
```

中身は protobuf のメッセージです（フィールド番号とワイヤ型だけでスキーマはない）。Resolve はほとんどを zstd で圧縮して書きます。drpkit は `0x80` で書き、Resolve はこれを受け付けます。`0x81` を読むには Python 3.14 以上（`compression.zstd`）か `zstandard` パッケージが必要です。

### ロック可能ブロブ（`Sm2…LockableBlob`／`BtLockableBlob`） {#lockable-blob}

`FieldsBlob` はキーが1つ `BlobData`（`QByteArray`）の `QVariantMap` です。

```text
u32BE 0x00002711 | u32BE 長さ（フラグの1バイトを含む） | u8 フラグ（0x80 無圧縮／0x81 zstd） | protobuf
```

クリップ色は3バイト固定（`80 28 <番号>`）、マーカーは protobuf の一覧です。[クリップと編集](clips-edits.md#clip-colors) 参照。

### protobuf

標準の protobuf のワイヤ形式です。キーは varint の `フィールド番号 << 3 | ワイヤ型`。ワイヤ型 0＝varint、1＝8バイト、2＝長さ付き、5＝4バイト。符号つきの位置は zigzag 符号化。長さ付きの中では、リトルエンディアンの値（単一値のつまみの double、キーフレームの記録）とビッグエンディアンの値（フェードのカーブ点、入れ子の長さ見出し）が混在します。出てくる箇所ごとに明記しています。
