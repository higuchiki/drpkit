# Getting started

## Requirements

| Need | For |
|---|---|
| Python 3.9 or newer | everything |
| [PyYAML](https://pypi.org/project/PyYAML/) | everything (installed automatically) |
| `ffprobe` from [FFmpeg](https://ffmpeg.org/) on `PATH` | `compose` only (reads the media you hand it) |
| Python 3.14+ (built-in `compression.zstd`) **or** the `zstandard` package | reading clip effects from a `Project.db`, and timeline markers stored compressed |

Nothing else. drpkit never starts Resolve and never talks to its scripting API.

## Install

```bash
pip install git+https://github.com/higuchiki/drpkit.git
# with the optional zstd support:
pip install "drpkit[zstd] @ git+https://github.com/higuchiki/drpkit.git"
drpkit --version
```

In a checkout, `pip install .` works too. The old entry points `fairlight_reader.py`, `fairlight_writer.py` and `drp_compose.py` are thin wrappers around the same code.

## Three commands

### 1. Read a mixer

```bash
drpkit read project.drp
```

One Markdown table per mixer strip (each track column and each bus). Every row shows the converted value, a [confidence mark](fairlight-model.md#confidence-marks) and the raw stored value:

```text
## タイムライン：Fixture

### Track1（track・列0）
| 項目 | 値 | 生値 |
|---|---|---|
| fader | 0 dB² | 0 |
| proc_order | FX→DY→EQ (default) | 5 |
| eq_band1_type | HPF | 6 |
| eq_band1_freq | 70 Hz | 70 |
| eq_band1_q | 1.1※ | 26 |
...
```

Table headings and some labels are Japanese (the tool was first written for a Japanese workflow); item names, values and units are plain. Use `--json` for machine-readable output.

A disk-database project is read the same way; pick one timeline with `--timeline`:

```bash
drpkit read "/path/to/Resolve Project Library/.../Project.db" --timeline "Main"
```

### 2. Read the edit

```bash
drpkit read project.drp --edits
```

Clips (position, source In/Out, fades, fade curve point, clip volume, volume keyframes, clip FX, color), transitions and timeline markers. All positions are frames at the timeline frame rate. See [Clips & edits](clips-edits.md).

### 3. Compose a new project

```bash
drpkit compose TEMPLATE.drp OUT.drp --cuts cuts.json \
    --media 1=host.wav --media 2=guest.flac
```

The template's audio tracks are emptied and refilled from the [cut list](cut-list.md); the mixer and everything else stay byte for byte. Import the result in Resolve with *File → Import Project*, into a **project library used only for testing**.

## Safety rules

- `read` opens a `.drp` as a zip for reading and a `Project.db` with SQLite `mode=ro&immutable=1`; it never modifies the input.
- `write` and `compose` refuse an output path that already exists, build every change in memory, verify it, write a temporary file next to the output, read it back and verify again, and only then move it to the output name in one step (hard link, or rename where links are unsupported). On any error the temporary file is removed and no output exists.
- Keep a backup of the original and check the result in Resolve before relying on it. **No warranty** — see [LICENSE](https://github.com/higuchiki/drpkit/blob/main/LICENSE).

## Run the tests

```bash
python3 -m unittest discover -s tests -t . -v
```

The compose tests need `ffmpeg` / `ffprobe`. What each test covers: [Verification](verification.md#automated-tests).
