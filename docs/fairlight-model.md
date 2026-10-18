# Fairlight model (FLStudioModelBA)

The whole Fairlight mixer of a timeline — tracks, buses, built-in EQ and Dynamics, plugins, routing — is one binary blob: the `FLStudioModelBA` value in the `Sm2Sequence` `FieldsBlob` (see [.drp and Project.db](file-format.md)). After `qCompress` decompression it holds two kinds of data that drpkit reads: **channel settings tables** and **plugin records**.

The machine-readable source of truth for every item id and conversion is [`drpkit/fairlight_map.yaml`](https://github.com/higuchiki/drpkit/blob/main/drpkit/fairlight_map.yaml). The [item table below](#all-channel-items) is generated from it.

## Channel settings tables

A run of little-endian records:

```text
u32 1 | u32 item_id | u32 n_columns | n_columns × int32
```

- One **column** per channel. A stereo track occupies two columns with the same name; a mono track one.
- Item `0xBC` is the exception: it holds `n_columns` length-prefixed UTF-8 strings — the channel names. It is how tables are found and told apart.
- If an item id appears twice in a table, the first occurrence is used.

There are several tables, recognized by their names:

| Table | Names look like |
|---|---|
| track table | the track names |
| bus table | `Bus 1`, `Bus 2`, … (starts at item `0x1D`) |
| others | `VCA…`, `Mapping…`, `Folder…` (not read) |

How the reader finds them: it locates every `0xBC` record, walks backwards record by record to the start of its table, then parses forward until the record pattern breaks.

### The bus table's first part

The bus table is split. Its first part — fader `0x001`, mute `0x002`, pre-gain `0x019`, pan … — is stored **separately, earlier in the blob**, right after a header `u32 0, u32 7` (7 is the bus kind, the same number used in plugin ownership). The reader takes the last such run before the bus table whose column count equals the number of buses, and merges it into the bus strips.

### Strip ids and routing

| Item | Tracks | Buses |
|---|---|---|
| strip id `0x458` | 0 … n−1 (the second column of a stereo track is −1) | number of tracks + 1 |
| bus channel count `0x1B4` | — | as-is (2 = stereo) |
| output connected / output bus `0x400` / `0x40B` | flag / bus index (0 = Bus 1, −1 = none) | |

## Plugin records {#plugin-records}

Each plugin instance — insert plugins on tracks and buses, and the track built-in FX — appears as an ASCII tag `bmd:<Name>:<ID>`.

```text
offset from the tag   content
  −12                 u8 kind | u8 column | u8 0 | u8 slot
   −4                 u32 owner (2 = mixer-owned instance)
    0                 256-byte NUL-padded name field "bmd:<Name>:<ID>"
  256                 4 × int32: plugin window rectangle (all −1 until the window was opened)
  272                 u32 state flags
  ...                 parameters until the next tag
```

| Field | Values |
|---|---|
| kind | `0` = track, `7` = bus |
| column | the column of the owning strip in its table |
| slot | `0–5` = insert slots 1–6; `6–10` = track built-in FX: 6 Voice Isolation, 7 Dialogue Leveler, 8 Dialogue Separator, 9 Music Remixer, 10 Ducker |
| owner | `2` for mixer-owned instances; `0` / `1` for built-in FX. Other values are templates (for example AutoMix presets) and are ignored |
| parameter | 64-byte NUL-padded name (`Plugin::PARAM`, or a bare name such as `UI_BAS_PRESET`) followed by a little-endian float32 **normalized value 0–1** |
| state flags | track built-in Voice Isolation: bit `0x10` set = disabled, clear = enabled (the amount is kept while disabled). Unused built-in slots also carry `0x10`. Not decoded for insert plugins or the other built-in FX (`--all` prints them raw) |

The knob conversions are listed in [Plugins](plugins.md).

## Confidence marks {#confidence-marks}

Every converted value carries a mark that tells you how it was established.

| Mark | `conf` | Meaning |
|---|---|---|
| (none) | `direct` | stored value as-is or times a constant; cross-checked against known UI values |
| ² | `two_point` | linear / log formula fixed by two or more known points |
| ※ | `calib` / `law` | lookup table built from UI readings (interpolated for Dynamics). Unknown stored values print `未較正(raw=…)` |
| ? | `assumed` | single point, range assumed — reference only |
| ✗ | `raw` / `uncal` | meaning unknown or not calibrated; raw value only |

## All channel items {#all-channel-items}

Generated from `drpkit/fairlight_map.yaml` (`python tools/gen_map_docs.py`). Item ids are the same in the track and bus tables. Kinds: `scale` = raw × constant, `flag` = 0/1, `flag_inv` = inverted flag, `enum` = lookup, `affine` = a + b × raw (clamped), `law` = built-in Dynamics conversion, `raw` = not decoded.

--8<-- "map_items.en.md"

### Item families

| Family | Ids | Notes |
|---|---|---|
| EQ band k on (k = 1…6) | `0x100+k` | 1 = on |
| EQ band k filter type | `0xF8+k` | 1 low shelf, 2 bell, 3 high shelf, 4 notch, 5 low-pass (band 6 default), 6 high-pass (band 1 default) |
| EQ band k frequency | `0xF0+k` | Hz as-is |
| EQ band k gain | `0xE0+k` | ÷10 dB |
| EQ band k Q | `0xE8+k` | Q ≈ −0.615 + 0.06567 × raw |
| EQ band k range (k = 2…5) | `0x287+k` | 0 L, 1 ML, 2 MH, 3 H |
| EQ band 1 / band 6 slope | `0x4BE` / `0x4C3` | 0 = 6, 1 = 12, 2 = 18, 3 = 24 dB/oct |
| EQ band k knob (raw) | `0x333+k` | follows the frequency, ≈ 94 per natural-log unit of Hz, 0–256; probably the knob position, not used for display |

How each conversion was established: [Conversions](conversions.md).
