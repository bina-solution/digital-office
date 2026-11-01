"""probe — what is INSIDE the file, and can this browser play it as it is?

The single most important fact about this library: Telegram's channels publish whatever they like, and
"it is an mp4" says almost nothing. A `.mkv` cannot be opened by any browser at all; an mp4 whose audio
is AC3/E-AC3 (very common in film releases) plays silently in Chrome; a 10-bit HEVC file plays on a
Mac and not on a Linux desktop. Playing the bytes as Telegram stores them therefore produces the worst
possible experience — a black rectangle with no error — which is exactly the failure this module
exists to prevent.

So: ask ffprobe what the file is (over the app's own range-capable URL, so ffprobe reads a few hundred
KB instead of the whole film), cache the answer, and derive one of three verdicts:

  * `direct`      the browser can play these exact bytes → serve them as they are. Zero CPU, instant
                  start, and seeking is plain HTTP Range (the best experience there is).
  * `remux`       the CONTAINER or the AUDIO is the problem, the video stream is fine → copy the video
                  and repackage into fragmented MP4, transcoding only the audio when it must. Costs a
                  few percent of one core, runs at many times realtime.
  * `unsupported` the VIDEO codec itself is one no browser decodes → say so, in Hebrew, with the codec
                  named. Transcoding 1080p on the office's 4 ARM cores would not keep up with
                  playback, and quietly attempting it is how a "smooth" player becomes a slideshow.

`probe_json` is cached on the movie row: probing costs a couple of MB of download and the answer for a
given message never changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

log = logging.getLogger("telegram-tv.probe")

FFPROBE = os.environ.get("TV_FFPROBE", "ffprobe")
TIMEOUT = float(os.environ.get("TV_PROBE_TIMEOUT", "90"))

#: Video codecs every browser of 2024+ decodes in an MP4/WebM container.
PLAYABLE_VIDEO = {"h264", "av1", "vp8", "vp9"}
#: Codecs a browser only decodes with help: HEVC needs the OS/platform decoder (Safari always; Chrome
#: on macOS with hardware support; rarely on Linux). Tried, but reported as risky so the player can
#: offer the alternative instead of showing a black screen.
CONDITIONAL_VIDEO = {"hevc", "h265"}
PLAYABLE_AUDIO = {"aac", "mp3", "opus", "vorbis", "flac"}
#: Containers a browser opens directly. Matroska/AVI/MPEG-TS are NOT among them, however modern the
#: codecs inside are.
DIRECT_CONTAINERS = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "webm", "ogg"}

CODEC_TAG = {"h264": "avc1", "hevc": "hvc1", "h265": "hvc1", "av1": "av01", "vp9": "vp09",
             "vp8": "vp8", "aac": "mp4a.40.2", "mp3": "mp4a.69", "opus": "opus", "ac3": "ac-3",
             "eac3": "ec-3", "dts": "dtsc", "flac": "flac", "vorbis": "vorbis"}


async def ffprobe(url: str) -> dict:
    """ffprobe over HTTP. `-analyzeduration`/`-probesize` are bounded so probing a 4 GB film reads a
    few hundred KB from the front, not the whole file — the app's own endpoint answers range requests,
    so ffprobe can still seek to the index when a format keeps it at the end."""
    cmd = [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
           "-analyzeduration", "10M", "-probesize", "10M", url]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("ffprobe לא סיים בפרק הזמן שהוקצב")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe נכשל: {(err or b'').decode('utf-8', 'replace')[:300]}")
    return json.loads(out.decode("utf-8", "replace") or "{}")


def summarize(info: dict) -> dict:
    """ffprobe's JSON → the handful of facts the player needs."""
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = info.get("format") or {}
    containers = (fmt.get("format_name") or "").split(",")
    vcodec = (video or {}).get("codec_name") or ""
    acodec = (audio or {}).get("codec_name") or ""
    return {
        "container": containers[0] if containers else "",
        "containers": containers,
        "video": vcodec,
        "audio": acodec,
        "width": int((video or {}).get("width") or 0),
        "height": int((video or {}).get("height") or 0),
        "pix_fmt": (video or {}).get("pix_fmt") or "",
        "profile": (video or {}).get("profile") or "",
        "audio_channels": int((audio or {}).get("channels") or 0),
        "duration": float(fmt.get("duration") or (video or {}).get("duration") or 0) or 0,
        "bit_rate": int(fmt.get("bit_rate") or 0) or 0,
        "has_audio": audio is not None,
    }


def codecs_string(p: dict) -> str:
    """The RFC 6381 string a browser is asked about with canPlayType(). It is the ONLY honest way to
    find out whether the client can decode the file: the answer depends on the OS and the GPU, not on
    the codec's name."""
    v = CODEC_TAG.get(p.get("video") or "", "")
    a = CODEC_TAG.get(p.get("audio") or "", "")
    if not v:
        return ""
    return f'video/mp4; codecs="{v}{("," + a) if a else ""}"'


def policy(p: dict) -> dict:
    """(mode, why) — the verdict. Read the docstring above for what each mode means."""
    if not p or not p.get("video"):
        return {"mode": "unsupported", "reason": "לא נמצא זרם וידאו בקובץ"}
    v, a = p.get("video"), p.get("audio") or ""
    container_ok = any(c in DIRECT_CONTAINERS for c in (p.get("containers") or []))
    if v in PLAYABLE_VIDEO and (not a or a in PLAYABLE_AUDIO) and container_ok:
        return {"mode": "direct", "reason": "", "audio_copy": True}
    if v in PLAYABLE_VIDEO or v in CONDITIONAL_VIDEO:
        why = []
        if not container_ok:
            why.append(f"המיכל {p.get('container') or '?'} אינו נתמך בדפדפן")
        if a and a not in PLAYABLE_AUDIO:
            why.append(f"הפס קול {a.upper()} אינו נתמך")
        if v in CONDITIONAL_VIDEO:
            why.append("וידאו HEVC — תלוי בחומרה של המחשב")
        return {"mode": "remux", "reason": " · ".join(why),
                "audio_copy": bool(a) and a in PLAYABLE_AUDIO,
                "video_copy": True, "risky_video": v in CONDITIONAL_VIDEO}
    return {"mode": "unsupported",
            "reason": f"קודק הווידאו {v.upper()} אינו נתמך בדפדפן ואין מספיק מעבד להמיר אותו בזמן אמת"}


async def probe(movie: dict, raw_url: str, store=None) -> dict:
    """Cached probe. `store` is optional so the function stays usable from a shell one-liner."""
    if store is not None:
        cached = store.get_probe(movie["id"])
        if cached:
            return cached
    info = summarize(await ffprobe(raw_url))
    info["policy"] = policy(info)
    info["codecs"] = codecs_string(info)
    if store is not None:
        store.set_probe(movie["id"], info)
    log.info("probed %s: %s/%s %sx%s -> %s", movie["id"], info["container"], info["video"],
             info["width"], info["height"], info["policy"]["mode"])
    return info
