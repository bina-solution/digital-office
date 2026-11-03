#!/bin/sh
# apps/meet — Jibri runs this once a recording is finished, with the recording's folder as $1
# (JIBRI_FINALIZE_RECORDING_SCRIPT_PATH; the image's default is /bin/true). It writes the meeting's
# audio beside the video, <room>_<time>.ogg: 16 kHz mono Opus at 32 kb/s, about 15 MB an hour, which
# is what the office's transcriber takes (DGO-834). Written under a temporary name and renamed, so
# the file exists only when it is whole. A failure here costs the transcript, never the video: the
# script always exits 0. Jibri waits for it before it takes the next recording (seconds, not minutes:
# ffmpeg copies no video, it only re-encodes the sound).
#
# …and <room>_<time>.silence.json: every stretch of the sound that is full silence (below -50 dB) for
# a minute or more (DGO-959: the owner's phone stopped sending his voice when he showed another app,
# and 21 minutes were recorded silent with nobody in the room to notice). The workflow writes them on
# the meeting's item. {"noise_db", "min_seconds", "duration", "stretches": [[start, end], …]}, seconds.
#
# …and <room>_<time>.holes.json: the damage fpg103/fpg104 had (fireplace, 2026-10-26: a recorder starved of CPU
# filled ~40 % of every second with digital zeros, 30-75 ms at a time, and the file looked whole). Real sound —
# a quiet room included — is never exactly zero; a capture that missed its deadline is. So: every stretch of
# 20 ms to 2 s below -91 dBFS (under one 16-bit step). Longer stretches are everyone muted, not damage (and the
# silence.json above has the minute-long ones). Measured: a healthy 20-minute ten-person test 0 runs; fpg103
# 471 runs, 414 s. {"noise_db", "min_seconds", "max_seconds", "duration", "runs", "seconds", "pct", "long_runs"}.
# meet-start tells the owner when pct ≥ 1 (start/server.py, the meetings' watch).
#
# …and first, an mp4 with no index is rebuilt (MEET-48, fireplace 2026-11-01: the server froze on memory,
# Jibri's graceful stop timed out and killed ffmpeg, 137 — the file kept its media and no moov, and this
# script found «moov atom not found» and wrote nothing). meet-rebuild-moov.py (tools/restore/rebuild_moov.py)
# reads the media itself, with a healthy recording beside it for the codecs' configuration; the original
# stays as <name>.mp4.no-moov. Exit 3 = rebuilt from what could be read, not all of it: kept all the same.
dir="$1"
[ -d "$dir" ] || exit 0
for video in "$dir"/*.mp4; do
  [ -f "$video" ] || continue
  if [ ! -e "$video.no-moov" ] && ! ffprobe -v error -show_entries format=duration -of csv=p=0 "$video" >/dev/null 2>&1; then
    python3 /usr/local/bin/meet-rebuild-moov.py "$video" "$video.rebuilt"
    rc=$?
    if { [ "$rc" = 0 ] || [ "$rc" = 3 ]; } && [ -s "$video.rebuilt" ]; then
      mv "$video" "$video.no-moov" && mv "$video.rebuilt" "$video"
    else
      rm -f "$video.rebuilt"
    fi
  fi
  audio="${video%.mp4}.ogg"
  if [ ! -s "$audio" ]; then
    if ffmpeg -nostdin -v error -y -i "$video" -vn -ac 1 -ar 16000 -c:a libopus -b:a 32k -f ogg "$audio.part"; then
      mv "$audio.part" "$audio"
    else
      rm -f "$audio.part"
    fi
  fi
  holes="${video%.mp4}.holes.json"
  if [ -s "$audio" ] && [ ! -s "$holes" ]; then
    hdur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$audio" 2>/dev/null)
    if [ -n "$hdur" ] && ffmpeg -nostdin -hide_banner -i "$audio" -af silencedetect=noise=-91dB:d=0.02 -f null - 2>&1 | awk -v dur="$hdur" '
        /silence_duration:/ { d = $NF + 0; if (d <= 2) { n++; s += d } else { long++ } }
        END { printf "{\"noise_db\": -91, \"min_seconds\": 0.02, \"max_seconds\": 2, \"duration\": %s, \"runs\": %d, \"seconds\": %.1f, \"pct\": %.2f, \"long_runs\": %d}\n", dur + 0, n, s, (dur > 0 ? 100 * s / dur : 0), long }' > "$holes.part"
    then
      mv "$holes.part" "$holes"
    else
      rm -f "$holes.part"
    fi
  fi
  silence="${video%.mp4}.silence.json"
  [ -s "$audio" ] && [ ! -s "$silence" ] || continue
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$audio" 2>/dev/null)
  [ -n "$dur" ] || continue    # a sound file ffprobe cannot read: no claim about its silence
  if ffmpeg -nostdin -hide_banner -i "$audio" -af silencedetect=noise=-50dB:d=60 -f null - 2>&1 | awk -v dur="${dur:-0}" '
      /silence_start:/ { s = $NF }
      /silence_end:/ { for (i = 1; i < NF; i++) if ($i == "silence_end:") e = $(i + 1)
                       out = out sep "[" s "," e "]"; sep = ","; s = "" }
      END { if (s != "") out = out sep "[" s "," (dur + 0) "]"
            printf "{\"noise_db\": -50, \"min_seconds\": 60, \"duration\": %s, \"stretches\": [%s]}\n", dur + 0, out }' > "$silence.part"
  then
    mv "$silence.part" "$silence"
  else
    rm -f "$silence.part"
  fi
done
exit 0
