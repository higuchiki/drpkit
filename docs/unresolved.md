# Unresolved

What is known to exist but not decoded, or decoded only partly. Contributions with evidence (an export before and after one UI change) are welcome.

## Not decoded

| Item | What is known |
|---|---|
| Track automation | fader and plugin automation lanes of tracks are not read |
| Keyframe flags | every keyframe made in the UI stores `0x000C0000`; probably the interpolation type. `compose` writes the same value |
| Track-level Dialogue Leveler | not settable through the API; the track record carries no `UI_…` parameters until set in the UI |
| Plugin bypass | where an insert plugin's bypass is stored is not known |
| Plugin state flags | decoded only for track built-in Voice Isolation (bit `0x10`). Insert plugins (`2` has been seen) and the other built-in FX: raw with `--all` |
| Bus solo, bus pan | items exist in the first part of the bus table but are not verified |
| `0x0B9` | non-zero on exactly one track per timeline (1, 2 = channel within that track). It is **not** the track selection (`0x0AA`). Printed raw as `unknown_0b9` |
| `0x13B` | meaning unknown; printed raw as `unknown_13b` |
| `0x008` / `0x009` | possibly pan related (writing −200 changed the level by about +1.5 dB) |
| `0x11B` non-zero values | 0 = expander; any non-zero value shows the gate. The meaning of the individual values is not known |
| EQ knob `0x333+k` | follows the frequency; probably the knob position; not used |
| Fade curve shape | the curve passes through the stored point; for a point at 50 % it is the straight fade's dB curve times a constant. For other positions the shape between the ends and the point is not modelled |
| Media `Clip` fields 15, 16 | kept as they are |

## Partly calibrated

| Item | State |
|---|---|
| Expander threshold `0x116` | ÷10 dB from a single point (`assumed`) |
| Expander ratio `0x253` | all 14 measured points are in the table; no independent check |
| Limiter plugin release | one value (0.8829 = 190.55 ms) |
| De-Esser reaction | one value (0.5 = medium) |
| EQ Q | fitted on 0.8–5.0; the ends of the UI range (0.3, 10.3) not checked |
| Dynamics hold / release | knob position 100–250 can be off by more than ±1 % |

## Solved (kept for reference)

- **Fade curve**: params 99 / 100, a big-endian `(position %, level in 0.1 dB)` point. See [Fade curves](clips-edits.md#fade-curves).
- **Track Voice Isolation on/off**: bit `0x10` of the plugin record's state flags. See [Plugins](plugins.md#track-voice-isolation-onoff).
- **EQ bands**: see [Conversions](conversions.md). The old `eq_band1_type` → `0x0DE` mapping was wrong (that item is the processing order) and has been removed.

## Not supported by `compose`

Refused rather than guessed: overlapping clips, transitions other than a centered Cross Fade 0 dB, curved fades, several audio streams per file, the same media on several tracks, seconds or sub-frame positions, non-default channel mappings when the channel count changes, media other than the [supported formats](media.md#supported-formats), and items other than audio clips and transitions on the template's audio tracks.

Also note: FCPXML `fadeIn` / `fadeOut` are ignored by Resolve on import, so fades cannot be brought in that way.
