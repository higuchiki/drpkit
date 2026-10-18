# コマンドリファレンス

```text
drpkit <command> [options]

  read     Fairlight ミキサー設定または編集情報を読む（読み取り専用）
  write    解析専用：.drp の新しいコピーのミキサー表へ int32 の生値を書く
  compose  テンプレート＋素材＋カット表から新しい .drp を作る

drpkit -V | --version
drpkit <command> -h
```

`drpkit` だけを実行すると使い方を表示して終了コード 2、知らないコマンドも 2 で終了します。

## drpkit read

```text
drpkit read [-h] [--timeline TIMELINE] [--json] [--all] [--expect EXPECT] [--edits] path
```

| 引数 | 意味 |
|---|---|
| `path` | `.drp`（zip として読むだけ）または `Project.db`（SQLite、`mode=ro&immutable=1`）。拡張子 `.drp` で判定し、それ以外は `Project.db` として扱う |
| `--timeline 名前` | そのタイムラインだけ。省略すると Fairlight のモデルを持つ全タイムラインを出す |
| `--json` | Markdown の代わりに機械処理用の JSON |
| `--all` | 対応表にないプラグインのつまみ（正規化された生値）と、プラグインの状態フラグの生値も出す |
| `--expect ファイル` | 期待値（YAML、下記）と照合。`一致 N 件／不一致 M 件` と不一致の一覧を出し、不一致があれば終了コード 1、なければ 0 |
| `--edits` | ミキサーの代わりに編集情報（クリップ・フェード・キーフレーム・トランジション・クリップ色・マーカー）を出す |

終了コード：0＝完了、1＝`--expect` の不一致、2＝`FLStudioModelBA` を持つタイムラインが見つからない（ミキサー表示のとき）。

### ミキサーの出力（`--json`）

```json
[
 {"timeline": "Fixture",
  "seqref": "…",
  "strips": [
   {"name": "Track1", "type": "track", "column": 0,
    "values": {"fader": {"value": "0 dB", "raw": 0, "conf": "two_point"}, "…": {}},
    "plugins": [
     {"plugin": "Voice Isolation", "slot": "内蔵FX(6)",
      "params": {"amount":  {"value": "82.01", "raw": 0.82005, "conf": "two_point"},
                 "enabled": {"value": "ON",    "raw": 0,       "conf": "direct"}}}]}]}
]
```

- ストリップは**列ごと**に1つ。ステレオトラックは同じ名前のストリップが2つ出ます。Bus は `"type": "bus"`。
- `values` のキーは [対応表](fairlight-model.md#all-channel-items) の項目名、`raw` は保存されている int32、`conf` は [確度](fairlight-model.md#confidence-marks)。
- `slot` は `Slot1`〜`Slot6`（挿入スロット）か `内蔵FX(n)`（トラック内蔵FX、n＝6〜10）。[プラグイン](plugins.md) 参照。
- 換算できない値は `未較正(raw=…)`（対応表にない）または `画面空欄(raw=…)`（画面の欄が空になる範囲）と出し、`conf` は `uncal`。

### `--expect` のファイル

```yaml
timeline: Fixture            # 省略可：このタイムラインだけ
strips:
  Track1: {comp_threshold: -15 dB, comp_ratio: "2.0:1", Voice Isolation.enabled: "ON"}
  Bus 1:  {limiter_on: "ON"}
```

キーは項目名、プラグインの値は `プラグイン名.出力名`。期待値は、換算後の `value`（確度記号を除いた表示どおりの文字列）と文字列として完全一致で比べます。例：`tests/expect_fixture_default-01.yaml`、`tests/expect_fixture_roundtrip-01.yaml`。

### 編集情報の出力（`--edits --json`）

```json
[{"timeline": "Fixture", "fps": 24.0, "start_frame": 86400,
  "items": [
   {"track": "Track1", "type": "audio", "kind": "AudioClip", "name": "sine1k.wav",
    "start": 86400, "end": 86640.0, "duration": 240.0, "src_in": 0.0, "src_out": 240.0,
    "color": "Orange", "fade_in": 48.0, "fade_out": 24.0, "volume_db": -6.0,
    "volume_db_keyframes": [{"frame": 48, "value": 0.0, "flags": 786432}],
    "clip_plugins": [{"plugin": "Voice Isolation", "params": {"amount": {"value": "55.0", "raw": 0.55, "conf": "two_point"}}}],
    "start_tc": "01:00:00:00"},
   {"kind": "Transition", "transition": "Cross Fade 0DB", "alignment": "centered on edit point", "…": "…"}],
  "markers": [{"frame": 86448, "offset": 48, "color": "Red", "name": "Cut here",
               "note": "…", "duration": 1, "custom_data": ""}]}]
```

| キー | 意味 |
|---|---|
| `start`・`end`・`duration` | タイムラインのフレーム（`end`＝`start + duration`） |
| `src_in`・`src_out` | 素材のフレーム。`src_out`＝`src_in + duration` |
| `fade_in`・`fade_out` | フェードの長さ（フレーム。保存されているときだけ） |
| `fade_in_curve`・`fade_out_curve` | カーブ点 `[位置%, レベル（0.1 dB 単位）]`（曲線のフェードのときだけ） |
| `volume_db` | クリップ音量（dB） |
| `volume_db_keyframes` | `[{frame: 素材のフレーム, value: dB, flags}]` |
| `clip_plugins` | クリップ内蔵FX（Voice Isolation・Dialogue Leveler）。記録があれば有効 |
| `start_tc` | `start` のタイムコード（`.drp` のみ） |
| `markers[].frame`・`offset` | タイムライン上の絶対フレーム／タイムライン開始からのフレーム |

`fps` と `start_frame` は `.drp` から得ます。`Project.db` では `null` で、マーカーは `offset` だけを持ちます。詳しくは [クリップと編集](clips-edits.md)。

## drpkit compose

```text
drpkit compose [-h] --cuts CUTS --media TRACK=FILE [--media ...] [--timeline TIMELINE] [--keep-clip-fx] template output
```

| 引数 | 意味 |
|---|---|
| `template` | テンプレートの `.drp`（読むだけ） |
| `output` | 新しい `.drp`。既にあってはならない |
| `--cuts ファイル` | カット表（`.json` か `.csv`、[形式](cut-list.md)）。中の `media` の相対パスはカット表のフォルダから解決 |
| `--media N=ファイル` | オーディオトラック N（1始まり・テンプレートの並び順）の音声ファイル。テンプレートのタイムラインの**全**オーディオトラックを1回ずつ指定する。`N=@template` はそのトラックのテンプレート素材をそのまま使う（カット・フェード・キーフレームは反映） |
| `--timeline 名前` | テンプレートのタイムライン。テンプレートに複数あるときは必須 |
| `--keep-clip-fx` | 各トラックのテンプレート上で最も早いクリップから、クリップ音量・音量キーフレームと `EffectFiltersBA` 内のほかのエフェクトを引き継ぐ。カット表のフェード・キーフレームが優先。指定しなければ新しいクリップの音量は 0 dB。（クリップ内蔵FX＝Voice Isolation・Dialogue Leveler はクリップの `FieldsBlob` にあり、指定の有無にかかわらず、新しいクリップはすべて同じ最も早いクリップからこれを写す。[クリップと編集](clips-edits.md#clip-built-in-fx) 参照） |

成功すると JSON の報告（`fps`・`timeline_start_frame`・`markers`・`cuts`・`media`・`extra_media`・`preservation`）を出します。エラー時は理由を出して終了コード 2。出力ファイルは作りません。

変えるもの・残すもの：テンプレートのオーディオのアイテムとそのクリップ色を置き換え、テンプレートの各トラックのメディアプール項目を指定ファイルに向け直し（`ffprobe` で得た情報。[素材](media.md)）、シーケンスの範囲を最初と最後のカットに合わせ、カット表に `markers` があればマーカーを書きます。それ以外（Fairlight のモデル＝ミキサー・プラグイン・Bus・ルーティング、映像、カラー、Fusion、ほかのメディアプール項目）は書き込み前に比較し、バイト単位で同一でなければなりません。

推測せずに拒否するもの：重なるクリップ（隣接するカット＋`crossfade` を使う）、オーディオトラック上のオーディオクリップとトランジション以外のアイテム、複数トラックでの同じ素材、トラック間で共有されたメディアプール項目、素材の長さを超える `source_out`、テンプレートのチャンネル割り当てが既定でない場合のチャンネル数変更、未対応の素材形式。

## drpkit write

```text
drpkit write [-h] [--set NAME:ITEM=VALUE ...] [--dump-item ITEM] [--timeline TIMELINE] src [dst]
```

| 引数 | 意味 |
|---|---|
| `src` | 入力の `.drp`（読むだけ） |
| `dst` | 出力の `.drp`。既にあってはならない。`--set` のとき必須 |
| `--set 名前:項目=値` | ストリップ `名前`（項目 `0xBC` に保存されたトラック名、または `Bus 1`）の項目 `項目`（例 `0x10d`）に int32 の `値`（10進か `0x…`）を書く。ステレオトラックは同名の全列に書く。複数指定可 |
| `--dump-item 項目` | その項目の値を各表で表示（先頭6列）して終了。出力ファイルなし |
| `--timeline 名前` | 書き込むタイムライン。Fairlight のモデルを持つタイムラインが複数あるときは必須 |

書いたセルはすべて読み直して比較し、指定したセルだけが変わったときに限り出力を作ります。書き込みごとに1行（`書込 名前 0x… = 値（列 …）`）を出します。換算表づくり専用です（保存値を書く → Resolve に読み込む → 画面を読む）。必ずコピーに使ってください。
