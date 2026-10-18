# Prior work

## davinci-resolve-mcp

[samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp) (MIT) already works with the same `FLStudioModelBA` blob (`resolve-advanced/vendor/fairlight/index.js`) to read and create bus configuration and routing. Many thanks to that project for showing that this data is reachable.

If you need to build buses or change routing, use davinci-resolve-mcp.

## Where each finding comes from

| Source | Items |
|---|---|
| Prior work: davinci-resolve-mcp — **checked against our data** | that the mixer is stored in the `FLStudioModelBA` blob; bus channel count `0x1B4`; strip id `0x458` |
| Our own work — comparing the UI with exported projects (change one control, export, diff), and measuring renders | everything else: the other channel items, built-in Dynamics conversion tables, EQ, plugin knobs, the bus table's first part (fader, mute), track selection, processing order, Effects In, EQ master switch, track Voice Isolation state, edit information (clip positions, colors, fades, fade curves, keyframes, transitions, clip FX), timeline markers and media metadata |

drpkit covers a different area of the same blob than davinci-resolve-mcp — built-in Dynamics and EQ converted to UI values, fader, solo, processing order, Effects In, EQ master switch, track selection, plugin knobs and track Voice Isolation state — plus edit information and markers. These were identified independently.

## Official sources

None. Blackmagic Design does not document the `.drp` or `Project.db` formats. The scripting API (`Timeline.AddMarker`, `SetFades`, `SetVoiceIsolationState`, `GetMarkers`, `GetStartFrame`, `ExportProject`) was used only to **create test projects and check results**; drpkit itself never calls it.

“DaVinci Resolve” and “Fairlight” are trademarks of Blackmagic Design Pty. Ltd. This project is not affiliated with, endorsed by, or supported by Blackmagic Design.
