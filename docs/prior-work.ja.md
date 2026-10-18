# 先行例

## davinci-resolve-mcp

[samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp)（MIT）は、同じ `FLStudioModelBA` ブロブ（`resolve-advanced/vendor/fairlight/index.js`）を扱い、Bus の構成とルーティングの読み書きを実装しています。このデータが読み取れることを示してくれた同プロジェクトに感謝します。

Bus の構成やルーティングの変更が必要な場合は davinci-resolve-mcp を使ってください。

## 各知見の出どころ

| 出どころ | 項目 |
|---|---|
| 先行例：davinci-resolve-mcp（**当方のデータで照合済み**） | ミキサーが `FLStudioModelBA` ブロブにあること、Bus のチャンネル数 `0x1B4`、ストリップ番号 `0x458` |
| 当方の作業：画面と書き出したプロジェクトの比較（操作を1つ変える → 書き出す → 差分を取る）と、書き出し音声の測定 | それ以外すべて：ほかのチャンネル項目、内蔵 Dynamics の換算表、EQ、プラグインのつまみ、Bus 表の前半（フェーダー・ミュート）、トラックの選択、処理順、Effects In、EQ の主スイッチ、トラック Voice Isolation の状態、編集情報（クリップの位置・色・フェード・フェードのカーブ・キーフレーム・トランジション・クリップFX）、タイムラインマーカー、素材の情報 |

drpkit は同じブロブのうち davinci-resolve-mcp とは別の領域（内蔵 Dynamics と EQ の画面値への換算、フェーダー、ソロ、処理順、Effects In、EQ の主スイッチ、トラックの選択、プラグインのつまみ、トラック Voice Isolation の状態）と、編集情報・マーカーを扱います。これらは独自に特定しました。

## 公式の資料

ありません。Blackmagic Design は `.drp` と `Project.db` の形式を公開していません。スクリプトAPI（`Timeline.AddMarker`・`SetFades`・`SetVoiceIsolationState`・`GetMarkers`・`GetStartFrame`・`ExportProject`）は、**テスト用プロジェクトを作り結果を確かめるためだけに**使いました。drpkit 自体は API を呼びません。

「DaVinci Resolve」「Fairlight」は Blackmagic Design Pty. Ltd. の商標です。本プロジェクトは Blackmagic Design 社とは無関係で、提携・支援関係はありません。
