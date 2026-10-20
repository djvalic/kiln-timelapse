# kiln-timelapse

A [Kiln OS](https://github.com/djvalic/kiln-os) plugin for Flashforge AD5X
printers: timelapse videos of your prints, made on the printer.
[moonraker-timelapse](https://github.com/mainsail-crew/moonraker-timelapse)
takes a camera frame per layer and renders the video when the print ends,
with an ffmpeg built from source for the printer (x264, H.264 MP4).
Fluidd's **Timelapse** tab shows the settings and the videos.

Needs Kiln OS with plugin API 1.3 or newer (v0.0.6+), and a USB camera.

## Install

On the printer's touch screen: **Settings > Plugins**, then **Install**
next to **Timelapse**. Or in the console (Fluidd or HelixScreen):

    INSTALL_PLUGIN NAME=timelapse ENABLE=1

That clones it into `/data/ad5x/plugins/timelapse` and switches it on;
Klipper and Moonraker restart by themselves (Kiln OS v0.0.7 or newer).
Updates: Fluidd > Settings > Software Updates, the screen's **Update**
button, or `UPDATE_PLUGIN NAME=timelapse`. Removing it: the screen's
**Remove**, or `REMOVE_PLUGIN NAME=timelapse`.

On Kiln OS v0.0.6, by hand over SSH:

    cd /data/ad5x/plugins
    su klipper -s /bin/sh -c 'git clone https://github.com/djvalic/kiln-timelapse.git timelapse'

then `ENABLE_PLUGIN NAME=timelapse` and reboot once.

## Use

Add one line to your slicer's layer-change G-code (OrcaSlicer: Printer
settings > Machine G-code > "Before layer change" or "Timelapse G-code"):

    TIMELAPSE_TAKE_FRAME

If your G-code already calls it (zMod profiles do), nothing to change: this
plugin replaces zmod-compat's empty macro. Without the line, Fluidd's
"hyperlapse" mode takes frames at a fixed interval instead.

In Fluidd > Settings > Timelapse choose the camera, the frame rate and
whether the head parks for each frame (cleaner videos, slightly longer
prints). The video is rendered after the print (the printer's CPU takes a
few minutes for a long print; it starts from a quiet printer) and appears in
the Timelapse tab; `TIMELAPSE_RENDER` renders by hand.

Frames are kept in `printer_data/timelapse_frames` on the data partition
(the printer's `/tmp` is memory) and removed after rendering; videos in
`printer_data/timelapse`.

## ffmpeg

`ffmpeg/` holds ffmpeg 6.1.5 with x264, built from source with Kiln OS's
toolchain by `tools/build_ffmpeg.sh` (options: `tools/ffmpeg.config`, only
what timelapses need: JPEG frames in, H.264 MP4 out, rotate/flip). Kiln OS
itself has no ffmpeg. `ffmpeg/SOURCES` names the source archives; they are
attached to this repository's `ffmpeg-sources` release.

## Files

| File | What |
|---|---|
| `plugin.json`, `plugin.cfg` | Plugin metadata; includes `timelapse.cfg` |
| `timelapse.cfg` | moonraker-timelapse's Klipper macros (unchanged) |
| `moonraker/components/timelapse.py` | moonraker-timelapse's component (unchanged, see `UPSTREAM`) |
| `moonraker.conf` | `[timelapse]` paths for the AD5X, and the update entry |
| `ffmpeg/` | `ffmpeg` (wrapper), `bin/`, `lib/`, `SOURCES` |
| `tools/` | `build_ffmpeg.sh`, `ffmpeg.config` |

## Licence

GPL-3.0 (moonraker-timelapse's licence, `LICENSE`). ffmpeg and x264 in
`ffmpeg/`: GPL-2.0-or-later.
