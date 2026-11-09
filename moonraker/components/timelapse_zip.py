#!/usr/bin/env python3
# kiln-timelapse (Kiln OS change, see UPSTREAM): the "Save Frames" zip of
# moonraker-timelapse, run by timelapse.py as a child process at low
# priority, so the zip never blocks Moonraker's event loop or starves
# Klipper (Kiln OS issue #40: 725 frames, 117 MB, 15 s event loop block,
# then "Timer too close"). Not a Moonraker component (no [timelapse_zip]
# section); standard library only.
#
# usage: timelapse_zip.py ZIPFILE < frame paths, one per line
#
# - ZIP_STORED: JPEG frames don't compress, deflate would only cost CPU
#   (upstream's ZipFile(...) is stored too; this keeps it explicit).
# - nice 19 (timelapse.py starts it under nice, and ionice -c3 when the
#   system has it; it sets nice 19 itself too, in case there is no nice).
# - The zip is written to the eMMC in small synced steps and dropped from
#   the page cache, instead of ~100 MB of dirty pages that the kernel
#   then writes back at once (with 512 MB of RAM, that throttles every
#   writer and evicts Klipper's pages).
import os
import sys
import zipfile

SYNC_BYTES = 4 << 20


def _flush(fp):
    fp.flush()
    os.fsync(fp.fileno())
    if hasattr(os, "posix_fadvise"):
        os.posix_fadvise(fp.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)


def zip_frames(zip_path, frames, sync_bytes=SYNC_BYTES):
    """Store frames in zip_path under their base names (as upstream).
    Returns the number of frames stored; missing frames are skipped."""
    stored = 0
    synced = 0
    try:
        with open(zip_path, "wb") as fp:
            with zipfile.ZipFile(fp, "w", zipfile.ZIP_STORED) as zf:
                for frame in frames:
                    try:
                        zf.write(frame, os.path.basename(frame))
                    except FileNotFoundError:
                        sys.stderr.write(f"timelapse_zip: {frame} is "
                                         "gone, skipped\n")
                        continue
                    stored += 1
                    pos = fp.tell()
                    if pos - synced >= sync_bytes:
                        _flush(fp)
                        synced = pos
            _flush(fp)
    except BaseException:
        # no half-written zip in the Timelapse tab
        try:
            os.remove(zip_path)
        except OSError:
            pass
        raise
    return stored


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: timelapse_zip.py ZIPFILE < frame list\n")
        return 2
    try:
        os.setpriority(os.PRIO_PROCESS, 0, 19)
    except OSError:
        pass
    frames = [line for line in sys.stdin.read().splitlines() if line]
    stored = zip_frames(argv[1], frames)
    print(f"stored {stored} of {len(frames)} frames")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
