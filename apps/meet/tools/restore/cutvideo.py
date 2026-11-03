#!/usr/bin/env python3
"""Cut the original video to the restored audio's timeline (restore.py --mode cut --map).
usage: cutvideo.py SRC.mp4 MAP.json AUDIO.m4a OUT.mp4
Every output frame k (30 fps) shows the source frame at the source time the map gives for k/30;
a pause the audio kept (silence inserted between two kept stretches) freezes the last frame.
The source is decoded once, sequentially, through a pipe; the output is x264 + the given audio."""
import json
import subprocess
import sys

import numpy as np

src, mp, audio, out = sys.argv[1:5]
FPS = 30
W, H = 1280, 720
FRAME = W * H * 3 // 2
m = json.load(open(mp))
segs = m["segments"]                      # [out_start_s, src_start_s, len_s], in order
# duration of the output = end of the last segment
out_dur = segs[-1][0] + segs[-1][2]
n_out = int(round(out_dur * FPS))
# output time -> source time (vectorised): for each output frame, find its segment
starts = np.array([s[0] for s in segs])
src0 = np.array([s[1] for s in segs]) + float(m.get("offset_s") or 0)
lens = np.array([s[2] for s in segs])
t_out = (np.arange(n_out) + 0.5) / FPS
idx = np.searchsorted(starts, t_out, side="right") - 1
idx = np.clip(idx, 0, len(segs) - 1)
within = t_out - starts[idx]
# inside the segment: its source time; in a pause after it: freeze at the segment's last source time
t_src = src0[idx] + np.minimum(within, lens[idx] - 1e-3)
f_src = np.floor(t_src * FPS).astype(np.int64)
f_src = np.maximum.accumulate(f_src)       # never go backwards (the decoder is sequential)
print(f"output frames {n_out} ({out_dur:.1f}s), source frames needed up to {f_src[-1]}", flush=True)

dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-an", "-f", "rawvideo", "-pix_fmt", "yuv420p",
                        "-s", f"{W}x{H}", "-r", str(FPS), "-"], stdout=subprocess.PIPE, bufsize=FRAME * 4)
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{W}x{H}",
                        "-r", str(FPS), "-i", "-", "-i", audio, "-map", "0:v", "-map", "1:a",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-g", "60",
                        "-c:a", "copy", "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
cur_i = -1
cur = None
written = 0
for k in range(n_out):
    want = int(f_src[k])
    while cur_i < want:
        buf = dec.stdout.read(FRAME)
        if len(buf) < FRAME:
            break                      # source video ended early: keep showing its last frame
        cur = buf
        cur_i += 1
    if cur is None:
        continue
    enc.stdin.write(cur)
    written += 1
enc.stdin.close()
dec.stdout.close()
dec.wait()
enc.wait()
print(f"wrote {written} frames -> {out}", flush=True)
