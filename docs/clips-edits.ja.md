# クリップと編集

`drpkit read --edits` が読み、`drpkit compose` が書く内容：クリップ、クリップ音量とフェード、キーフレーム、トランジション、クリップ色、クリップ内蔵FX、タイムラインマーカー。位置はすべて**タイムラインのフレームレートでのフレーム数**です。

| データ | `.drp` | `Project.db` |
|---|---|---|
| クリップ・トランジション | `SeqContainer/*.xml`：`Sm2TiAudioClip`・`Sm2TiTransition` | `Sm2TiTrack` 経由の `Sm2TiItem` |
| クリップ音量・フェード・キーフレーム | クリップの `<EffectFiltersBA>`（16進） | `Sm2TiItem.EffectFiltersBA` |
| クリップ内蔵FX | クリップ自身の `<FieldsBlob>` | `Sm2TiItem.FieldsBlob` |
| クリップ色 | `project.xml`：`Sm2TiItemLockableBlob` | `BtLockableBlob` |
| タイムラインマーカー | `project.xml`：`Sm2SequenceLockableBlob` | `BtLockableBlob` |
| タイムラインの開始 | `Sm2Sequence/MediaExtents` | — |
| フレームレート | `Sm2Timeline/FrameRate`（double LE） | —（フレームのみ） |

## クリップの記録

| 項目 | 意味 |
|---|---|
| `Name` | クリップ名（オーディオでは素材のファイル名） |
| `Start` | クリップ先頭のタイムライン上のフレーム（整数） |
| `Duration` | `整数|hex(double LE)`：整数フレームと、端数をリトルエンディアン double にした16進。例 `16816|00009a999999e93f`。単なる数値のこともある |
| `In` | クリップ先頭の素材上のフレーム。空なら 0 |
| `MediaRef` | メディアプール項目（`Sm2MpAudioClip`）の `DbId` |
| `MediaFilePath` | 素材ファイルの絶対パス |
| `MediaTimemapBA` | `02` ＋ ビッグエンディアン double：素材の長さ − 1フレーム（秒）（`compose` が書く値） |
| `EffectFiltersBA` | クリップ音量・フェード・キーフレーム（下記） |
| `FieldsBlob` | クリップ内蔵FX（下記） |
| `VirtualAudioTrackBA` | クリップのチャンネル割り当て |

reader は `end = start + duration`、`src_out = src_in + duration`、`start` のタイムコード（`.drp` のみ）も出します。

## クリップ音量とフェード：`EffectFiltersBA`

[版つきブロブ](file-format.md#versioned-blob)（`u32BE 2`・`u32BE 長さ`・フラグ `0x80`／`0x81` zstd）で、中身は protobuf です。

```text
field 1（繰り返し）＝ エフェクト
    1: エフェクト種別（varint）
    9（繰り返し）＝ パラメーター
        1: パラメーター番号（varint）
        3: { 1: { 2: double LE （単一の値）
                  7: ビッグエンディアン double の列 （カーブ点） } }
        10: キーフレーム（バイト列、下記）
```

エフェクト種別 **124** が「Fairlight Clip Volume and Fades」です。

--8<-- "map_clip_effects.ja.md"

| 番号 | 意味 | 単位 |
|---|---|---|
| 95 | クリップ音量 | dB |
| 97／98 | フェードイン／フェードアウトの長さ | フレーム（double） |
| 99／100 | フェードイン／フェードアウトのカーブ点 | [フェードのカーブ](#fade-curves) 参照 |

`SetFades` の 0/0・48/24・100/7 と、FCPXML のクリップ音量 −6 dB で確認。`.drp` を読み込み直しても値は残ります。注意：`Project.ExportProject` は最後に**保存した**状態を書き出します。`SetFades` の後は保存してから書き出してください。

## 音量キーフレーム

番号95（クリップ音量）のメッセージの field 10 に入ります。

```text
int32BE（−16 × 個数）
個数 × （u32LE フレーム | u32LE フラグ | double LE dB）
```

- `フレーム` は**素材のフレーム番号**です（クリップ先頭＝素材の In）。In が 144 のクリップで確認：素材の 24／48 に置いたキーではクリップ全体が最後の値、168／192 に置くとクリップの +1 秒／+2 秒で効いた。
- `フラグ` は画面で付けたキーでは `0x000C0000`（補間の種類と思われる・未解読）。`compose` も同じ値を書きます。
- 再生（書き出しで確認）：キーの間は dB で直線補間、最初のキーより前は最初の値、最後より後は最後の値。
- 画面で作ったデータでは、単一の値（field 3）は最初のキーと同じ。
- 24 fps で画面で付けたキー：+20 秒 → 480、+25 秒 → 600、+30 秒12フレーム → 732、値 −3／−15／+6 dB。

## フェードのカーブ {#fade-curves}

番号99（フェードイン）と100（フェードアウト）はカーブ点を1つ持ちます。field 7 にビッグエンディアンの double 2つ、**（位置 %、レベル 0.1 dB 単位）**です。

- 位置はフェード区間の先頭から測り、レベルはクリップ音量（番号95）に対する相対値。
- 直線のフェード（振幅が直線）では 99／100 に**何も記録しない**。
- 書き出した曲線は点をちょうど通る（位置 25／50／75／78 % で確認）。
- 点が 50 % のとき、曲線は直線フェードの dB 曲線の定数倍：`(50, −20)` で 25／50／75 % の点が −0.8／−2.0／−4.0 dB（直線なら −2.5／−6.0／−12.0）。それ以外の位置では、両端と点の間の形は**モデル化していません**。
- reader の表示例：`Out カーブ点 位置49%で -2.0 dB・直線 -5.8 dB より上に凸`。
- `compose` が書くのは直線のフェードだけ。`--keep-clip-fx` で引き継いだカーブ点は消します。

FCPXML の `fadeIn`／`fadeOut` は、Resolve が読み込み時に無視します（クリップ音量だけが入る）。

## トランジション

トラック上でクリップの間に置かれる `Sm2TiTransition` です。

| 項目 | 意味 |
|---|---|
| `PrettyType` | 例 `Cross Fade 0DB`・`Cross Fade +3dB`・`Cross Fade -3dB` |
| `Start` | トランジション先頭のタイムライン上のフレーム |
| `Duration` | 長さ（フレーム） |
| `AlignmentType` | 下表。`Position` にも同じ値 |

--8<-- "map_alignment.ja.md"

（1＝編集点から始まる、2＝編集点が中央、3＝編集点で終わる）

`compose` は `Cross Fade 0DB` を中央揃え（`AlignmentType` 2）で、つなぎ目の `crossfade/2` フレーム前から書きます。トランジション本体（`FieldsBlob`）は Resolve 21.1.1 の書き出しから取った定数で、クリップへの参照は含みません。

## クリップ色 {#clip-colors}

色を付けたクリップごとに `Sm2TiItemLockableBlob`（`.drp`）／`BtLockableBlob` の行（`Project.db`）が1つあります。色がなければ**記録はありません**。

- `BlobOwner`＝クリップの `DbId`／`Sm2TiItem_id`。
- `BlobData`＝`00002711 00000003 80 28 <番号>`：ロック可能ブロブの見出し、長さ 3、フラグ `0x80`、protobuf の field 5（`0x28`）＝色番号。

--8<-- "map_clip_colors.ja.md"

## クリップ内蔵FX {#clip-built-in-fx}

クリップに設定した Voice Isolation と Dialogue Leveler は、クリップ自身の `FieldsBlob` にあります。

1. 版つきブロブ（`u32BE 2`・長さ・`0x80`／`0x81` zstd）、中身は protobuf
2. ASCII 文字列 `FL::ClipFX` の後ろに zlib ストリーム（`78 9C …`）
3. その中に、トラックと同じ形式のプラグイン記録：`bmd:<名前>:<ID>` ＋ 64 バイトのパラメーター名 ＋ float32 の正規化値。パラメーター名に `::` がないこともある（Dialogue Leveler の `UI_…`）

エフェクトを無効にすると**記録そのものが消える**ので、記録があれば有効です。API の `SetVoiceIsolationState` と `SetProperty` で確認。換算は [プラグイン](plugins.md)。`compose` はトラックの新しいクリップをすべて、テンプレートのそのトラックで最も早いクリップから作り、その `FieldsBlob` をそのまま写すので、クリップ内蔵FX は `--keep-clip-fx` の有無にかかわらず新しいクリップ全部に引き継がれます（このオプションが扱うのは `EffectFiltersBA`＝クリップ音量・キーフレーム・ほかのエフェクト）。

## タイムラインマーカー

マーカーのあるタイムラインごとに `Sm2SequenceLockableBlob`（`.drp`）／`BtLockableBlob` の行（`Project.db`）が1つあります。マーカーがなければ**記録はありません**。

- `BlobOwner`＝タイムラインの `Sm2Sequence` の `DbId`。
- `FieldsBlob`＝`QVariantMap {BlobData}`。`BlobData`＝`00002711`・`u32BE 長さ`・`0x80` 無圧縮／`0x81` zstd・protobuf。
- protobuf の field 2 がマーカー一覧です（メッセージのほかのフィールドは `compose` がそのまま残します）。

```text
field 2（繰り返し）＝ マーカー
    1: { 1: zigzag(フレーム) }           タイムライン開始からのフレーム（0 のときは省略）
    2: u32BE 2 | u32BE 長さ | {
         1: {
           1: 色ビット（varint）
           3: メモ      （文字列）
           3: 長さ      （フレーム数の10進文字列）
           3: 名前      （文字列）
           6: customData（文字列・任意）
         } }
```

3つの field 3 は順にメモ・長さ・名前です。フレームはタイムライン開始から数え、`Timeline.GetMarkers()` の値と同じです。reader は絶対フレーム（`offset + 開始フレーム`、`.drp` のみ）も出します。

--8<-- "map_marker_colors.ja.md"

ビット 256 は使われていません。`Timeline.AddMarker` で作ったマーカー（16色すべて、長さ1〜24、日本語、XML 記号、customData）で確認し、API で作った4本の書き出しを符号化し直すと**バイト単位で一致**します。

## タイムラインの開始

`Sm2Sequence/MediaExtents` はリトルエンディアン double 2つ：開始秒と長さ秒です。開始秒 × fps＝`Timeline.GetStartFrame()`（読み込み後に 24 fps で 3600 秒 → 86400、0 → 0 を確認）。`compose` は最初と最後のカットに合わせて設定します。
