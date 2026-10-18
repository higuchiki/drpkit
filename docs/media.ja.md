# 素材

メディアプール内の音声ファイルがどう記録されているか、そして `compose` がテンプレートのメディアプール項目を指定ファイルに向け直すときに何を書くか。値は `ffprobe` で読みます。推測はせず、未対応のファイルは拒否します。

## 対応形式 {#supported-formats}

| 入れ物 | `ffprobe` のコーデック | ビット深度 | `CodecName` | `BitDepth` | Clip の field 18（形式フラグ） |
|---|---|---|---|---|---|
| WAV | `pcm_s16le` | 16 ビット | `Linear PCM` | 1 | 32768（`0x8000`） |
| WAV | `pcm_s24le` | 24 ビット | `Linear PCM` | 2 | 32768（`0x8000`） |
| WAV | `pcm_f32le` | 32 ビット浮動小数点 | `Linear PCM` | 3 | 32768（`0x8000`） |
| FLAC | `flac` | 16 ビット | `FLAC` | 1 | 32778（`0x800A`） |
| FLAC | `flac` | 24 ビット | `FLAC` | 2 | 32778（`0x800A`） |
| M4A | `aac`（プロファイル LC） | — | `AAC` | 3 | 32772（`0x8004`） |
| MP3 | `mp3` | — | `MP3` | 3 | 32776（`0x8008`） |

- **`BitDepth`：1＝16 ビット、2＝24 ビット、3＝32 ビット浮動小数点。** 圧縮形式は 3 で保存されます。
- サンプリング周波数 44100 か 48000 Hz、1 か 2 チャンネル、音声ストリームはちょうど1つ。
- それ以外（ほかのコーデック、8／32 ビット整数 PCM、ほかの周波数、3チャンネル以上、動画ファイル）は拒否します。

## メディアプール項目（`Sm2MpAudioClip`）

`MediaPool/**/MpFolder.xml` の中：

| 項目 | 符号化 | 内容 |
|---|---|---|
| `Name` | 文字列 | ファイル名 |
| `UniqueMediaPoolItemId` | UUID | 項目の ID。`compose` が追加素材を足すたびに新しく振る |
| `Clip` | [版つきブロブ](file-format.md#versioned-blob)、protobuf | ファイルの場所と形式（下記） |
| `TracksBA` | QDataStream | ストリームごとの音声の説明（下記） |
| `FieldsBlob` | 版つきブロブ、protobuf | 埋め込み音声の情報（下記） |
| `EmbeddedAudioVec` → `BtAudioInfo` | XML | 埋め込み音声ストリームの記録（`DbId` はチャンネル割り当てから参照される） |
| `VirtualAudioTracksBA` | 16進 | 仮想オーディオトラックの構成 |

### `Clip`（protobuf）

| フィールド | 型 | 内容 |
|---|---|---|
| 1 | 文字列 | ファイルのフォルダ |
| 2 | 文字列 | ファイル名 |
| 3 | 文字列 | 更新日時、C の `ctime` 形式（`Sun Oct 18 17:34:12 2026`） |
| 5 | 文字列 | コーデック名（`Linear PCM`・`FLAC`・`AAC`・`MP3`） |
| 13 | varint | 更新日時、エポックからのマイクロ秒 |
| 15・16 | varint | 未解読（そのまま残す） |
| 18 | varint | 形式フラグ（上の表） |

### `TracksBA`（QDataStream）

キーが1つ `"0"` の `QVariantMap` で、その `QByteArray` の値が最初の音声ストリームを表す入れ子の `QVariantMap` です。

| キー | 内容 |
|---|---|
| `UniqueId` | ストリームの ID |
| `DbType` | `BtAudioTrack` |
| `IdxTrack` | ストリーム番号（0） |
| `StartTime` | 0.0 |
| `SampleRate` | Hz |
| `NumChannels` | 1 か 2 |
| `Duration` | 長さ（**サンプル数**） |
| `CodecName` | `Clip` の field 5 と同じ |
| `BitDepth` | 1／2／3 |
| `ChannelLayout` | チャンネル配置。`ffprobe` が `mono`／`stereo` と報告したときにある |

### `FieldsBlob`（protobuf）

field 1 → field 5 に埋め込み音声の情報があり、これも入れ子のマップを包んだキー1つの `QVariantMap` です。

| キー | 内容 |
|---|---|
| `MediaExtents` | リトルエンディアン double 2つ：0 と長さ（秒） |
| `CodecName` | コーデック名 |
| `SampleRate` | Hz。**48000 のときは省略** |
| `BitDepth` | 1／2。**3 のときは省略**（採取したすべての例で 32 ビットが既定） |
| `Type` | ステレオで 0、モノラルでは省略 |
| `ChannelVecBA` | チャンネル割り当て：`{"0": {MediaRef}, "1": {MediaRef, ChannelIdx: 1}}` のようにチャンネルごとに1つ。`MediaRef`＝`BtAudioInfo` の `DbId` |

## 長さ

- `Duration`（サンプル数）は、ストリームの `duration_ts × time_base × 周波数`（なければ `duration × 周波数`）。
- **MP3**：Resolve は `ffprobe` のギャップレスの長さと違い、符号化された MP3 フレームをすべて数えるため、drpkit はパケットの長さを合計します。
- カット表の `source_out` は、2つの長さ（保存する長さと再生できる中身）の短い方を超えてはなりません。

## チャンネル数の変更

新しいファイルのチャンネル数がテンプレートの素材と違う（モノラル ↔ ステレオ）とき、`compose` は `NumChannels`・`ChannelVecBA`・`Type` と各クリップの `VirtualAudioTrackBA`（`ChannelsBA`＝`u32BE 2, 個数` ＋ チャンネルごとに `0x4001 + i`、`AudioType` はモノラル 1・ステレオ 0）も書き換えます。テンプレートが Resolve の既定のチャンネル割り当てのときだけで、そうでなければ拒否します。

## 1トラックに複数の素材

`media` を持つカットの行ごとに新しいメディアプール項目を作ります。トラックのテンプレート項目を新しい ID で複製し（項目の `DbId`、埋め込み `BtAudioInfo` の `DbId`＝チャンネル割り当て内に UTF-16 で入っている箇所も改名、`UniqueMediaPoolItemId`）、そのファイルの情報で埋めます。同じファイルを2つのトラックで使うこと、2つのテンプレートトラックが1つのメディアプール項目を共有していることは拒否します。

## 検証

28通りすべて（WAV 16/24/32f、FLAC 16/24、AAC、MP3 × 44.1/48 kHz × モノラル/ステレオ）の素材情報を、同じファイルを Resolve 自身が書き出したもの（`tests/compose/formats/`）と項目ごとに照合しています。28通りを網羅する 56 本の合成プロジェクトを Resolve 21.1.1 に読み込み、全クリップが指定の位置・In 点・フェードで *オンライン* になり、両チャンネルで音が出ることを確認しました。
