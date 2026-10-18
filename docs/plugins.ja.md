# プラグイン

プラグインのパラメーターは **0〜1 に正規化された float32** で保存されています（[プラグイン記録](fairlight-model.md#plugin-records) 参照）。reader はここに挙げたパラメーターを換算し、それ以外は `--all` で生値を出します。`compose` はプラグインに触れず、バイト単位でそのまま残します。

プラグインの置き場所：

| 場所 | 位置 | 記録 |
|---|---|---|
| トラック／Bus の挿入スロット1〜6 | `FLStudioModelBA` | 種別・列・スロット 0〜5・所属 2 の `bmd:<名前>:<ID>` |
| トラック内蔵FX | `FLStudioModelBA` | スロット 6 Voice Isolation、7 Dialogue Leveler、8 Dialogue Separator、9 Music Remixer、10 Ducker |
| クリップ内蔵FX | クリップ自身の `FieldsBlob` | [クリップと編集](clips-edits.md#clip-built-in-fx) 参照 |

## 換算式

`p` は保存されている正規化値です。

| プラグイン | パラメーター | 画面値 |
|---|---|---|
| De-Esser | `BMDDeesser::RANGE`（周波数） | 700 · (9000 / 700)^p Hz、有効数字3桁で表示 |
| | `BMDDeesser::AMOUNT` | 100 · p % |
| | `BMDDeesser::MODE` | 0＝ナローバンド、0.5＝センターベル |
| | `Deesser::REACTION` | 0.5＝medium（観測した値のみ） |
| | `BMDDeesser::ESS_ONLY` | フラグ（「S のみ」） |
| Vocal Channel | `BMDVocalChannel::COMP_THRES` | −40 + 40p dB |
| | `BMDVocalChannel::COMP_RATIO` | 1.1 + 5.9p（`x:1`） |
| | `BMDVocalChannel::COMP_GAIN` | 20p dB |
| | `BMDVocalChannel::COMP_REACTION` | そのまま（0〜1） |
| | `HPF_IN`／`EQ_IN`／`COMP_IN` | フラグ（ハイパス・EQ・コンプレッサーの各部） |
| Limiter | `BMDLimiter::INPUT_GAIN` | −18 + 36p dB |
| | `BMDLimiter::THRESHOLD`（上限） | −24 + 24p dBTP |
| | `BMDLimiter::RELEASE` | 対応表：0.8829＝190.55 ms（較正した値はこれのみ） |
| | `BMDLimiter::SOFT` | フラグ |
| Voice Isolation（トラック内蔵スロット6、またはクリップ） | `BMDVoiceIsolationControl::DRY_MIX` | 100 · p＝量（37 → 0.3701、82 → 0.8201、55 → 0.55） |
| Dialogue Leveler（クリップ） | `UI_BAS_PRESET` | モード＝3p：0 ダイナミクスを広く、1 中程度のレベルに最適化、2 低いレベルをより持ち上げる、3 ささやき声を持ち上げる |
| | `UI_ADV_RIDER_ON`／`UI_BAS_LIFTER_ON`／`UI_BAS_CLEANER_ON` | フラグ：大きな声を抑える／小さな声を持ち上げる／背景ノイズ低減 |
| | `UI_BAS_OUTPUT_GAIN` | 6p dB（範囲 0〜6 dB） |

フラグは `p ≥ 0.5` で ON。対応表にない値は `未較正(raw=…)` と出します。

### 対応表から生成

--8<-- "map_plugins.ja.md"

一次式（`min + (max − min) × p`）は2点以上の画面値と、画面で見たつまみの目盛（範囲）で確定したもの（`two_point`）、対応表（`calib`）は画面で読んだ値だけを持っています。

## トラック Voice Isolation の有効／無効 {#track-voice-isolation-onoff}

トラック内蔵の Voice Isolation（スロット6）には有効／無効のパラメーターがありません。タグから 272 バイト目の u32 **状態フラグ**のビット `0x10` が有効／無効を表します。

| ビット `0x10` | 意味 |
|---|---|
| 立っていない | 有効 |
| 立っている | 無効（量は保存されたまま） |

- 2つのトラックで画面から切り替えて確認：変わるのはその1バイトだけ（2つの記録は 768 バイト離れている）で、量は変わらない。
- スクリプトAPI `Timeline.SetVoiceIsolationState` でも確認：無効にしたトラックについて API は量 0 を返すが、保存された量は残る。
- パラメーターの登録表（目印 `0x77668866`）も変わるが、状態を読むのには不要。
- 使っていない内蔵スロットも `0x10`。挿入プラグイン（`2` を観測）とほかの内蔵FX のフラグは**未解読**で、`--all` で `state_flags` として出します。

reader は `Voice Isolation.enabled`（`ON`／`OFF`）として出し、`--expect` でも使えます。

## 未解読

- プラグインのバイパス（挿入スロット）。
- トラック単位の Dialogue Leveler の設定：画面で設定するまでトラックの記録に `UI_…` のパラメーターがなく、API からも設定できない。
- ほかのプラグインのパラメーター（Vocal Channel の EQ バンド、Dialogue Separator、Music Remixer、Ducker、他社製プラグイン）：`--all` で生値。
