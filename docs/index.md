# drpkit

Read and edit DaVinci Resolve project files **without opening Resolve**: `.drp` exports can be read and written; the disk-database `Project.db` is **read only** (`write` and `compose` work on `.drp` files only).

`Unofficial` · `MIT License` · `Python 3.9+`

This site is the full specification: the commands, the cut list, and everything that is known about how Resolve stores the Fairlight mixer, clips, markers and media — with the evidence for each item.

## What it does

### `drpkit read`

Fairlight mixer settings (tracks, buses, built-in EQ / Dynamics, plugins) and edit information (clips, fades, keyframes, transitions, clip colors, timeline markers), converted to the values shown in the UI.

```bash
drpkit read project.drp
drpkit read project.drp --json
drpkit read project.drp --edits
drpkit read Project.db --timeline "Main"
```

### `drpkit compose`

Build a new `.drp` from a template project, your audio files and a cut list. The template's whole mixer is kept byte for byte.

```bash
drpkit compose TEMPLATE.drp OUT.drp --cuts cuts.json \
    --media 1=host.wav --media 2=guest.flac
```

### `drpkit write`

Analysis only: write raw values into the mixer tables of a copy of a `.drp`, to build conversion tables.

```bash
drpkit write IN.drp OUT.drp --set 'Track1:0x10d=51996'
```

Checked with DaVinci Resolve Studio 21.1.1. The free version is not verified. drpkit only touches files, never the Resolve application or its scripting API.

## What is supported

| Area | Read | Write / compose |
|---|---|---|
| Strip basics | fader, mute, solo, pan, routing, bus channel count, strip id | raw cells (`write`) |
| Built-in EQ / Dynamics | every band / knob converted to UI values | raw cells |
| Plugins | De-Esser, Vocal Channel, Limiter, Voice Isolation, Dialogue Leveler | kept byte for byte by `compose` |
| Clips | position, fades, color, keyframes, clip FX | position, source in/out, media, color, fades, clip volume keyframes |
| Timeline markers | frame, color (16), name, note, duration | same |
| Not decoded | track automation lanes, keyframe flags, plugin bypass, bus solo, track-level Dialogue Leveler | |

Full list with item numbers: [Fairlight model](fairlight-model.md) · open questions: [Unresolved](unresolved.md).

## Install

```bash
pip install git+https://github.com/higuchiki/drpkit.git
drpkit --version
```

`compose` needs `ffprobe` (part of FFmpeg) on `PATH`. Reading clip effects and compressed markers from a `Project.db` needs Python 3.14+ or the `zstandard` package. See [Getting started](getting-started.md).

## Safety

- `read` never modifies its input: a `.drp` is opened as a zip for reading, a `Project.db` read-only and immutable.
- `write` and `compose` never overwrite — the output path must not already exist. The result is written to a temporary file, read back and verified (`compose` compares every clip with the cut table), then moved into place in one step; on any error no output file is left.
- Import results into a separate project library used only for testing, and keep a backup of the original.

!!! warning "Unofficial project"
    Not affiliated with, endorsed by, or supported by Blackmagic Design. "DaVinci Resolve" and "Fairlight" are trademarks of Blackmagic Design Pty. Ltd. The file format was worked out by observation and may change in any Resolve release.

    Always work on a copy. `write` and `compose` output is for use in a separate, test-only project library — check the result in Resolve before relying on it. **No warranty**: the author accepts no responsibility for corrupted or lost projects. Use at your own risk — see [LICENSE](https://github.com/higuchiki/drpkit/blob/main/LICENSE).

## Prior work

[samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp) (MIT) already works with the same underlying data to read and create bus configuration and routing. Many thanks to that project for showing that this data is reachable. drpkit covers a different area — built-in Dynamics and EQ converted to UI values, fader, solo, processing order, plugin knobs and track Voice Isolation state, plus edit information and markers — identified independently. If you need to build buses or change routing, use davinci-resolve-mcp. Details: [Prior work](prior-work.md).

---

[github.com/higuchiki/drpkit](https://github.com/higuchiki/drpkit) · MIT License — © Kiyonori Higuchi
