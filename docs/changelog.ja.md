# 更新履歴

英語版の正本は [CHANGELOG.md](https://github.com/higuchiki/drpkit/blob/main/CHANGELOG.md) です。

## 未リリース

### 追加
- ドキュメントサイト（MkDocs Material、英語と日本語）を https://higuchiki.github.io/drpkit/ に公開：コマンドリファレンス、カット表、`.drp`／`Project.db` の構造、全項目つきの Fairlight ミキサー、換算、プラグイン、クリップと編集、素材、未解読、検証。項目の表は `drpkit/fairlight_map.yaml` から生成（`tools/gen_map_docs.py`）。GitHub Actions で公開。

## 0.1.0 — 2026-10-18

最初のパッケージ版。DaVinci Resolve Studio 21.1.1（macOS）で確認。

### 追加
- Python パッケージ `drpkit`（Python 3.9 以上、PyYAML、任意で `zstandard`）とコマンド `drpkit read | write | compose`。
  `fairlight_reader.py`・`fairlight_writer.py`・`drp_compose.py` は互換用の薄い入口として残す。
- `read`：トラック内蔵 Voice Isolation の有効／無効（`Voice Isolation.enabled`）。プラグイン記録の状態フラグ（ビット `0x10`）から。
  `--all` でほかのプラグインの状態フラグも生値で出す。
- `read --edits`：タイムラインマーカー（フレーム、タイムライン開始からの位置、16色、名前、メモ、長さ、customData）とタイムラインの開始フレーム。
- `compose`：カット表の `media` 列。1トラックに複数の音声ファイル（BGM など）を置け、それぞれが独立したメディアプール項目になる。
- `compose`：カット表の `markers`。タイムラインマーカーの書き込み・置き換え・消去（絶対 `frame` または `offset`）。
- `tools/sanitize_drp.py`：`.drp` の fixture をコミットする前に、機器 ID と保存された絶対パスを消す。`--check` で残りを報告。
- GitHub Actions：Ubuntu と macOS、Python 3.9 と 3.12 での単体テストと、プライバシー検査。

### 変更
- 項目の対応表を `configs/fairlight_map.yaml` から `drpkit/fairlight_map.yaml`（パッケージのデータ）へ移動。
- コミット済みの全 `.drp` fixture を再度消毒：機器 ID とプロジェクト設定内の絶対パスを置換。テストが使う内容は不変。

### まだ解読していないもの
トラック単位の Dialogue Leveler の設定、トラックのオートメーションレーン、キーフレームのフラグ、項目 `0x0B9`、プラグインのバイパス、Bus のソロ。
