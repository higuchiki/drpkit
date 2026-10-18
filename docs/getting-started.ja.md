# はじめに

## 必要なもの

| 必要なもの | 用途 |
|---|---|
| Python 3.9 以上 | すべて |
| [PyYAML](https://pypi.org/project/PyYAML/) | すべて（自動で入ります） |
| `PATH` 上の `ffprobe`（[FFmpeg](https://ffmpeg.org/) に同梱） | `compose` のみ（渡した素材を読むため） |
| Python 3.14 以上（標準の `compression.zstd`）**または** `zstandard` パッケージ | `Project.db` のクリップFX、圧縮して保存されたタイムラインマーカーを読むとき |

これ以外は不要です。drpkit は Resolve を起動せず、スクリプトAPIも使いません。

## インストール

```bash
pip install git+https://github.com/higuchiki/drpkit.git
# zstd 対応つき：
pip install "drpkit[zstd] @ git+https://github.com/higuchiki/drpkit.git"
drpkit --version
```

リポジトリを取得した場合は `pip install .` でも入ります。旧来の `fairlight_reader.py`・`fairlight_writer.py`・`drp_compose.py` も同じコードを呼ぶ薄い入口として残っています。

## 3つのコマンド

### 1. ミキサーを読む

```bash
drpkit read project.drp
```

ミキサーのストリップ（トラックの各列と各 Bus）ごとに Markdown の表を1つ出します。各行に換算後の値・[確度記号](fairlight-model.md#confidence-marks)・保存されている生値が並びます。

```text
## タイムライン：Fixture

### Track1（track・列0）
| 項目 | 値 | 生値 |
|---|---|---|
| fader | 0 dB² | 0 |
| proc_order | FX→DY→EQ (default) | 5 |
| eq_band1_type | HPF | 6 |
| eq_band1_freq | 70 Hz | 70 |
| eq_band1_q | 1.1※ | 26 |
...
```

機械処理には `--json` を使います。ディスクDBのプロジェクトも同じように読めます。タイムラインは `--timeline` で1つ選びます。

```bash
drpkit read "/path/to/Resolve Project Library/.../Project.db" --timeline "Main"
```

### 2. 編集情報を読む

```bash
drpkit read project.drp --edits
```

クリップ（位置・ソースIn/Out・フェード・フェードのカーブ点・クリップ音量・音量キーフレーム・クリップFX・色）、トランジション、タイムラインマーカーを出します。位置はすべてタイムラインのフレームレートでのフレーム数です。詳しくは [クリップと編集](clips-edits.md)。

### 3. 新しいプロジェクトを組み立てる

```bash
drpkit compose TEMPLATE.drp OUT.drp --cuts cuts.json \
    --media 1=host.wav --media 2=guest.flac
```

テンプレートのオーディオトラックを空にして [カット表](cut-list.md) どおりに並べ直します。ミキサーほか残りはバイト単位でそのままです。Resolve の *ファイル → プロジェクトの読み込み* で、**検証専用のプロジェクトライブラリ**に読み込んでください。

## 安全のきまり

- `read` は `.drp` を zip として読むだけ、`Project.db` は SQLite の `mode=ro&immutable=1` で開きます。入力は変更しません。
- `write` と `compose` は出力先が既にあれば拒否します。全変更をメモリ上で作って検証し、出力の隣の一時ファイルに書いて読み直して再検証し、合格したときだけ一度に出力名へ移します（ハードリンク。使えない環境では rename）。エラー時は一時ファイルを消し、出力は残りません。
- 原本のバックアップを残し、Resolve で結果を確かめてから使ってください。**無保証**です（[LICENSE](https://github.com/higuchiki/drpkit/blob/main/LICENSE)）。

## テストの実行

```bash
python3 -m unittest discover -s tests -t . -v
```

compose のテストには `ffmpeg` / `ffprobe` が必要です。各テストの範囲は [検証](verification.md#automated-tests)。
