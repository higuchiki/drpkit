# CLI reference

```text
drpkit <command> [options]

  read     read Fairlight mixer settings or edit information (read-only)
  write    analysis only: write raw int32 mixer values into a new copy of a .drp
  compose  build a new .drp from a template + media + cut list

drpkit -V | --version
drpkit <command> -h
```

`drpkit` alone prints the usage and exits with 2; an unknown command also exits with 2.

## drpkit read

```text
drpkit read [-h] [--timeline TIMELINE] [--json] [--all] [--expect EXPECT] [--edits] path
```

| Argument | Meaning |
|---|---|
| `path` | a `.drp` file (opened as a zip, read only) or a `Project.db` (SQLite, `mode=ro&immutable=1`). The file type is chosen by the `.drp` extension; anything else is treated as `Project.db` |
| `--timeline NAME` | only this timeline. Without it every timeline that has a Fairlight model is printed |
| `--json` | machine-readable output instead of Markdown |
| `--all` | also print plugin knobs that are not in the map (raw normalized value) and the raw state flags of plugins |
| `--expect FILE` | compare with expected values (YAML, below). Prints `一致 N 件／不一致 M 件` (matches / mismatches) and each mismatch; exit code 1 if anything differs, 0 otherwise |
| `--edits` | print edit information (clips, fades, keyframes, transitions, clip colors, markers) instead of the mixer |

Exit codes: 0 = done; 1 = `--expect` mismatch; 2 = no timeline with an `FLStudioModelBA` found (mixer mode).

### Mixer output (`--json`)

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

- One strip per **column**: a stereo track gives two strips with the same name (`column` 0 and 1 of that table position). Buses have `"type": "bus"`.
- `values` keys are the item names of the [map](fairlight-model.md#all-channel-items); `raw` is the stored int32; `conf` is the [confidence](fairlight-model.md#confidence-marks).
- `slot` is `Slot1` … `Slot6` (insert slots) or `内蔵FX(n)` (track built-in FX, n = 6–10). See [Plugins](plugins.md).
- Values the reader cannot convert are reported as `未較正(raw=…)` (not calibrated) or `画面空欄(raw=…)` (the UI shows a blank field), with `conf` `uncal`.

### `--expect` file

```yaml
timeline: Fixture            # optional: only this timeline
strips:
  Track1: {comp_threshold: -15 dB, comp_ratio: "2.0:1", Voice Isolation.enabled: "ON"}
  Bus 1:  {limiter_on: "ON"}
```

Keys are item names, or `Plugin.label` for plugin values. Each expected value is compared as a string with the converted `value` exactly as printed (without the confidence mark). Examples: `tests/expect_fixture_default-01.yaml`, `tests/expect_fixture_roundtrip-01.yaml`.

### Edit output (`--edits --json`)

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

| Key | Meaning |
|---|---|
| `start`, `end`, `duration` | timeline frames (`end` = `start + duration`) |
| `src_in`, `src_out` | source frames; `src_out` = `src_in + duration` |
| `fade_in`, `fade_out` | fade lengths in frames (only when stored) |
| `fade_in_curve`, `fade_out_curve` | curve point `[position %, level in 0.1 dB]` (only for curved fades) |
| `volume_db` | clip volume in dB |
| `volume_db_keyframes` | `[{frame: source frame, value: dB, flags}]` |
| `clip_plugins` | clip built-in FX (Voice Isolation, Dialogue Leveler); present = enabled |
| `start_tc` | timecode of `start` (`.drp` only) |
| `markers[].frame` / `offset` | absolute timeline frame / frames from the timeline start |

`fps` and `start_frame` come from the `.drp`; for a `Project.db` they are `null` and markers carry only `offset`. Details: [Clips & edits](clips-edits.md).

## drpkit compose

```text
drpkit compose [-h] --cuts CUTS --media TRACK=FILE [--media ...] [--timeline TIMELINE] [--keep-clip-fx] template output
```

| Argument | Meaning |
|---|---|
| `template` | template `.drp` (read only) |
| `output` | new `.drp`; must not exist |
| `--cuts FILE` | cut list, `.json` or `.csv` ([format](cut-list.md)). Relative `media` paths in it are resolved from the cut list's folder |
| `--media N=FILE` | audio file for audio track N (1-based, in template order). **Every** audio track of the template timeline must be given once. `N=@template` keeps the template's own media for that track (cuts, fades and keyframes are still applied) |
| `--timeline NAME` | template timeline; required when the template has several timelines |
| `--keep-clip-fx` | carry over each track's clip volume, volume keyframes and the other effects in `EffectFiltersBA` from the template's earliest clip on that track; fades and keyframes in the cut list take precedence. Without it, new clips get clip volume 0 dB. (Clip built-in FX — Voice Isolation, Dialogue Leveler — live in the clip's `FieldsBlob`, which every new clip copies from that same earliest clip in either case; see [Clips & edits](clips-edits.md#clip-built-in-fx).) |

On success it prints a JSON report (`fps`, `timeline_start_frame`, `markers`, `cuts`, `media`, `extra_media`, `preservation`). On any error it prints the reason and exits with 2; no output file is created.

What it changes and what it keeps: the template's audio items and their clip colors are replaced, the media-pool items of the template tracks are pointed at your files (metadata from `ffprobe`, see [Media](media.md)), the sequence extents are set to the first and last cut, and markers are written if the cut list has `markers`. Everything else — the Fairlight model (mixer, plugins, buses, routing), video, color, Fusion, other media-pool items — is compared before writing and must be byte-identical.

Refused rather than guessed: overlapping clips (use adjacent cuts and a `crossfade`), items other than audio clips and transitions on the audio tracks, the same media on several tracks, one media-pool item shared by tracks, `source_out` beyond the media, channel changes where the template's channel mapping is not the default, unsupported media formats.

## drpkit write

`write` accepts explicit `@A1` / `@A2` selectors for mixer
`strip_id` 0 / 1, including unnamed tracks and their continuation channels.
These are not localized UI names. The reader displays these aliases for unnamed
tracks; ambiguous layouts are refused.

EQ band 2–5 frequency writes require the matching knob and range items in the
same request. Resolve can restore the previous frequency when only Hz is written.
The following band 2 tuple was verified in Windows Resolve Free 19.1.3:

```text
drpkit write in.drp out.drp --set "Bus 1:0xf2=1000" --set "Bus 1:0x335=218" --set "Bus 1:0x289=1"
drpkit write in.drp fader.drp --set "@A1:0x1=-90" --set "Bus 1:0x1=-30"
```

### EQ frequency in whole Hz (`--eq-freq`)

```text
drpkit write in.drp out.drp --eq-freq "Bus 1:2=1234" --eq-freq "@A1:4=4321"
drpkit write roundtrip.drp --verify-eq --eq-freq "Bus 1:2=1234" --eq-freq "@A1:4=4321"
```

`NAME:BAND=HZ` synchronizes Hz, logarithmic knob, and range. Repeatable. Band 1:
30–399 Hz; band 6: 1400–22000 Hz; bands 2–5: 30–22000 Hz. Only finite integer
Hz are accepted. The current range is retained when possible, otherwise the
first compatible L/ML/MH/H range is selected. Overlapping requests and raw
`--set` writes to the same frequency/knob/range cells are refused.

Exact preservation of every Hz is **not guaranteed**. Windows Free 19.1.3 retained
17 of 18 tested settings exactly; Bus band 5 at 1399 Hz became 1392 Hz. A GUI-only
enter/export/import control reproduced that case. Writes emit a stderr notice.
Check the actual re-export using read-only `--verify-eq`: exit 0 on match, 1 on
mismatch, 2 on invalid verification arguments.

```text
drpkit write [-h] [--set NAME:ITEM=VALUE ...] [--eq-freq NAME:BAND=HZ ...] [--verify-eq] [--dump-item ITEM] [--timeline TIMELINE] src [dst]
```

| Argument | Meaning |
|---|---|
| `src` | input `.drp` (read only) |
| `dst` | output `.drp`; must not exist. Required with `--set` |
| `--set NAME:ITEM=VALUE` | write the int32 `VALUE` (decimal or `0x…`) into item `ITEM` (e.g. `0x10d`) of the strip `NAME` — a track name as stored in item `0xBC`, or `Bus 1`. A stereo track is written in all columns with that name. Repeatable |
| `--dump-item ITEM` | print that item's values in every table (first 6 columns) and exit; no output file |
| `--eq-freq NAME:BAND=HZ` | EQ band 1–6 frequency in whole Hz; the knob and range items are written too. Repeatable |
| `--verify-eq` | read only: compare `src` (a re-export) with the `--eq-freq` requests; exit 0 match, 1 mismatch, 2 invalid arguments. No `dst`, no `--set` |
| `--timeline NAME` | timeline to write; required when the `.drp` has several timelines with a Fairlight model |

Each written cell is read back and compared; the output is created only if exactly the requested cells changed. It prints one line per write (`書込 NAME 0x… = VALUE（列 …）`). Use it only on copies, to build conversion tables: write a stored value → import into Resolve → read the UI.

Windows CLI output is UTF-8; callers must decode it explicitly. The reader also supports Resolve 19 timeline markers and unnamed edit-track aliases such as `@A1`.

Stored-value equality does not guarantee DSP accuracy. In Windows Free 19.1.3 steady 440 Hz tests, a -6 dB fader matched within 0.000001 dB. EQ +6 dB / Q2 produced +8.108108 dB with Fire, but +6.000000 dB with Earth; fix the EQ style when comparing gain.

Compressor `comp_mix` (0x117) is the GUI Mix value, not a wet percentage. With threshold -30 dB, ratio 3:1 and makeup 0 dB, Mix 0 rendered compressed audio only. Mix 50, 75 and 100 matched `Mix0_audio + (Mix/100)^2 * unprocessed_audio` within one 24-bit sample step in two steady windows. Mix 100 therefore added unprocessed audio to the compressed audio, explaining the measured +3.028825 dB. This is an empirical result for that setup/version, not a general DSP guarantee. Keep raw/GUI values unchanged; do not invert or square values when writing DRP files.
