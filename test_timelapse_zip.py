#!/usr/bin/env python3
"""Test the Kiln changes in moonraker/components/timelapse.py (issue #40)
with stand-ins for Moonraker and tornado:

- "Save Frames": the zip runs in a child process (timelapse_zip.py) at
  nice 19, the event loop keeps running meanwhile, and the zip is valid,
  stored (not deflated) and has the same names and bytes as the frames.
- A frame that is gone is skipped; a zip that can't be written gives
  status "error" and clears saveisrunning.
- Render: ffmpeg runs under nice with one thread; with a system ffmpeg
  the command is also run on a few real JPEG frames.

usage: test_timelapse_zip.py [frames]   (default 300 frames of ~160 KB)
"""
import asyncio
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
COMPONENT = os.path.join(REPO, "moonraker", "components", "timelapse.py")

# tornado.ioloop: only IOLoop is imported
tornado = types.ModuleType("tornado")
ioloop_mod = types.ModuleType("tornado.ioloop")
ioloop_mod.IOLoop = type("IOLoop", (), {})
tornado.ioloop = ioloop_mod
sys.modules.setdefault("tornado", tornado)
sys.modules.setdefault("tornado.ioloop", ioloop_mod)

spec = importlib.util.spec_from_file_location("timelapse", COMPONENT)
timelapse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timelapse)

FAILED = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILED.append(what)


class KlippyApis:
    async def query_objects(self, objs):
        return {"print_stats": {"filename": "subdir/test_print.gcode"}}

    async def run_gcode(self, gcode):
        pass


def make_component(temp_dir, out_dir):
    """A Timelapse with what saveFramesZip and render use, set up the
    way __init__ sets the Kiln parts."""
    tl = object.__new__(timelapse.Timelapse)
    tl.temp_dir = os.path.join(temp_dir, "")
    tl.out_dir = os.path.join(out_dir, "")
    tl.saveisrunning = False
    tl.renderisrunning = False
    tl.byrendermacro = False
    tl.framecount = 0
    tl.lastcmdreponse = ""
    tl.lastrenderprogress = 0
    tl.klippy_apis = KlippyApis()
    tl.config = {"time_format_code": "%Y%m%d_%H%M"}
    nice = shutil.which("nice")
    ionice = shutil.which("ionice")
    tl.kiln_nice = [nice, "-n", "19"] if nice else []
    tl.kiln_ionice = [ionice, "-c", "3"] if ionice else []
    tl.kiln_zip_script = os.path.join(os.path.dirname(COMPONENT),
                                      "timelapse_zip.py")
    return tl


def zip_children():
    """(pid, nice) of running timelapse_zip.py processes."""
    found = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = f.read().split(b"\0")
            # the Python child itself (not ionice before its exec)
            if not (b"python" in os.path.basename(args[0])
                    and any(os.path.basename(a) == b"timelapse_zip.py"
                            for a in args)):
                continue
            with open(f"/proc/{pid}/stat") as f:
                stat = f.read()
        except OSError:
            continue
        # field 19 (nice) counted after the ")" that ends the comm field
        fields = stat.rsplit(")", 1)[1].split()
        found.append((int(pid), int(fields[16])))
    return found


async def run_with_ticker(coro):
    """Run coro while a 10 ms ticker measures the longest event loop
    gap; also note the niceness of the zip child."""
    gaps = [0.0]
    nices = set()
    done = asyncio.Event()

    async def ticker():
        last = time.monotonic()
        while not done.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps[0] = max(gaps[0], now - last)
            last = now
            for _, n in zip_children():
                nices.add(n)

    task = asyncio.ensure_future(ticker())
    start = time.monotonic()
    try:
        result = await coro
    finally:
        done.set()
        await task
    return result, time.monotonic() - start, gaps[0], nices


def test_save_frames(nframes, size):
    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = os.path.join(tmp, "frames")
        out_dir = os.path.join(tmp, "out")
        os.makedirs(frames_dir)
        os.makedirs(out_dir)
        for i in range(nframes):
            # JPEG-like: SOI marker and random (incompressible) data
            with open(os.path.join(frames_dir, f"frame{i + 1:06d}.jpg"),
                      "wb") as f:
                f.write(b"\xff\xd8\xff\xe0" + os.urandom(size))
        names = sorted(os.listdir(frames_dir))

        # what upstream did in the event loop, for comparison
        t0 = time.monotonic()
        with zipfile.ZipFile(os.path.join(tmp, "inline.zip"), "w") as z:
            for n in names:
                z.write(os.path.join(frames_dir, n), n)
        inline = time.monotonic() - t0
        os.remove(os.path.join(tmp, "inline.zip"))

        tl = make_component(frames_dir, out_dir)
        result, took, gap, nices = asyncio.run(
            run_with_ticker(tl.saveFramesZip()))
        mb = nframes * size / 1e6
        print(f"     {nframes} frames, {mb:.0f} MB: zip took {took:.2f} s, "
              f"longest event loop gap {gap * 1000:.0f} ms "
              f"(upstream inline zip here: {inline:.2f} s of blocked loop)")
        check(result.get("status") == "finished", f"status finished: "
              f"{result}")
        check(tl.saveisrunning is False, "saveisrunning cleared")
        check(gap < 0.25, "event loop not blocked (gap < 250 ms)")
        if nices:
            # it starts under nice -n 19 (relative), then sets 19 itself
            check(19 in nices and min(nices) > 0,
                  f"zip child ran at low priority, nice 19 (saw {nices})")
        else:
            print("     (zip child too quick to see its niceness)")
        zpath = os.path.join(out_dir, result.get("zipfile", ""))
        check(os.path.isfile(zpath), f"zip written: {result.get('zipfile')}")
        check(result.get("zipfile", "").startswith(
            "timelapse_test_print.gcode_"), "upstream zip file name")
        with zipfile.ZipFile(zpath) as z:
            check(z.testzip() is None, "zip CRCs valid")
            check(z.namelist() == names, "same names, same order")
            check(all(i.compress_type == zipfile.ZIP_STORED
                      for i in z.infolist()), "frames stored, not deflated")
            same = all(z.read(n) == open(os.path.join(frames_dir, n),
                                         "rb").read() for n in names)
            check(same, "same bytes")


def test_no_fadvise():
    # Kiln OS's MIPS kernel: posix_fadvise raises ENOSYS; the zip still works
    import errno
    zspec = importlib.util.spec_from_file_location(
        "timelapse_zip", os.path.join(os.path.dirname(COMPONENT),
                                      "timelapse_zip.py"))
    timelapse_zip = importlib.util.module_from_spec(zspec)
    zspec.loader.exec_module(timelapse_zip)
    def enosys(*a):
        raise OSError(errno.ENOSYS, "Function not implemented")
    real = getattr(timelapse_zip.os, "posix_fadvise", None)
    timelapse_zip.os.posix_fadvise = enosys
    try:
        with tempfile.TemporaryDirectory() as d:
            frames = []
            for n in range(5):
                f = os.path.join(d, "frame%06d.jpg" % n)
                with open(f, "wb") as fp:
                    fp.write(os.urandom(3000))
                frames.append(f)
            z = os.path.join(d, "out.zip")
            stored = timelapse_zip.zip_frames(z, frames, sync_bytes=4096)
            with zipfile.ZipFile(z) as zf:
                ok = stored == 5 and zf.testzip() is None
        check(ok, "posix_fadvise ENOSYS (MIPS kernel): zip still written")
    finally:
        if real is not None:
            timelapse_zip.os.posix_fadvise = real


def test_missing_and_error():
    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = os.path.join(tmp, "frames")
        out_dir = os.path.join(tmp, "out")
        os.makedirs(frames_dir)
        os.makedirs(out_dir)
        for i in range(5):
            with open(os.path.join(frames_dir, f"frame{i + 1:06d}.jpg"),
                      "wb") as f:
                f.write(os.urandom(1000))
        tl = make_component(frames_dir, out_dir)
        # a frame removed between the listing and the zip (a new print's
        # cleanup) is skipped
        files = sorted(os.path.join(frames_dir, n)
                       for n in os.listdir(frames_dir))
        os.remove(files[2])
        ok = asyncio.run(tl.kiln_zip_frames(
            os.path.join(out_dir, "x.zip"), files))
        with zipfile.ZipFile(os.path.join(out_dir, "x.zip")) as z:
            n = len(z.namelist())
        check(ok and n == 4, f"missing frame skipped ({n} of 5 stored)")

        # output directory gone: status error, no stuck saveisrunning
        tl.out_dir = os.path.join(tmp, "nonexistent", "")
        result = asyncio.run(tl.saveFramesZip())
        check(result.get("status") == "error", f"unwritable zip: status "
              f"error ({result.get('status')})")
        check(tl.saveisrunning is False, "saveisrunning cleared on error")

        # no frames: upstream's skip
        tl.temp_dir = os.path.join(tmp, "empty", "")
        os.makedirs(tl.temp_dir)
        result = asyncio.run(tl.saveFramesZip())
        check("status" not in result or result["status"] != "finished",
              "no frames: nothing zipped")


class ShellCommand:
    """Moonraker's shell_command, running the command for real when
    ffmpeg is the system one; records the commands."""
    def __init__(self, run_it):
        self.cmds = []
        self.run_it = run_it

    def build_shell_command(self, cmd, callback=None):
        self.cmds.append(cmd)
        run_it = self.run_it

        class Cmd:
            async def run(self, **kw):
                if not run_it:
                    return True
                import shlex
                p = await asyncio.create_subprocess_exec(
                    *shlex.split(cmd), stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE)
                _, err = await p.communicate()
                if p.returncode and callback:
                    callback(err[-2000:])
                return p.returncode == 0
        return Cmd()


def test_render():
    ffmpeg = shutil.which("ffmpeg")
    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = os.path.join(tmp, "frames")
        out_dir = os.path.join(tmp, "out")
        os.makedirs(frames_dir)
        os.makedirs(out_dir)
        if ffmpeg:
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=size=320x240:rate=10", "-frames:v",
                            "20", os.path.join(frames_dir, "frame%06d.jpg")],
                           check=True)
        else:
            for i in range(20):
                with open(os.path.join(frames_dir, f"frame{i + 1:06d}.jpg"),
                          "wb") as f:
                    f.write(b"\xff\xd8")
        tl = make_component(frames_dir, out_dir)
        tl.ffmpeg_binary_path = ffmpeg or "/usr/bin/ffmpeg"
        tl.ffmpeg_installed = True
        tl.config.update({
            "duplicatelastframe": 0, "variable_fps": False,
            "output_framerate": 10, "rotation": 90, "flip_x": False,
            "flip_y": False, "constant_rate_factor": 23,
            "pixelformat": "yuv420p", "extraoutputparams": "",
            "previewimage": True})
        shell = ShellCommand(run_it=bool(ffmpeg))
        tl.server = types.SimpleNamespace(
            lookup_component=lambda name: shell,
            send_event=lambda *a: None)

        async def no_webcam():
            pass
        tl.getWebcamConfig = no_webcam
        result = asyncio.run(tl.render())
        cmd = shell.cmds[0]
        print(f"     render: {cmd}")
        if tl.kiln_nice:
            check(cmd.startswith(" ".join(tl.kiln_nice) + " "),
                  "render under nice -n 19")
            check(shell.cmds[-1].startswith(" ".join(tl.kiln_nice)),
                  "preview rotation under nice -n 19")
        check(cmd.count(" -threads 1") == 2 and "-threads 2" not in cmd,
              "one decode and one x264 thread")
        if ffmpeg:
            check(result.get("status") == "success",
                  f"system ffmpeg renders with this command: "
                  f"{result.get('status')} {result.get('msg', '')[-300:]}")
            mp4 = os.path.join(out_dir, result.get("filename", "?"))
            check(os.path.getsize(mp4) > 0 if os.path.exists(mp4)
                  else False, "mp4 written")
        else:
            print("     (no system ffmpeg: command not run)")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    test_save_frames(n, 160_000)
    test_missing_and_error()
    test_no_fadvise()
    test_render()
    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)
