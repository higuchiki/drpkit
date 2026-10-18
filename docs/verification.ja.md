# 検証

すべて **macOS の DaVinci Resolve Studio 21.1.1** で確かめています。ほかの版と無償版は未検証です。方法はいつも同じで、1か所だけ変え（画面で、スクリプトAPIで、または `drpkit write` で保存値を書いて）、書き出して比べます。音に関わるものは**書き出して測ります**。

## reader

| 対象 | 方法 |
|---|---|
| 初期値 | 新規プロジェクトのミキサーを、画面とユーザーマニュアルの初期値と照合（`tests/expect_fixture_default-01.yaml`） |
| 内蔵 Dynamics | 画面で読んだ 309 値：23 プロジェクト × 10 つまみの書き込み掃引＋個別の点（[換算](conversions.md#built-in-dynamics)）。表に使っていない 20 点での盲検 |
| writer の往復 | writer → Resolve に読み込み → 書き出し：書いた値がすべて残る（`tests/expect_fixture_roundtrip-01.yaml`） |
| フェーダー | トラック −60／−200 と Bus −60／−200／+60 が書き出しで −6.0／−20.0／+6.0 dB。Bus フェーダー −20 dB はちょうど 20.0 dB 小さく書き出される。Bus のミュートで無音 |
| EQ | 種類・周波数・ゲイン・Q（6点）・レンジ・スロープを画面で1つずつ設定 |
| 処理順 | 6通りすべてを画面で選択 |
| プラグインのつまみ | 一次式のつまみごとに2点以上の画面値＋画面で見た目盛 |
| トラック Voice Isolation の有効／無効 | 2つのトラックで画面から切替、および `Timeline.SetVoiceIsolationState` |
| クリップ音量とフェード | `SetFades` の 0/0・48/24・100/7 と FCPXML のクリップ音量 −6 dB。読み込み直しても残る |
| フェードのカーブ | カーブ点 25／50／75／78 % で書き出して測定、ほかに画面で作った7例 |
| 音量キーフレーム | 画面で +20 秒／+25 秒／+30 秒12フレームに付けたキー、フレームの起点を決めるための In＝144 のクリップ、合成音の書き出しで補間を測定 |
| クリップ内蔵FX | `SetVoiceIsolationState` と `SetProperty` で設定・解除 |
| マーカー | `Timeline.AddMarker` で作った16色・長さ1〜24・日本語・XML 記号・customData。4本の書き出しを符号化し直すとバイト単位で一致 |
| タイムラインの開始 | 読み込み後に 24 fps で 3600 秒 → `GetStartFrame()` 86400、0 → 0 |

## compose

| 対象 | 方法 |
|---|---|
| 素材の形式 | 28通りの素材形式（WAV 16/24/32f、FLAC 16/24、AAC、MP3 × 44.1/48 kHz × モノラル/ステレオ）を網羅する 56 本の合成プロジェクトを読み込み、全クリップが指定の位置・In 点・フェードで *オンライン* になり、両チャンネルで音が出る |
| ミキサーの保持 | プラグインと Dynamics を持つ4話者のテンプレートに、カット・クロスフェード・フェードアウト・キーフレームを入れて合成。ミキサーが保たれ、区間ごとのラウドネスが原本と一致（0.0 LU） |
| 1トラックに複数素材 | モノラルのトラックにモノラル FLAC とステレオ WAV を並べ、それぞれ1つのメディアプール項目として *オンライン* で読み込み |
| マーカー | マーカーのないテンプレートへの書き込み、既存マーカーの置き換え、最初のカットがテンプレートの先頭にないタイムラインでの絶対フレーム指定。すべて `Timeline.GetMarkers()` で同じ値が読めた |

## 自動テスト {#automated-tests}

```bash
python3 -m unittest discover -s tests -t . -v
```

GitHub Actions が Ubuntu と macOS、Python 3.9 と 3.12 で実行し、コミットされた全 `.drp` のプライバシー検査も行います。compose のテストには `ffmpeg`／`ffprobe` が必要です。

| テスト | 確かめること |
|---|---|
| `test_dyn_law` | Dynamics の換算を、Resolve の画面で読んだ値と照合 |
| `test_fixtures` | reader の初期値と往復、フェード、Bus フェーダー、writer（指定したセルだけが変わる・上書きを拒否・エラー時に出力も一時ファイルも残さない・複数タイムラインでの `--timeline`） |
| `test_drp_compose` | 合成：reader での往復、ミキサーと zip のバイト単位の保持、28形式の素材情報を Resolve 自身の書き出しと照合、不正なカット表を出力なしで拒否、書いたファイルを読み直してカット表と照合（Duration／In／素材パス／クロスフェードを改ざんすると拒否）、書き込み失敗時にファイルを残さない、クロスフェードの余白、キーフレーム、クリップFX の引き継ぎ |
| `test_markers_media_cli` | トラック Voice Isolation の有効／無効、マーカー（読み取り・バイト単位の再符号化・compose での追加／置換／保持／消去・不正入力）、1トラックに複数の素材、`drpkit` コマンド、プライバシー検査そのもの |

ドキュメントのビルドでは、生成した表が `drpkit/fairlight_map.yaml` と一致することも確かめます（`python tools/gen_map_docs.py --check`）。

## テスト用 fixture

fixture は合成したものです：生成した正弦波を置いた新規の Resolve プロジェクト。**実案件や収録音声は含みません**。fixture は `.drp` の書き出しだけなので、Resolve に読み込むと素材はオフライン表示になります（テストには不要）。

`.drp` はコミット前に `tools/sanitize_drp.py` を通し、機器 ID、Resolve のユーザー UUID（公開用の固定値に置換）、プロジェクト設定に保存される絶対パスを消します。`tools/sanitize_drp.py --check` が何も報告しないことが条件です。検査はホーム／ボリュームのパス（macOS・Linux・Windows）、メールアドレス、機器 ID とユーザー UUID を、16進のブロブや zlib／zstd のストリームの中まで再帰的に展開して探します。

最初の fixture を Resolve で再リンクするには、プロジェクトが期待するパスに2つのファイル（10 秒・48 kHz・モノラル・16 ビット）を作ります。

```bash
mkdir -p /tmp/rfr-fixture
ffmpeg -f lavfi -i "sine=frequency=1000:sample_rate=48000:duration=10" -ac 1 -c:a pcm_s16le /tmp/rfr-fixture/sine1k.wav
ffmpeg -f lavfi -i "anullsrc=r=48000:cl=mono" -t 10 -c:a pcm_s16le /tmp/rfr-fixture/silence.wav
```

## 根拠の限界

- 較正表（※）を、それを作ったのと同じ Resolve の版で照合しても循環します。独立した根拠は盲検と書き出しの測定です。
- ミキサーがバイト単位で同じでも、あらゆる場合に音が同じとは限りません。ラウドネスの比較は1つのテンプレートについてのものです。
- どれも Resolve の更新で変わる可能性があります。
