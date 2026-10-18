# カット表の形式

カット表は、どの音声のどこをどこへ置くかを `drpkit compose` に伝えるものです。JSON か、同じ列名の CSV で書きます（CSV には `markers` がありません）。

## 単位

- 値はすべて**タイムラインのフレームレートでの整数フレーム**（テンプレートのタイムラインの `FrameRate`）。JSON では `"units": "frames"` が必須。秒・タイムコード・サブフレームは受け付けません。
- `source_in` は含み、`source_out` は**含まない**（クリップの長さは `source_out − source_in` フレーム）。
- `timeline_start` はタイムライン上の**絶対**フレーム。24 fps で 01:00:00:00 から始まるタイムラインなら 86400 が先頭です。
- 出力のタイムラインは最も早いカット（`min(timeline_start)`）から始まります。

## 例（JSON）

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

## カットの列

| 列 | 必須 | 型 | 意味 |
|---|---|---|---|
| `track`／`tracks` | どちらか一方 | 整数／整数の配列／`"all"` | オーディオトラックの番号（1始まり・テンプレートの並び順）。複数指定した行は各トラックに1クリップずつになる |
| `source_in` | 必須 | 0以上の整数 | 素材の最初のフレーム |
| `source_out` | 必須 | `source_in` より大きい整数 | 最後のフレームの次（含まない）。素材の長さを超えてはならない |
| `timeline_start` | 必須 | 0以上の整数 | クリップ先頭のタイムライン上の絶対フレーム |
| `media` | 任意 | パス | このカット専用の音声ファイル（1トラックに複数の BGM を並べる等）。相対パスはカット表のファイルの場所から。空ならそのトラックの `--media`。追加の素材ごとに新しいメディアプール項目ができる。同じファイルを2つのトラックで使うことはできない。ここに `@template` は書けない |
| `fade_in`・`fade_out` | 任意 | 0以上の整数 | フェードの長さ（フレーム）。`fade_in + fade_out` はクリップ長以下。フェードは直線（カーブ点なし） |
| `crossfade` | 任意 | 偶数 | 同じトラックの直前のカットとのつなぎ目を**中心**にした、このフレーム数の Cross Fade 0 dB。両側に `crossfade/2` の素材の余白が要り、2つのカットはぴったり接していて、そのつなぎ目にフェードがあってはならない |
| `volume_keyframes` | 任意 | `[[素材フレーム, dB], ...]` | クリップ音量のキーフレーム。フレームは**素材の**フレーム番号（クリップ先頭＝`source_in`）。キーの間は dB で直線補間、最初のキーより前は最初の値、最後より後は最後の値。CSV では JSON の配列を文字列で書く |
| `color` | 任意 | 色名 | クリップ色16色のいずれか：Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate |

これ以外の列はエラーです。1トラック上のクリップは重ねられません。代わりに隣接するカットと `crossfade` を使います。

## マーカー（JSON のみ）

| キー | 必須 | 意味 |
|---|---|---|
| `frame` **または** `offset` | どちらか1つだけ | `frame`＝タイムライン上の絶対フレーム（`timeline_start` と同じ尺度。最初のカットより前は不可）／`offset`＝タイムライン開始からのフレーム（`Timeline.GetMarkers()` が返す値） |
| `name` | 必須 | マーカー名（Resolve は名前のないマーカーを作らない） |
| `color` | 任意 | Blue（既定）, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream |
| `note`・`custom_data` | 任意 | 文字列 |
| `duration` | 任意 | 1以上のフレーム数。既定 1 |

- `markers` がなければテンプレートのマーカーをそのまま残し、あれば置き換え、`"markers": []` なら消します。
- 同じフレームに2つのマーカーは置けません。

## CSV

```csv
track,source_in,source_out,timeline_start,fade_in,fade_out,crossfade,color,media,volume_keyframes
1,0,3600,86400,,,,,,
2,0,3600,86400,,,,,,
1,7200,10800,90000,,,60,,,
3,0,1200,86400,,24,,Orange,bgm/intro.wav,"[[0,-12.0],[600,-18.0]]"
```

- 1行目は上の列名の見出し。UTF-8（BOM 付きも可）。`units` は `frames` とみなします。
- `track` 列か `tracks` 列のどちらか一方を使います。CSV のセルにはトラック番号を1つ（トラックごとに行を繰り返す）、または `tracks` 列なら `all` を書きます。
- 空のセルは「指定なし」です。

## 検証

書き込みの前にカット表全体を検査します。次の場合は拒否し、出力ファイルは作りません。

- `units` がない／`frames` でない、知らない列、`track` と `tracks` の両方、存在しないトラック番号
- 整数でない・負の値・空や逆向きのカット、クリップより長いフェード
- 素材の長さを超える `source_out`、1トラック上で重なるクリップ
- 奇数の `crossfade`、直前に接するカットがない・素材の余白がない・つなぎ目にフェードがあるクロスフェード
- 知らないクリップ色・マーカー色、名前のないマーカー、`frame`／`offset` の両方または片方もない、タイムライン開始より前、同じフレームに2つ

書き込み後は一時ファイルを reader で読み直し、全オーディオクリップとクロスフェードをカット表と照合します（トラック・順序・位置・ソースIn/Out・フェード・音量キーフレーム・色・素材ファイル）。
