#!/bin/sh
# Runs in the jibri image (root): measure one recording.  measure.sh <mp4 inside /d> <outdir inside /out>
set -u
f="$1"; out="$2"; mkdir -p "$out"
echo "== ffprobe"; ffprobe -v error -show_entries format=duration:stream=codec_type,nb_frames,bit_rate -of compact "$f"
echo "== audio gaps (-35 dB, >=0.15 s)"
ffmpeg -nostdin -hide_banner -i "$f" -vn -af "silencedetect=noise=-35dB:d=0.15" -f null - 2> "$out/silence35.txt"
grep -oE "silence_duration: [0-9.]+" "$out/silence35.txt" | awk '{d=$2; n++; t+=d; if(d<0.5)a++; else if(d<2)b++; else if(d<10)c++; else e++} END{print "gaps="n+0, "total="t+0, "<0.5s:"a+0, "0.5-2s:"b+0, "2-10s:"c+0, ">10s:"e+0}'
echo "== sound seconds"
ffmpeg -nostdin -hide_banner -i "$f" -vn -af "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=$out/rms.txt" -f null - 2>/dev/null
python3 - "$out/rms.txt" <<'EOF'
import re, sys
vals = []
for line in open(sys.argv[1]):
    m = re.search(r"RMS_level=(-?[0-9.]+|-inf)", line)
    if m: vals.append(-99.0 if m.group(1) == "-inf" else float(m.group(1)))
per = 1024 / 44100
secs = {}
for i, v in enumerate(vals):
    s = int(i * per); secs[s] = max(secs.get(s, -99), v)
n = max(secs) + 1
loud = [1 if secs.get(s, -99) > -40 else 0 for s in range(n)]
print("seconds", n, "with sound", sum(loud), "per-minute", [sum(loud[m:m+60]) for m in range(0, n, 60)])
EOF
echo "== scene cuts (>0.35) and freezes (>=3 s)"
ffmpeg -nostdin -hide_banner -i "$f" -an -vf "scale=320:180,select=gt(scene\,0.35),showinfo" -vsync vfr -f null - 2> "$out/scenes.txt"
echo "cuts: $(grep -c pts_time "$out/scenes.txt") at: $(grep -oE 'pts_time:[0-9.]+' "$out/scenes.txt" | cut -d: -f2 | awk '{printf "%d ", $1}')"
ffmpeg -nostdin -hide_banner -i "$f" -an -vf "scale=320:180,freezedetect=n=-50dB:d=3" -f null - 2> "$out/freeze.txt"
echo "freezes: $(grep -c freeze_start "$out/freeze.txt") total $(grep -oE 'freeze_duration: [0-9.]+' "$out/freeze.txt" | awk '{t+=$2} END{print t+0}') s"
ffmpeg -nostdin -hide_banner -loglevel error -i "$f" -an -vf "fps=1/10,scale=256:144,tile=6x6" -q:v 4 "$out/montage_%02d.jpg"
echo MEASURE-DONE
