# Plugins

Plugin parameters are stored as **normalized float32 values from 0 to 1** (see [plugin records](fairlight-model.md#plugin-records)). The reader converts the parameters listed here; any other parameter is printed raw with `--all`. `compose` never touches plugins: they are kept byte for byte.

Where plugins are stored:

| Where | Location | Records |
|---|---|---|
| track / bus insert slots 1–6 | `FLStudioModelBA` | `bmd:<Name>:<ID>` with kind, column, slot 0–5, owner 2 |
| track built-in FX | `FLStudioModelBA` | slot 6 Voice Isolation, 7 Dialogue Leveler, 8 Dialogue Separator, 9 Music Remixer, 10 Ducker |
| clip built-in FX | the clip's own `FieldsBlob` | see [Clips & edits](clips-edits.md#clip-built-in-fx) |

## Conversion formulas

`p` is the stored normalized value.

| Plugin | Parameter | UI value |
|---|---|---|
| De-Esser | `BMDDeesser::RANGE` (frequency) | 700 · (9000 / 700)^p Hz, shown with 3 significant digits |
| | `BMDDeesser::AMOUNT` | 100 · p % |
| | `BMDDeesser::MODE` | 0 = narrow band, 0.5 = centered bell |
| | `Deesser::REACTION` | 0.5 = medium (only value seen) |
| | `BMDDeesser::ESS_ONLY` | flag (“S only”) |
| Vocal Channel | `BMDVocalChannel::COMP_THRES` | −40 + 40p dB |
| | `BMDVocalChannel::COMP_RATIO` | 1.1 + 5.9p (`x:1`) |
| | `BMDVocalChannel::COMP_GAIN` | 20p dB |
| | `BMDVocalChannel::COMP_REACTION` | as-is (0–1) |
| | `HPF_IN` / `EQ_IN` / `COMP_IN` | flags (high-pass, EQ, compressor sections) |
| Limiter | `BMDLimiter::INPUT_GAIN` | −18 + 36p dB |
| | `BMDLimiter::THRESHOLD` (ceiling) | −24 + 24p dBTP |
| | `BMDLimiter::RELEASE` | lookup: 0.8829 = 190.55 ms (only value calibrated) |
| | `BMDLimiter::SOFT` | flag |
| Voice Isolation (track built-in slot 6, or clip) | `BMDVoiceIsolationControl::DRY_MIX` | 100 · p = amount (37 → 0.3701, 82 → 0.8201, 55 → 0.55) |
| Dialogue Leveler (clip) | `UI_BAS_PRESET` | mode = 3p: 0 allow wider dynamics, 1 optimize moderate levels, 2 more lift for low levels, 3 lift soft whispery sources |
| | `UI_ADV_RIDER_ON` / `UI_BAS_LIFTER_ON` / `UI_BAS_CLEANER_ON` | flags: reduce loud dialogue / lift soft dialogue / background reduction |
| | `UI_BAS_OUTPUT_GAIN` | 6p dB (range 0–6 dB) |

A flag is ON when `p ≥ 0.5`. A lookup value that is not in the table prints `未較正(raw=…)`.

### Generated from the map

--8<-- "map_plugins.en.md"

Linear formulas (`min + (max − min) × p`) were fixed with two or more UI points and the knob scale (range) seen in the UI (`two_point`); lookups (`calib`) hold only the values that were read on the UI.

## Track Voice Isolation on/off {#track-voice-isolation-onoff}

The track built-in Voice Isolation (slot 6) has no on/off parameter. It is bit `0x10` of the record's u32 **state flags** at offset 272 from the tag:

| Bit `0x10` | Meaning |
|---|---|
| clear | enabled |
| set | disabled — the amount stays stored |

- Verified by toggling it in the UI on two tracks: only that one byte changes (the two records are 768 bytes apart), and the amount is unchanged.
- Verified with the scripting API `Timeline.SetVoiceIsolationState`: the API then reports amount 0 for a disabled track, although the stored amount stays.
- The parameter registry (marker `0x77668866`) also changes, but it is not needed to read the state.
- Unused built-in slots also carry `0x10`. For insert plugins (`2` has been seen) and the other built-in FX the flags are **not decoded**; `--all` prints them as `state_flags`.

The reader prints it as `Voice Isolation.enabled` (`ON` / `OFF`), usable in `--expect`.

## Not decoded

- Plugin bypass (insert slots).
- Track-level Dialogue Leveler settings: the track record carries no `UI_…` parameters until they are set in the UI, and they cannot be set through the API.
- Parameters of other plugins (Vocal Channel EQ bands, Dialogue Separator, Music Remixer, Ducker, third-party plugins): raw with `--all`.
