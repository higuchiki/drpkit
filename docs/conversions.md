# Conversions

How stored values become the numbers shown in the Fairlight UI, and how each conversion was established. Item ids: [Fairlight model](fairlight-model.md#all-channel-items).

## Fader, gain, pan, routing

| Control | Item | Conversion | Evidence |
|---|---|---|---|
| fader | `0x001` | ÷10 dB, post-dynamics | track: −60 / −200 rendered −6.0 / −20.0 dB. Bus (first part of the bus table): −60 / −200 / +60 rendered exactly −6.0 / −20.0 / +6.0 dB |
| pre-dynamics gain | `0x019` | ÷10 dB, before Dynamics | with the limiter on, −60 lowered the output by only 0.4 dB, so it acts before the dynamics (UI name not confirmed) |
| mute | `0x002` | 1 = muted | bus: 1 rendered silence |
| solo | `0x011` | 1 = solo | |
| pan bypass | `0x00D` | 1 = pan **off**; reported inverted as `pan_on` | |
| pan L/R | `0x004` | ÷10 = %, −100 … +100 | |
| Effects In | `0x01D` | 1 = on | toggled in the UI: 0 → 1 |
| EQ master switch | `0x0DF` | 1 = on | default 1; switching it off in the UI gave 0 |
| processing order | `0x0DE` | 0 EQ→DY→FX, 1 EQ→FX→DY, 2 DY→EQ→FX, 3 DY→FX→EQ, 4 FX→EQ→DY, 5 FX→DY→EQ (default) | all six orders selected in the UI one by one |
| track selected | `0x0AA` | 1 = the track header is selected (UI state only, no effect on sound) | selecting A1 then A2 changed `[1,0,0,0]` → `[0,1,0,0]` |
| output connected / bus | `0x400` / `0x40B` | flag / bus index (0 = Bus 1, −1 = none) | |

## Built-in EQ

Six bands per strip. Band k uses the ids below (k = 1 … 6).

| Control | Item | Conversion |
|---|---|---|
| band on | `0x100+k` | 1 = on |
| filter type | `0xF8+k` | 1 low shelf, 2 bell, 3 high shelf, 4 notch, 5 low-pass (band 6 default), 6 high-pass (band 1 default) |
| frequency | `0xF0+k` | Hz as-is |
| gain | `0xE0+k` | ÷10 dB |
| Q | `0xE8+k` | **Q = −0.615 + 0.06567 × raw**, clamped to 0.3 … 10.3, one decimal |
| range (bands 2–5) | `0x287+k` | 0 L, 1 ML, 2 MH, 3 H. Factory defaults 0, 1, 2, 3 for bands 2–5 |
| slope (bands 1 and 6) | `0x4BE` / `0x4C3` | 0 = 6, 1 = 12, 2 = 18, 3 = 24 dB/oct |
| knob (raw) | `0x333+k` | follows the frequency (≈ 94 per natural-log unit of Hz, 0–256); probably the knob position; not used for display |

The Q formula is fitted to 6 UI points between 0.8 and 5.0; all six match to the displayed digit. The UI range is 0.3–10.3; the ends were not checked. An older mapping that read the band 1 type from `0x0DE` was wrong (that item is the processing order).

## Built-in Dynamics {#built-in-dynamics}

### Linear knobs

| Control | Item | Conversion |
|---|---|---|
| make-up | `0x109` | ÷10 dB |
| compressor on / threshold / knee / mix | `0x10C` / `0x10E` / `0x10F` / `0x117` | flag / ÷10 dB / as-is / as-is |
| expander on / threshold / range | `0x114` / `0x116` / `0x115` | flag / ÷10 dB (single point, `assumed`) / ×0.6 dB |
| expander mode | `0x11B` | 0 = expander; any non-zero value shows the gate |
| limiter on / threshold | `0x11D` / `0x11E` | flag / ÷10 dB |

### Time and ratio knobs: two encodings

Ratio, attack, hold and release of the compressor, expander and limiter are not linear. A stored value `r` uses one of two encodings, and **both can appear in the same project**.

| Encoding | Condition | UI value |
|---|---|---|
| legacy (templates, factory defaults) | `r ≤ 100` | `r` is the knob position in %; log-interpolate the `legacy` table |
| current (values set in Resolve 21) | `r ≥ 5000` | `M = (r + 5) // 100` (knob position 0 … 1000), `d = r − 100·M` (−5 … 94); **UI = law[M] + d × fine** |
| out of range | `101 ≤ r ≤ 4999` | the UI field is blank (`画面空欄(raw=…)`) |

- `fine` is 1 ms for time knobs and 0 for ratio.
- Values typed into the UI have so far always been stored with `d = −4`. Example: attack 4.0 ms is stored as 40496 → M = 405 (law 8.0 ms), d = −4 → 8.0 − 4 = **4.0 ms**.
- Example: ratio stored as 51996 → M = 520, d = −4 (fine 0) → between law[500] = 2.9 and law[550] = 3.2 → **3.0:1**.
- Example (legacy): release stored as 20 → legacy table → **93 ms**.

| Knob | Item | Law | Notes |
|---|---|---|---|
| compressor ratio | `0x10D` | `ratio` | UI `x:1`, max 20 |
| compressor attack / hold / release | `0x110` / `0x111` / `0x112` | `attack` / `hold` / `release` | attack minimum 0.70 ms |
| expander ratio | `0x253` | `exp_ratio` | UI `1:x`, max 3.0 |
| expander attack / hold / release | `0x118` / `0x119` / `0x11A` | `exp_attack` / `hold` / `release` | attack minimum 0.50 ms |
| limiter attack / hold / release | `0x11F` / `0x120` / `0x121` | `lim_attack` / `hold` / `release` | attack minimum 0.70 ms |

Compressor and expander attack share one curve (only the minimum differs); hold is shared by all three processors; release is shared, and equals hold for M ≥ 200. Hold and release are capped at 4000 ms.

### Interpolation and display

- `law[M]` is defined every 50 steps plus a few measured points. Between two table points the value is interpolated **logarithmically** when both ends are positive, otherwise linearly. Outside the table the end value is used (no extrapolation).
- The attack minimum (`floor`) and the law maximum (`max`) are applied after the conversion.
- Display: below 1 two decimals, below 9.95 one decimal, otherwise an integer — as the Fairlight UI shows it. Ratio is printed `x:1`, expander ratio `1:x`.

### Tables (current encoding)

Generated from `dyn_laws` in `drpkit/fairlight_map.yaml`. Units: ms for time knobs, ratio for `ratio` / `exp_ratio`.

--8<-- "map_laws.en.md"

### Tables (legacy encoding, r ≤ 100)

--8<-- "map_legacy.en.md"

### How the tables were made, and how accurate they are

1. Write chosen stored values into a copy of a project with `drpkit write`.
2. Import the copy into Resolve 21.1.1 and read the Dynamics window.
3. 23 projects × 10 knobs, plus individual points; the readings are in `tests/data/dyn_law_sweep_readings.txt`, the plan in `tests/data/dyn_law_sweep_plan.json`, and `tests/test_dyn_law.py` checks every one.

Blind check on 20 points that were **not** used to build the tables: 11 exact, 5 off by one in the last displayed digit, 3 off by 0.2–0.8 %, 1 outlier (hold at M = 165; that point was then added to the table). In general the conversion is within ±1 % (the last displayed digit); hold and release around knob position 100–250 can be off by more.

The expander ratio (`0x253`) points — legacy 0 → 1.1, 10 → 1.3, 25 → 1.6, 40 → 1.8, 55 → 2.1, 75 → 2.5, 90 → 2.8, 100 → 3.0; current M = 152 → 1.3, 263 → 1.5, 400 → 1.7, 600 → 2.1, 800 → 2.5, 1000 → 2.9 — were all read on the UI (8 after writing values with the writer). They are all in the table, so the test is not an independent check for this knob.

## Plugins and clips

Plugin knob formulas (normalized 0–1 → UI): [Plugins](plugins.md). Clip volume, fades, fade curves and keyframes: [Clips & edits](clips-edits.md).
