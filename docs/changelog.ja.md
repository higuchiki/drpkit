# 更新履歴

英語版の正本は [CHANGELOG.md](https://github.com/higuchiki/drpkit/blob/main/CHANGELOG.md) です。

## 未リリース

### 追加
- `write --eq-freq 名前:バンド=Hz`：EQ の周波数を整数Hzで指定。連動するノブ位置・帯域も同時に書く。小数・範囲外・raw `--set` との競合は拒否。
- `write --verify-eq`：Resolve から書き出し直したファイルを `--eq-freq` の指定と照合する読み取り専用の確認（一致0／不一致1／指定エラー2）。Resolve は読み込み時に値を変えることがある（無料版 19.1.3 で 1399 Hz → 1392 Hz）。
- 名前が空のトラックを strip id で指定する `@A1`／`@A2`（ステレオの継続列も含む）。
- `read`：Resolve 19 のタイムラインマーカー形式（21 形式と両対応）。名前が空の編集トラックを `@A1` などで表示。
- GitHub Actions：テストに Windows を追加（Ubuntu・macOS・Windows × Python 3.9・3.12）。
- Windows 11 の無料版 DaVinci Resolve 19.1.3（build 7）・Python 3.10.6 で確認（「検証」参照）。21.1.1 を含むほかの無料版は未検証。

### 修正
- Windows：コマンド出力を UTF-8 に統一（CP932 で `UnicodeEncodeError` が出ていた）。テストも UTF-8 で読む。
- `write` の Bus フェーダーの位置探索。書き込み後の検証を表番号で区別し、名前が空の表どうしが衝突しないようにした。
- EQ band2〜5 の Hz だけの書き込みを拒否（Resolve は Hz だけでは反映しない）。ノブ位置・帯域も必要。

### 追加（ドキュメント）
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
