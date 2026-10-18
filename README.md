# drpkit

Read and edit DaVinci Resolve project files **without opening Resolve**: `.drp` exports can be read and written; the disk-database `Project.db` is **read only** (`write` and `compose` work on `.drp` files only).

- `drpkit read` — Fairlight mixer settings (tracks, buses, built-in EQ / Dynamics, plugins) and edit information (clips, fades, keyframes, transitions, clip colors, timeline markers), converted to the values shown in the UI.
- `drpkit compose` — build a new `.drp` from a template project, your audio files and a cut list. The template's whole mixer is kept byte for byte.
- `drpkit write` — analysis only: write raw values into the mixer tables of a copy of a `.drp`.

Checked with DaVinci Resolve Studio 21.1.1. The free version is not verified. drpkit only touches files, never the Resolve application or its scripting API.

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by Blackmagic Design. "DaVinci Resolve" and "Fairlight" are trademarks of Blackmagic Design Pty. Ltd. The file format was worked out by observation and may change in any Resolve release.

## Install

Python 3.9 or newer. The only dependency is PyYAML.

```bash
pip install git+https://github.com/higuchiki/drpkit.git        # or, in a checkout: pip install .
pip install "drpkit[zstd] @ git+https://github.com/higuchiki/drpkit.git"   # + zstandard, see below
drpkit --version
```

- `drpkit compose` needs `ffprobe` (part of [FFmpeg](https://ffmpeg.org/)) on `PATH` to read the media. `read` and `write` do not.
- Reading clip effects from a `Project.db`, and reading timeline markers stored compressed, needs Python 3.14+ (built-in `compression.zstd`) or the `zstandard` package (`drpkit[zstd]`). Everything else works without it.
- The old entry points `fairlight_reader.py`, `fairlight_writer.py` and `drp_compose.py` still work in a checkout; they call the same code.

## Safety

- `read` never modifies its input: a `.drp` is opened as a zip for reading, a `Project.db` with SQLite `mode=ro&immutable=1`.
- `write` and `compose` never overwrite: the output path must not exist. Every change is built in memory and checked first — only the intended cells / items differ from the input, everything else is byte-identical. The result is then written to a temporary file next to the output, read back and checked again (`compose` re-reads it with the reader and compares every audio clip and crossfade with the cut table: track, order, position, source In/Out, fades, volume keyframes, color, media file); only when that passes is it moved to the output name in one step (hard link, or rename where links are unsupported). On any error the temporary file is removed and no output file is created.
- Import results into a **separate project library used only for testing**, keep a backup of the original, and check the result in Resolve before relying on it.
- **No warranty.** The author accepts no responsibility for corrupted or lost projects. Use it at your own risk (see [LICENSE](LICENSE)).

## drpkit read

```bash
drpkit read project.drp                   # Markdown tables, one per mixer strip
drpkit read project.drp --json            # machine-readable
drpkit read Project.db --timeline "Main"  # disk database, one timeline
drpkit read project.drp --all             # also unmapped plugin knobs and plugin state flags (raw)
drpkit read project.drp --edits           # clips, fades, keyframes, transitions, colors, markers
drpkit read project.drp --expect my.yaml  # compare with expected values; exit 1 on mismatch
```

`--expect` format (see `tests/expect_fixture_default-01.yaml`); plugin values are `Plugin.label`:

```yaml
timeline: Fixture
strips:
  Track1: {comp_threshold: -15 dB, comp_ratio: "2.0:1", Voice Isolation.enabled: "ON"}
  Bus 1:  {limiter_on: "ON"}
```

Output labels and some messages are in Japanese (the tool was first written for a Japanese workflow); values and units are plain numbers. Item ids and conversions live in one file, [`drpkit/fairlight_map.yaml`](drpkit/fairlight_map.yaml); the binary layout is described in [FORMAT.md](FORMAT.md).

## drpkit compose

```bash
drpkit compose TEMPLATE.drp OUT.drp --cuts cuts.json \
    --media 1=host.wav --media 2=guest.flac --media 3=@template [--timeline "Main"] [--keep-clip-fx]
```

- The template's audio tracks are emptied and refilled with your cuts; the mixer (EQ, Dynamics, plugins, buses, routing), the media pool's other items and the rest of the archive stay byte for byte.
- `--media N=FILE` for **every** audio track of the template timeline (1-based). `N=@template` keeps the template's own media for that track.
- `--timeline` is required when the template has several timelines.
- `--keep-clip-fx` carries over each track's clip volume, volume keyframes and clip effects (Voice Isolation, Dialogue Leveler) from the template's earliest clip; fades and keyframes in the cut list take precedence.
- Import the result in Resolve with *File → Import Project*.

### Cut list

JSON, or CSV with the same column names (CSV has no `markers`). All values are **frames** at the timeline frame rate; `source_out` is exclusive; `timeline_start` is the absolute timeline frame (a timeline starting at 01:00:00:00 at 24 fps begins at 86400). The output timeline starts at the earliest cut.

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

| Column | Meaning |
|---|---|
| `track` / `tracks` | one track, a list, or `"all"` |
| `source_in`, `source_out`, `timeline_start` | integer frames |
| `media` | optional: this cut's own audio file (for example several BGM files on one track). Relative paths are relative to the cut list file. Empty = the track's `--media`. Each extra file becomes a new media-pool item; the same file may not be used on two tracks |
| `fade_in`, `fade_out` | frames (optional) |
| `crossfade` | even number of frames, centered on the joint with the directly preceding cut on that track; needs source handles on both sides and no fade at that joint |
| `volume_keyframes` | `[[source frame, dB], ...]` — frames are **source** frame numbers (the clip starts at `source_in`); linear in dB between keys |
| `color` | one of the 16 clip colors: Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate |

Timeline markers (`markers`, JSON only):

| Key | Meaning |
|---|---|
| `frame` **or** `offset` | `frame` = absolute timeline frame (same scale as `timeline_start`); `offset` = frames from the timeline start (what `Timeline.GetMarkers()` returns) |
| `name` | required (Resolve does not create unnamed markers) |
| `color` | Blue (default), Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream |
| `note`, `custom_data` | optional text |
| `duration` | frames, default 1 |

Without `markers` the template's markers are kept as they are; with `markers` they are replaced (`[]` removes them).

Supported media: WAV 16/24-bit and 32-bit float, FLAC 16/24-bit, AAC (`.m4a`, LC) and MP3, at 44.1 or 48 kHz, mono or stereo. Anything else is rejected rather than guessed.

## drpkit write (analysis only)

Writes arbitrary int32 values into the channel settings tables of a **copy** of a `.drp`, to build conversion tables (write a stored value → import into Resolve → read the UI).

```bash
drpkit write IN.drp OUT.drp --set 'Track1:0x10d=51996' --set 'Bus 1:0x11d=1'
drpkit write IN.drp OUT.drp --timeline "Main" --set 'Track1:0x001=-60'   # required with several timelines
drpkit write IN.drp --dump-item 0x10d
```

Every written cell is re-read and compared; the output is created only if exactly the requested cells changed. Never point it at a project you care about.

## What is supported

| Area | Read | Write / compose | Not decoded |
|---|---|---|---|
| Strip basics | fader (tracks, buses), pre-dynamics gain, mute, solo, pan on/off, pan L/R, track selection (UI state), output connected, output bus, bus channel count, strip id | raw cells (`write`) | bus solo / bus pan (seen, unverified), `0x0B9`, `0x13B`, `0x008` / `0x009` |
| Strip processing | Effects In, EQ master on/off, processing order (6 orders) | raw cells | — |
| Built-in EQ | bands 1–6: on/off, type, frequency, gain, Q, range, slope | raw cells | — |
| Built-in Dynamics | compressor, expander/gate, limiter: every knob converted to UI values | raw cells | meaning of non-zero `0x11B` |
| Plugins | De-Esser, Vocal Channel, Limiter, Voice Isolation, Dialogue Leveler knobs; other plugins raw (`--all`) | kept byte for byte by `compose` | plugin bypass; state flags of insert plugins |
| Track built-in FX | Voice Isolation amount and **on/off** | kept | track-level Dialogue Leveler settings |
| Automation | clip volume keyframes | clip volume keyframes | track automation lanes (fader / plugin automation); keyframe flags (`0x000C0000` for UI-made keys) |
| Clips | position, duration, source in/out, color, fade lengths, fade curve point, clip volume, clip Voice Isolation / Dialogue Leveler | position, source in/out, media (one or several files per track), color, fade lengths, clip volume keyframes; clip FX inherited with `--keep-clip-fx` | fade curve shape away from its point |
| Transitions | type, length, alignment | Cross Fade 0 dB, centered | — |
| Timeline markers | frame, color (16), name, note, duration, customData | same | — |
| Anything else (color, titles, video, Fusion) | — | kept byte for byte by `compose` | not read |

Details and evidence for each item: [FORMAT.md](FORMAT.md) ([unresolved items](FORMAT.md#unresolved)).

### Confidence marks

Every converted value carries a mark that tells you how it was established.

| Mark | `conf` | Meaning |
|---|---|---|
| (none) | `direct` | stored value as-is or times a constant; cross-checked against known UI values |
| ² | `two_point` | linear / log formula fixed by two or more known points |
| ※ | `calib` / `law` | lookup table built from UI readings (interpolated for Dynamics). Unknown stored values print `未較正(raw=…)` |
| ? | `assumed` | single point, range assumed — reference only |
| ✗ | `raw` / `uncal` | meaning unknown or not calibrated; raw value only |

Built-in Dynamics conversion accuracy: generally within ±1 % (last displayed digit); hold/release around knob position 100–250 can be off by more. See [FORMAT.md](FORMAT.md#built-in-dynamics-conversion).

### What was checked in DaVinci Resolve Studio 21.1.1 (macOS)

Other versions are untested.

- Reader: factory defaults of a new project; 309 Dynamics values read on the UI (write sweep of 23 projects × 10 knobs + individual points); writer → import → export round trip keeps every written value; bus fader −20 dB renders exactly 20.0 dB quieter; fade curves by render; track Voice Isolation on/off toggled in the UI and with the scripting API; 16 marker colors, durations, Japanese text, XML characters and customData made with `Timeline.AddMarker`.
- Compose: 56 composed projects covering all 28 media format combinations imported with every clip *Online* at the requested positions, In points and fades, audible on both channels; a 4-speaker template with plugins and Dynamics composed with cuts, a crossfade, a fade-out and keyframes kept its mixer and matched the original's loudness section by section (0.0 LU); several media files on one track (mono FLAC and stereo WAV on a mono track) imported *Online* with one media-pool item each; markers written into a template without markers, replacing existing markers, and with absolute frames on a timeline whose first cut is not at the template start, all read back identically by `Timeline.GetMarkers()`.

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

GitHub Actions runs them on Ubuntu and macOS with Python 3.9 and 3.12. The compose tests need `ffmpeg` / `ffprobe`.

| Test | What it checks |
|---|---|
| `test_dyn_law` | Dynamics conversion vs. values read on the Resolve UI |
| `test_fixtures` | reader defaults and round trip, fades, bus fader, writer (only requested cells change, refuses to overwrite, no output and no temporary file left on error, `--timeline` with several timelines) |
| `test_drp_compose` | composition: reader round trip, mixer and archive preserved byte for byte, media metadata for 28 formats against Resolve's own exports, invalid cut lists rejected without output, written file read back and checked against the cut table (a tampered Duration / In / media path / crossfade is refused), no file left on a failed write, crossfade handles, keyframes, clip FX inheritance |
| `test_markers_media_cli` | track Voice Isolation on/off, markers (read, byte-exact re-encode, compose add / replace / keep / clear, invalid input), several media files per track, the `drpkit` command line, and a privacy scan of every committed `.drp` (the scanner itself is tested on paths, e-mail addresses and user UUIDs hidden in UTF-16, hex, zlib and zstd) |

Fixtures are synthetic: new Resolve projects with generated sine tones. **No real projects or recordings are included**, and fixtures carry only `.drp` exports — imported into Resolve their media shows as offline (the tests do not need it). Before a `.drp` is committed it goes through `tools/sanitize_drp.py`, which neutralizes the machine id, the Resolve user UUID (replaced by a fixed public one) and the absolute paths Resolve stores in the project settings, and `tools/sanitize_drp.py --check` must report nothing. The check looks for home / volume paths (macOS, Linux, Windows), any e-mail address, machine ids and user UUIDs, also inside hex blobs and zlib / zstd streams, unpacked recursively.

To relink the first fixtures in Resolve, generate the two files (10 s, 48 kHz, mono, 16-bit) at the paths the project expects (`/tmp/rfr-fixture/sine1k.wav`, `/tmp/rfr-fixture/silence.wav`):

```bash
mkdir -p /tmp/rfr-fixture
ffmpeg -f lavfi -i "sine=frequency=1000:sample_rate=48000:duration=10" -ac 1 -c:a pcm_s16le /tmp/rfr-fixture/sine1k.wav
ffmpeg -f lavfi -i "anullsrc=r=48000:cl=mono" -t 10 -c:a pcm_s16le /tmp/rfr-fixture/silence.wav
```

## Prior work

[samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp) (MIT) already works with the same `FLStudioModelBA` blob (`resolve-advanced/vendor/fairlight/index.js`) to read and create bus configuration and routing. Many thanks to that project for showing that this data is reachable.

This tool covers a different area of the same blob — built-in Dynamics and EQ converted to UI values, fader, solo, processing order, Effects In, EQ master switch, track selection, plugin knobs and track Voice Isolation state — plus edit information and markers. These were identified independently by comparing the UI with exports and by measuring renders. The bus channel count (`0x1B4`) and strip id (`0x458`) items follow that project's findings, which our data confirms. See the top of [FORMAT.md](FORMAT.md). If you need to build buses or change routing, use davinci-resolve-mcp.

---

## 日本語

DaVinci Resolve のプロジェクトファイルを **Resolve を起動せずに**扱うツールです。`.drp`（書き出したプロジェクト）は読み書き、ディスクDBの `Project.db` は**読み取りのみ**です（`write`・`compose` は `.drp` だけが対象）。Resolve Studio 21.1.1 で確認。無償版は未検証です（ファイルだけを扱い、Resolve 本体やスクリプトAPIは使いません）。

- **非公式ツールです。Blackmagic Design 社とは無関係です。** 形式は観察で解読したもので、Resolve の更新で変わることがあります。動作確認は DaVinci Resolve Studio **21.1.1**（macOS）のみ
- インストール：Python 3.9 以上で `pip install git+https://github.com/higuchiki/drpkit.git`。依存は PyYAML のみ。`compose` は FFmpeg の `ffprobe` が必要。Project.db のクリップFXと圧縮されたマーカーを読むには Python 3.14 以上か `zstandard`（`drpkit[zstd]`）
- コマンド
  - `drpkit read 入力.drp`：ミキサー設定（トラック・Bus・内蔵EQ・内蔵Dynamics・プラグイン・トラック内蔵 Voice Isolation の有効/無効）を画面の値に換算して一覧。`--edits` でクリップ位置・フェード・キーフレーム・トランジション・クリップ色・タイムラインマーカー
  - `drpkit compose テンプレ.drp 出力.drp --cuts カット表.json --media 1=音声.wav ...`：テンプレートのミキサーをそのまま残し、カット表どおりにクリップを並べた新しい .drp を作る。カット表の `media` 列で1トラックに複数の素材（BGM の連結など。相対パスはカット表の場所から）、`markers` でタイムラインマーカー（`frame`＝タイムライン上の絶対フレーム／`offset`＝タイムライン開始からのフレーム、名前は必須、16色）
  - `drpkit write`：解析専用。.drp のコピーのミキサー表へ生の値を書き込む
- 安全：読み取りは原本を変更しません。書き込み系はすべて、出力先が既にあれば拒否し（上書きしない）、全変更をメモリ上で検証したうえで一時ファイルに書き出し、読み直して再検証（`compose` は全クリップ・クロスフェードをカット表と照合）してから、一度に出力名へ移します。エラー時は一時ファイルを消し、出力を残しません。結果は**本番とは別の検証用プロジェクトライブラリ**に読み込み、原本のバックアップを保持してください。プロジェクトの破損・消失について作者は責任を負いません
- 確度記号：無印＝直読／²＝2点以上で式を確定／※＝画面値との対応表（Dynamics は補間）／?＝1点のみ・参考値／✗＝未確定
- 未解読：トラック単位の Dialogue Leveler 設定、トラックのオートメーション、キーフレームのフラグ、項目 `0xB9`、プラグインのバイパス、Bus のソロなど（一覧は英語版「What is supported」と [FORMAT.md](FORMAT.md#unresolved)）
- テスト用 fixture は合成音の新規プロジェクトから作った `.drp` のみで、実案件・収録音声は含みません。コミット前に `tools/sanitize_drp.py` で機器ID・設定内の絶対パスを消し、`--check` で0件を確認します
- 先行例：[samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp)（MIT）が同じ `FLStudioModelBA` を扱い、Bus の構成・ルーティングの読み書きを実装しています。本ツールの項目は画面との比較・書き出しの実測で独自に特定しました。Bus のチャンネル数（`0x1B4`）・Strip ID（`0x458`）は先行例の記述に従い、当方データで照合済みです

## License

MIT — see [LICENSE](LICENSE).
