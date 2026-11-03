#!/usr/bin/env python3
# Rebuild a Jibri mp4 whose ffmpeg was killed before it wrote its moov (no index): MEET-48, fireplace
# 2026-11-01 — the server froze on memory, Jibri's graceful stop timed out, ffmpeg got SIGKILL (137),
# and the file kept its media (mdat) and no index, so no player opened it and no sound was taken.
# issues/meet-a-frozen-server-killed-the-recorder-s-ffmpeg-and-left-an-mp4-with-no-index.yaml
#
# Needs only python3 and ffmpeg — what the recorder's image has (jibri/finalize.sh runs it there).
#
# The mdat holds contiguous packets: H.264 samples (4-byte length + one NAL, 0x41/0x65; the first
# carries an SEI 0x06 before its IDR) and runs of 1-3 raw AAC-LC frames (first byte 0x21, or 0xde for
# the encoder's fill element). Video samples are found by their length + header, chained (what follows
# one must begin sound, video or the end, two samples ahead); the bytes between two video samples are
# one run of sound. The samples go into an FLV — which carries exactly these two formats, the H.264 one
# with its avcC and the AAC one with its config — and ffmpeg makes the mp4 from it: the video copied,
# the sound decoded and encoded again. Each run is one packet; libavcodec keeps the unconsumed rest of
# an audio packet and decodes it as the next frame, so no AAC frame boundary has to be known.
#
# The two configs (avcC, AAC) come from REFERENCE, a healthy recording of the same recorder; without
# one, from the newest healthy .mp4 beside the broken one (the recordings folder, two levels up).
#
# Proven: a healthy recording with its moov cut off (fpg106 2026-10-28 19-16-43) → 882 video samples
# and 2,527 sound frames, its own index's numbers; fpg107 (MEET-48) → 3,998 + 266.5 s of sound, 0 errors.
#
# usage: rebuild_moov.py BROKEN.mp4 OUT.mp4 [REFERENCE.mp4]
#   exit 0 = OUT written from the whole file; 3 = written, but a part could not be read (said on stderr);
#   2 = nothing written (no mdat, no reference, ffmpeg failed).
import glob
import mmap
import os
import struct
import subprocess
import sys

AUD = (0x21, 0xde)
# Two sets of limits. The strict ones (a NAL ≤ 400 KB, the next video sample within 4 KB: 1-3 AAC
# frames) find every sample of a healthy stretch and almost no false one; the wide ones (an IDR of a
# detailed full-HD screen share is far over 400 KB; ffmpeg's interleaver writes sound alone once video
# lags past max_interleave_delta, 10 s ≈ 160 KB of AAC — what a frozen server produces) are tried only
# where the strict ones find nothing: used everywhere, they let random bytes chain (measured on fpg107:
# 3,862 video samples and a decode error instead of 3,998 and none).
STRICT = (400_000, 4000)
WIDE = (8 << 20, 400_000)


def say(msg):
    print(f"rebuild_moov: {msg}", file=sys.stderr, flush=True)


def boxes(d, start=0, end=None):
    """(type, payload start, box end) of the boxes in d[start:end]."""
    p, end = start, len(d) if end is None else end
    while p + 8 <= end:
        size, typ = struct.unpack(">I4s", d[p:p + 8])
        hdr = 8
        if size == 1:
            size, hdr = struct.unpack(">Q", d[p + 8:p + 16])[0], 16
        elif size == 0:
            size = end - p
        if size < hdr:
            return
        yield typ, p + hdr, min(p + size, end)
        p += size


def configs(path):
    """(avcC, AAC AudioSpecificConfig) from a healthy mp4's moov, or None."""
    # only the moov is read: a reference may be an hour of video, on a machine short of memory
    m = None
    try:
        with open(path, "rb") as f:
            total = os.fstat(f.fileno()).st_size
            p = 0
            while p + 8 <= total:
                f.seek(p)
                size, typ = struct.unpack(">I4s", f.read(8))
                hdr = 8
                if size == 1:
                    size, hdr = struct.unpack(">Q", f.read(8))[0], 16
                elif size == 0:
                    size = total - p
                if size < hdr:
                    return None
                if typ == b"moov":
                    m = f.read(min(size - hdr, 64 << 20))
                    break
                p += size
    except (OSError, struct.error):
        return None
    if not m:
        return None
    i = m.find(b"avcC")
    j = m.find(b"esds")
    if i < 4 or j < 4:
        return None
    avcc = m[i + 4:i - 4 + struct.unpack(">I", m[i - 4:i])[0]]
    esds = m[j + 8:j - 4 + struct.unpack(">I", m[j - 4:j])[0]]   # after version+flags
    # the descriptors: 03 ES → 04 DecoderConfig → 05 DecoderSpecificInfo (the ASC); lengths are 1-4 bytes
    k = 0
    while k < len(esds):
        tag = esds[k]
        k += 1
        n = 0
        for _ in range(4):
            b = esds[k]
            k += 1
            n = (n << 7) | (b & 0x7f)
            if not b & 0x80:
                break
        if tag == 0x03:
            flags = esds[k + 2]
            k += 3 + (2 if flags & 0x80 else 0)
            k += (esds[k] + 1 if flags & 0x40 else 0) + (2 if flags & 0x20 else 0)
        elif tag == 0x04:
            k += 13
        elif tag == 0x05:
            return avcc, esds[k:k + n]
        else:
            k += n
    return None


def reference_for(broken):
    """The newest healthy recording beside the broken one."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(broken)))

    def mtime(f):
        try:
            return os.path.getmtime(f)
        except OSError:
            return 0

    for f in sorted(glob.glob(os.path.join(root, "*", "*.mp4")), key=mtime, reverse=True):
        try:
            if os.path.abspath(f) != os.path.abspath(broken) and configs(f):
                return f
        except (IndexError, ValueError, OSError):
            continue                       # one odd file is skipped, not the search
    return None


def parse(d):
    """The samples of the mdat: [('v'|'a', start, end)], how many were found with the wide limits,
    and where reading stopped (None = the end, or only a last partial sample left)."""
    mdat = next(((s, e) for t, s, e in boxes(d) if t == b"mdat"), None)
    if mdat is None:
        return None, 0, None
    p, end = mdat                        # a killed ffmpeg leaves the mdat's size 0: to the end of the file
    d = memoryview(d)[:end]
    lim = {"nal": STRICT[0], "win": STRICT[1]}

    def one_video(q):
        e = q
        while True:
            if e + 5 > len(d):
                return None
            n = struct.unpack(">I", d[e:e + 4])[0]
            if not 2 <= n <= lim["nal"] or e + 4 + n > len(d):
                return None
            h = d[e + 4]
            e += 4 + n
            if h == 0x06:           # SEI: its slice follows inside the same sample
                continue
            return e if h in (0x41, 0x65) else None

    def next_video(q0, depth):
        for q in range(q0 + 6, min(len(d), q0 + lim["win"])):    # one AAC frame is >= 6 bytes
            if d[q] == 0 and video_at(q, depth):
                return q
        return None

    def video_at(q, depth=2):
        e = one_video(q)
        if e is None:
            return None
        if e == len(d) or depth == 0:
            return e
        if one_video(e):                       # video straight after video (no sound between)
            return e if video_at(e, depth - 1) else None
        if d[e] not in AUD:
            return None
        if len(d) - e < 4000:                  # the tail: nothing left to confirm against
            return e
        return e if next_video(e, depth - 1) is not None else None

    samples, widened, stopped = [], 0, None
    while p < len(d):
        e = video_at(p)
        if e:
            samples.append(("v", p, e))
            p = e
            continue
        q = next_video(p, 2)
        if q is None:                       # a long sound-only stretch or a huge IDR: look wider, here only
            lim["nal"], lim["win"] = WIDE
            e = video_at(p)
            q = None if e else next_video(p, 2)
            lim["nal"], lim["win"] = STRICT
            if e:
                samples.append(("v", p, e))
                p, widened = e, widened + 1
                continue
            widened += q is not None
        if q is None:
            stopped = p
            break
        samples.append(("a", p, q))
        p = q
    if stopped is not None and len(d) - stopped <= 64 * 1024:
        stopped = None                     # a last partial sample: ffmpeg was killed in the middle of it
    d.release()                            # the closures above hold it in a cycle: the mmap must close
    return samples, widened, stopped


def has_idr(d, s, e):
    while s + 5 <= e:
        if d[s + 4] & 0x1f == 5:
            return True
        s += 4 + struct.unpack(">I", d[s:s + 4])[0]
    return False


def tag(kind, ms, body):
    """One FLV tag (8 audio, 9 video) and the size of the tag before the next."""
    head = struct.pack(">B", kind) + len(body).to_bytes(3, "big") + (ms & 0xffffff).to_bytes(3, "big") \
        + bytes([(ms >> 24) & 0xff]) + b"\0\0\0"
    return head + body + struct.pack(">I", 11 + len(body))


def flv(fh, d, samples, avcc, asc, fps):
    """Written tag by tag: nothing but one sample is held twice (the machine may be short of memory)."""
    fh.write(b"FLV\x01\x05\x00\x00\x00\x09" + struct.pack(">I", 0))
    fh.write(tag(9, 0, b"\x17\x00\x00\x00\x00" + avcc))         # AVC sequence header
    fh.write(tag(8, 0, b"\xaf\x00" + asc))                       # AAC sequence header
    i = 0
    for kind, s, e in samples:
        ms = int(round(i * 1000 / fps))
        if kind == "v":
            frame = 0x17 if has_idr(d, s, e) else 0x27
            fh.write(tag(9, ms, bytes([frame, 1, 0, 0, 0]) + d[s:e]))
            i += 1
        else:
            fh.write(tag(8, ms, b"\xaf\x01" + d[s:e]))


def main(argv):
    if len(argv) < 2:
        say("usage: rebuild_moov.py BROKEN.mp4 OUT.mp4 [REFERENCE.mp4]")
        return 2
    broken, out = argv[0], argv[1]
    ref = argv[2] if len(argv) > 2 else reference_for(broken)
    cfg = configs(ref) if ref else None
    if not cfg:
        say(f"no healthy recording to take the video and sound configuration from (reference: {ref})")
        return 2
    fps = float(os.environ.get("MEET_RECORDING_FRAMERATE") or os.environ.get("JIBRI_RECORDING_FRAMERATE") or 15)
    # a file WITH an index is never rebuilt: finalize.sh asks when ffprobe fails, and ffprobe can fail for
    # a reason of its own (killed under the very memory pressure that killed the recorder)
    if configs(broken):
        say(f"{broken} has its index (moov): nothing to rebuild")
        return 2
    src = open(broken, "rb")
    d = mmap.mmap(src.fileno(), 0, access=mmap.ACCESS_READ)
    samples, widened, stopped = parse(d)
    if not samples:
        say("no mdat, or nothing in it that reads as video and sound")
        return 2
    nv = sum(1 for k in samples if k[0] == "v")
    say(f"{broken}: {nv} video samples ({nv / fps:.1f} s at {fps:g} fps), {len(samples) - nv} sound runs, "
        f"{widened} found with the wide limits; reference {ref}")
    tmp = out + ".flv"
    size = len(d)
    try:
        with open(tmp, "wb") as fh:
            flv(fh, d, samples, *cfg, fps)
        d.close()
        src.close()
        # the sound's timestamps are the samples' own count (asetpts): each run's place between two video
        # frames is only approximate, and the decoded sound is continuous as it was recorded
        run = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", tmp, "-map", "0:v", "-map", "0:a",
                              "-c:v", "copy", "-af", "asetpts=N/SR/TB", "-c:a", "aac", "-b:a", "128k",
                              "-movflags", "+faststart", "-f", "mp4", out + ".part"],
                             capture_output=True, text=True)
    finally:
        try:
            os.unlink(tmp)                 # never left beside the recording, whatever failed
        except OSError:
            pass
    errors = [ln for ln in run.stderr.splitlines() if ln.strip()]
    if run.returncode != 0:
        say(f"ffmpeg failed ({run.returncode}): {' | '.join(errors[-3:])}")
        try:
            os.unlink(out + ".part")
        except OSError:
            pass
        return 2
    os.replace(out + ".part", out)
    say(f"wrote {out}" + (f"; ffmpeg said {len(errors)} line(s), the last: {errors[-1]}" if errors else ""))
    if stopped is not None:
        say(f"INCOMPLETE: {size - stopped} bytes from {stopped} could not be read")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
