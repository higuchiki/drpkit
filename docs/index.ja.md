# drpkit

DaVinci Resolve のプロジェクトファイルを **Resolve を起動せずに**扱うツールです。`.drp`（書き出したプロジェクト）は読み書き、ディスクDBの `Project.db` は**読み取りのみ**です（`write`・`compose` は `.drp` だけが対象）。

`非公式` · `MIT License` · `Python 3.9+`

このサイトは drpkit の仕様書の全体です。コマンド、カット表、そして Resolve が Fairlight ミキサー・クリップ・マーカー・素材をどう保存しているかについて分かっていることすべてを、項目ごとの根拠つきでまとめています。

## できること

### `drpkit read`

Fairlight ミキサー設定（トラック・Bus・内蔵EQ・内蔵Dynamics・プラグイン）と編集情報（クリップ・フェード・キーフレーム・トランジション・クリップ色・タイムラインマーカー）を、画面に表示される値に換算して出力します。

```bash
drpkit read project.drp
drpkit read project.drp --json
drpkit read project.drp --edits
drpkit read Project.db --timeline "Main"
```

### `drpkit compose`

テンプレートプロジェクト・音声ファイル・カット表から新しい `.drp` を組み立てます。テンプレートのミキサーはそのままバイト単位で保持されます。

```bash
drpkit compose TEMPLATE.drp OUT.drp --cuts cuts.json \
    --media 1=host.wav --media 2=guest.flac
```

### `drpkit write`

`.drp` のコピーで、既にあるミキサー設定の値を書き換えます。生の値（換算表づくり用）か、`--eq-freq` で EQ 周波数を整数Hzで指定します。Resolve は読み込み時に一部の値を変えることがあるので、読み込んで書き出し直したファイルを `--verify-eq` で確認してください。[コマンド](cli.md#drpkit-write)参照。

```bash
drpkit write IN.drp OUT.drp --set 'Track1:0x10d=51996'
```

macOS の Resolve Studio 21.1.1 で確認。無料版は Windows 11 の DaVinci Resolve 19.1.3（build 7）・Python 3.10.6 で、読み取り・`write`・`compose` を確認しました（[検証](verification.md)）。21.1.1 の無料版を含むほかの版は未検証です。ファイルだけを扱い、Resolve 本体やスクリプトAPIは一切使いません。

## 対応範囲

| 項目 | 読み取り | 書き込み／compose |
|---|---|---|
| ストリップ基本 | フェーダー・ミュート・ソロ・パン・ルーティング・Busチャンネル数・StripID | 生の値（`write`） |
| 内蔵EQ・Dynamics | 各バンド・ノブを画面表示値に換算 | 生の値 |
| プラグイン | De-Esser・Vocal Channel・Limiter・Voice Isolation・Dialogue Leveler | `compose` でバイト単位保持 |
| クリップ | 位置・フェード・色・キーフレーム・クリップFX | 位置・ソースIn/Out・メディア・色・フェード・ボリュームキーフレーム |
| タイムラインマーカー | フレーム・色（16色）・名前・ノート・長さ | 同上 |
| 未解読 | トラックのオートメーション、キーフレームのフラグ、プラグインのバイパス、Busのソロ、トラック単位のDialogue Leveler | |

項目番号つきの全一覧：[Fairlight ミキサー](fairlight-model.md)・未解決の点：[未解読](unresolved.md)

## インストール

```bash
pip install git+https://github.com/higuchiki/drpkit.git
drpkit --version
```

`compose` には `PATH` 上の `ffprobe`（FFmpeg）が必要です。`Project.db` のクリップFXと圧縮マーカーを読むには Python 3.14 以上、または `zstandard` パッケージが必要です。詳しくは [はじめに](getting-started.md)。

## 安全性

- `read` は入力を一切変更しません。`.drp` は読み取り専用で zip として開き、`Project.db` は読み取り専用・変更不可で開きます。
- `write` と `compose` は上書きしません（出力先が既にあれば拒否）。一時ファイルに書き出して読み直し・検証し（`compose` は全クリップをカット表と照合）、合格したときだけ一度に出力名へ移します。失敗時は出力ファイルを残しません。
- 結果は本番とは別の検証用プロジェクトライブラリに読み込み、原本のバックアップを保持してください。

!!! warning "非公式プロジェクトです"
    Blackmagic Design 社とは無関係・提携・支援関係はありません。「DaVinci Resolve」「Fairlight」は Blackmagic Design Pty. Ltd. の商標です。ファイル形式は観察によって解読したもので、Resolve の更新で変わることがあります。

    常にコピーで作業してください。`write` と `compose` の出力は別の検証用プロジェクトライブラリで使い、Resolve 上で結果を確認してから本番に反映してください。**無保証**：プロジェクトの破損・消失について作者は責任を負いません。自己責任でご利用ください。詳細は [LICENSE](https://github.com/higuchiki/drpkit/blob/main/LICENSE) を参照してください。

## 先行例

[samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp)（MIT）は同じ内部データを扱い、Bus の構成・ルーティングの読み書きを実装しています。このデータが読み取れることを示してくれた同プロジェクトに感謝します。drpkit は別の領域（内蔵Dynamics・EQの画面値換算、フェーダー、ソロ、処理順、プラグインのノブ、トラックのVoice Isolation状態、編集情報、マーカー）を独自に特定して扱っています。Bus の構成やルーティング変更が必要な場合は davinci-resolve-mcp を使ってください。詳しくは [先行例](prior-work.md)。

---

[github.com/higuchiki/drpkit](https://github.com/higuchiki/drpkit) · MIT License — © Kiyonori Higuchi
