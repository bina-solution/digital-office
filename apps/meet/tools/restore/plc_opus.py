#!/usr/bin/env python3
"""Neural packet-loss concealment of zero gaps with libopus >= 1.5 (Deep PLC), per gap, timeline preserved.

usage: plc_opus.py IN.wav OUT.wav [--max-gap 0.12] [--complexity 10] [--bitrate 40000] [--lib PATH]
                   [--trim 0.003] [--ctx 0.6] [--post 0.012] [--xf 0.003] [--stats OUT.json]

For every exact-zero gap (>= 2 ms) not longer than --max-gap:
  * the already-processed signal before the gap (--ctx seconds, from a frame boundary so that the gap starts
    exactly on a 10-ms frame boundary) is Opus-encoded at 48 kHz (SILK wide-band, VoIP, FEC/DTX off) and decoded
    with decoder complexity --complexity (>= 5 enables Deep PLC in libopus 1.5+);
  * ceil(gap / 10 ms) frames are declared LOST (opus_decode_float with a NULL packet) -> concealment;
  * --post seconds after the gap are encoded/decoded too, so the decoder's own recovery transition is used;
  * the concealment is written into the gap with --xf raised-cosine crossfades into the real audio on both sides.
The codec delay (encoder look-ahead) is compensated.  Gaps longer than --max-gap are left as they are.
Edges: --trim seconds of the (faded) burst edges next to each gap are treated as lost as well.
"""
import argparse
import ctypes
import json
import math

import numpy as np
import soundfile as sf
import soxr

ap = argparse.ArgumentParser()
ap.add_argument("inp")
ap.add_argument("out")
ap.add_argument("--max-gap", type=float, default=0.12)
ap.add_argument("--complexity", type=int, default=10)
ap.add_argument("--bitrate", type=int, default=40000)
ap.add_argument("--lib", default="/root/fpgaudio/opus/install/lib/libopus.so")
ap.add_argument("--trim", type=float, default=0.003)
ap.add_argument("--ctx", type=float, default=0.6)
ap.add_argument("--post", type=float, default=0.012)
ap.add_argument("--xf", type=float, default=0.003)
ap.add_argument("--frame-ms", type=int, default=10)
ap.add_argument("--celt", action="store_true", help="use CELT mode instead of SILK (no Deep PLC)")
ap.add_argument("--stats", default=None)
ap.add_argument("--chunk", type=float, default=300.0, help="process long files in pieces of this many seconds")
a = ap.parse_args()

# ---- libopus via ctypes ---------------------------------------------------------------------------------
L = ctypes.CDLL(a.lib)
L.opus_encoder_create.restype = ctypes.c_void_p
L.opus_encoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
L.opus_decoder_create.restype = ctypes.c_void_p
L.opus_decoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
L.opus_encode_float.restype = ctypes.c_int
L.opus_encode_float.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
L.opus_decode_float.restype = ctypes.c_int
L.opus_decode_float.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int]
L.opus_encoder_ctl.restype = ctypes.c_int
L.opus_decoder_ctl.restype = ctypes.c_int
L.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
L.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
L.opus_get_version_string.restype = ctypes.c_char_p

OPUS_APPLICATION_VOIP = 2048
OPUS_SET_BITRATE = 4002
OPUS_SET_VBR = 4006
OPUS_SET_BANDWIDTH = 4008
OPUS_SET_COMPLEXITY = 4010
OPUS_SET_INBAND_FEC = 4012
OPUS_SET_DTX = 4016
OPUS_SET_SIGNAL = 4024
OPUS_GET_LOOKAHEAD = 4027
OPUS_SET_FORCE_MODE = 11002          # opus_private.h; MODE_SILK_ONLY=1000, MODE_CELT_ONLY=1002
OPUS_BANDWIDTH_WIDEBAND = 1103
OPUS_BANDWIDTH_FULLBAND = 1105
OPUS_SIGNAL_VOICE = 3001

FS = 48000
FR = FS * a.frame_ms // 1000
print("libopus:", L.opus_get_version_string().decode())


def make_codec():
    err = ctypes.c_int(0)
    enc = L.opus_encoder_create(FS, 1, OPUS_APPLICATION_VOIP, ctypes.byref(err))
    assert err.value == 0, err.value
    for req, val in [(OPUS_SET_BITRATE, a.bitrate), (OPUS_SET_VBR, 1), (OPUS_SET_COMPLEXITY, 10),
                     (OPUS_SET_INBAND_FEC, 0), (OPUS_SET_DTX, 0), (OPUS_SET_SIGNAL, OPUS_SIGNAL_VOICE),
                     (OPUS_SET_BANDWIDTH, OPUS_BANDWIDTH_FULLBAND if a.celt else OPUS_BANDWIDTH_WIDEBAND),
                     (OPUS_SET_FORCE_MODE, 1002 if a.celt else 1000)]:
        r = L.opus_encoder_ctl(ctypes.c_void_p(enc), ctypes.c_int(req), ctypes.c_int(val))
        assert r == 0, (req, val, r)
    la = ctypes.c_int(0)
    L.opus_encoder_ctl(ctypes.c_void_p(enc), ctypes.c_int(OPUS_GET_LOOKAHEAD), ctypes.byref(la))
    dec = L.opus_decoder_create(FS, 1, ctypes.byref(err))
    assert err.value == 0
    r = L.opus_decoder_ctl(ctypes.c_void_p(dec), ctypes.c_int(OPUS_SET_COMPLEXITY), ctypes.c_int(a.complexity))
    assert r == 0, r
    return enc, dec, la.value


def run_codec(x, lost):
    """x: float32 at 48 kHz, length multiple of FR; lost: bool per frame. Returns decoded (delay-compensated)."""
    enc, dec, la = make_codec()
    nfr = len(x) // FR
    buf = ctypes.create_string_buffer(4000)
    pcm = (ctypes.c_float * FR)()
    out = np.zeros(nfr * FR + FR, dtype=np.float32)
    tocs = []
    for i in range(nfr):
        fr = np.ascontiguousarray(x[i * FR:(i + 1) * FR], dtype=np.float32)
        nb = L.opus_encode_float(ctypes.c_void_p(enc), fr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), FR, buf, 4000)
        assert nb > 0, nb
        if lost[i]:
            n = L.opus_decode_float(ctypes.c_void_p(dec), None, 0, pcm, FR, 0)
        else:
            tocs.append(buf.raw[0] >> 3)
            n = L.opus_decode_float(ctypes.c_void_p(dec), buf.raw[:nb], nb, pcm, FR, 0)
        assert n == FR, n
        out[i * FR:(i + 1) * FR] = np.frombuffer(pcm, dtype=np.float32, count=FR)
    L.opus_encoder_destroy(ctypes.c_void_p(enc)); L.opus_decoder_destroy(ctypes.c_void_p(dec))
    return out[la: la + nfr * FR], tocs


# ---- signal -------------------------------------------------------------------------------------------
ms = FS // 1000
TRIM = int(a.trim * FS)
XF = int(a.xf * FS)
POST = int(a.post * FS)
CTXF = int(math.ceil(a.ctx * FS / FR))
wxf = 0.5 * (1 - np.cos(np.pi * (np.arange(XF) + 0.5) / XF)).astype(np.float32)
stats = {"gaps": 0, "concealed": 0, "skipped": 0, "complexity": a.complexity, "bitrate": a.bitrate,
         "max_gap": a.max_gap, "frame_ms": a.frame_ms, "packet_modes": {}}


def zero_runs(x, sr):
    z = np.abs(x) < 1e-7
    dz = np.diff(np.concatenate([[0], z.astype(np.int8), [0]]))
    zs, ze = np.where(dz == 1)[0], np.where(dz == -1)[0]
    keep = (ze - zs) >= 2 * (sr // 1000)
    return zs[keep], ze[keep]


def conceal(x):
    """x: float32 at 48 kHz. Returns the concealed copy (timeline unchanged)."""
    n = len(x)
    zs, ze = zero_runs(x, FS)
    out = x.copy()
    toc_hist = {}
    for gs, ge in zip(zs, ze):
        stats["gaps"] += 1
        glen = (ge - gs) / FS
        if glen > a.max_gap:
            stats["skipped"] += 1
            continue
        gs2, ge2 = gs - TRIM, ge + TRIM              # the faded edges are lost too
        if gs2 - CTXF * FR < 0 or ge2 + POST + XF + 2 * FR > n:
            stats["skipped"] += 1
            continue
        s0 = gs2 - CTXF * FR                        # frame grid: gap starts on a boundary
        nlost = int(math.ceil((ge2 - gs2) / FR))
        npost = int(math.ceil((POST + XF) / FR)) + 1
        seg_end = gs2 + nlost * FR + npost * FR
        if seg_end > n:
            stats["skipped"] += 1
            continue
        seg = out[s0:seg_end]                       # context = already-concealed signal
        lost = np.zeros(len(seg) // FR, dtype=bool)
        lost[CTXF:CTXF + nlost] = True
        dec, tocs = run_codec(seg, lost)
        for t in tocs:
            toc_hist[t] = toc_hist.get(t, 0) + 1
        # fill region in output coordinates: [gs2 - XF, ge2 + POST + XF)
        f0, f1 = gs2 - XF, ge2 + POST + XF
        fill = dec[f0 - s0: f1 - s0].copy()
        w = np.ones(len(fill), dtype=np.float32)
        w[:XF] = wxf
        w[-XF:] = wxf[::-1]
        out[f0:f1] = out[f0:f1] * (1 - w) + fill * w
        stats["concealed"] += 1
    for t, c in toc_hist.items():
        k = "SILK" if t < 12 else ("HYBRID" if t < 16 else "CELT")
        stats["packet_modes"][k] = stats["packet_modes"].get(k, 0) + c
    return out


def process_piece(x0, sr0):
    x = soxr.resample(x0, sr0, FS).astype(np.float32) if sr0 != FS else x0.copy()
    out = conceal(x)
    y = soxr.resample(out, FS, sr0).astype(np.float32) if sr0 != FS else out
    if len(y) < len(x0):
        y = np.concatenate([y, np.zeros(len(x0) - len(y), dtype=np.float32)])
    return y[: len(x0)]


# ---- file driver: whole file, or chunks split inside sound bursts (long recordings, bounded memory) ---------
info = sf.info(a.inp)
sr0, N = info.samplerate, info.frames
CHUNK, OV = int(a.chunk * sr0), int(2.0 * sr0)
with sf.SoundFile(a.out, "w", samplerate=sr0, channels=1, subtype="FLOAT") as fo:
    if N <= CHUNK + CHUNK // 2:
        x0, _ = sf.read(a.inp, dtype="float32", always_2d=True)
        y = process_piece(x0.mean(axis=1).astype(np.float32), sr0)
        np.clip(y, -0.999, 0.999, out=y)
        fo.write(y)
    else:
        # split points: nominal multiples of CHUNK moved to the middle of the nearest sound burst >= 20 ms
        pos = 0
        while pos < N:
            nominal = min(N, pos + CHUNK)
            end = nominal
            if nominal < N:
                a0 = max(pos + CHUNK // 2, nominal - 10 * sr0)
                probe, _ = sf.read(a.inp, dtype="float32", always_2d=True, start=a0, stop=min(N, nominal + 10 * sr0))
                p = probe.mean(axis=1)
                nz = np.abs(p) > 1e-6
                # bursts >= 20 ms: runs of True
                d = np.diff(np.concatenate([[0], nz.astype(np.int8), [0]]))
                bs, be = np.where(d == 1)[0], np.where(d == -1)[0]
                good = (be - bs) >= 20 * (sr0 // 1000)
                if good.any():
                    mids = (bs[good] + be[good]) // 2 + a0
                    end = int(mids[np.argmin(np.abs(mids - nominal))])
            r0, r1 = max(0, pos - OV), min(N, end + OV)
            piece, _ = sf.read(a.inp, dtype="float32", always_2d=True, start=r0, stop=r1)
            y = process_piece(piece.mean(axis=1).astype(np.float32), sr0)
            y = y[pos - r0: pos - r0 + (end - pos)]
            np.clip(y, -0.999, 0.999, out=y)
            fo.write(y)
            pos = end
print(json.dumps(stats))
if a.stats:
    json.dump(stats, open(a.stats, "w"))
