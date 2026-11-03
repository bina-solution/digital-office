#!/bin/bash
# Produce processed 16-kHz versions of damaged benchmark streams for every restoration method.
# usage: methods.sh "NAME1 NAME2 ..." "METHOD1 METHOD2 ..."     (NAME = s0_mask103 etc.; input data/dmg/NAME.wav)
# output: data/proc/<method>/<NAME>.wav  (16 kHz mono PCM16)
set -e
cd /root/fpgaudio/bench/data && source /root/fpgaudio/venv/bin/activate
B=/mnt/c/Users/wbolo/AppData/Local/Temp/fpgaudio/bench
R=/mnt/c/Users/wbolo/AppData/Local/Temp/fpgaudio/restore.py
POST="highpass=f=80,acompressor=threshold=-28dB:ratio=3:attack=5:release=150:makeup=6,loudnorm=I=-18:TP=-2:LRA=11"
LN="loudnorm=I=-18:TP=-2:LRA=11"
F16="-ac 1 -ar 16000 -c:a pcm_s16le"
NAMES=$1; METHODS=$2
mkdir -p proc tmp
for N in $NAMES; do
  IN=dmg/$N.wav
  for M in $METHODS; do
    mkdir -p proc/$M
    OUT=proc/$M/$N.wav
    [ -f $OUT ] && continue
    case $M in
      raw)        ffmpeg -nostdin -v error -y -i $IN $F16 $OUT ;;
      raw_post)   ffmpeg -nostdin -v error -y -i $IN -af "$POST" $F16 $OUT ;;
      cut)        python $R $IN tmp/${N}_cut.wav --mode cut --map tmp/${N}_cut.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_cut.wav -af "$POST" $F16 $OUT ;;
      cut_ln)     python $R $IN tmp/${N}_cut.wav --mode cut --map tmp/${N}_cut.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_cut.wav -af "$LN" $F16 $OUT ;;
      cut15)      python $R $IN tmp/${N}_cut15.wav --mode cut --cut-min 0.15 --pause 0.35 --map tmp/${N}_cut15.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_cut15.wav -af "$POST" $F16 $OUT ;;
      inpaint)    python $R $IN tmp/${N}_inp.wav --mode inpaint >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_inp.wav -af "$POST" $F16 $OUT ;;
      inpaint_cut) python $R $IN tmp/${N}_inp06.wav --mode inpaint --inpaint-max 0.06 >/dev/null
                  python $R tmp/${N}_inp06.wav tmp/${N}_inpcut.wav --mode cut --no-edgefix --map tmp/${N}_inpcut.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_inpcut.wav -af "$POST" $F16 $OUT ;;
      noise6)     python $B/noisefill.py $IN tmp/${N}_n6.wav --level -6 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_n6.wav -af "$POST" $F16 $OUT ;;
      noise12)    python $B/noisefill.py $IN tmp/${N}_n12.wav --level -12 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_n12.wav -af "$POST" $F16 $OUT ;;
      noise12f)   python $B/noisefill.py $IN tmp/${N}_n12f.wav --level -12 --floor -55 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_n12f.wav -af "$POST" $F16 $OUT ;;
      plc)        python $B/plc_opus.py $IN tmp/${N}_plc.wav --max-gap 0.12 --trim 0.005 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_plc.wav -af "$POST" $F16 $OUT ;;
      plc_cut)    python $B/plc_opus.py $IN tmp/${N}_plc06.wav --max-gap 0.06 --trim 0.005 >/dev/null
                  python $R tmp/${N}_plc06.wav tmp/${N}_plccut.wav --mode cut --no-edgefix --map tmp/${N}_plccut.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_plccut.wav -af "$POST" $F16 $OUT ;;
      cut_st60)   python $R $IN tmp/${N}_cut.wav --mode cut --map tmp/${N}_cut.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_cut.wav -af "atempo=0.6,$POST" $F16 $OUT ;;
      cut_st75)   python $R $IN tmp/${N}_cut.wav --mode cut --map tmp/${N}_cut.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_cut.wav -af "atempo=0.75,$POST" $F16 $OUT ;;
      plccut_st75) python $B/plc_opus.py $IN tmp/${N}_plc06.wav --max-gap 0.06 --trim 0.005 >/dev/null
                  python $R tmp/${N}_plc06.wav tmp/${N}_plccut.wav --mode cut --no-edgefix --map tmp/${N}_plccut.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_plccut.wav -af "atempo=0.75,$POST" $F16 $OUT ;;
      plc_ln)     [ -f tmp/${N}_plc.wav ] || python $B/plc_opus.py $IN tmp/${N}_plc.wav --max-gap 0.12 --trim 0.005 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_plc.wav -af "$LN" $F16 $OUT ;;
      plc_f)      [ -f tmp/${N}_plc.wav ] || python $B/plc_opus.py $IN tmp/${N}_plc.wav --max-gap 0.12 --trim 0.005 >/dev/null
                  python $B/noisefill.py tmp/${N}_plc.wav tmp/${N}_plcf.wav --max-gap 0 --floor -55 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_plcf.wav -af "$LN" $F16 $OUT ;;
      noise12f_ln) [ -f tmp/${N}_n12f.wav ] || python $B/noisefill.py $IN tmp/${N}_n12f.wav --level -12 --floor -55 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_n12f.wav -af "$LN" $F16 $OUT ;;
      floor)      python $B/noisefill.py $IN tmp/${N}_floor.wav --max-gap 0 --floor -55 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_floor.wav -af "$LN" $F16 $OUT ;;
      trim)       python $R $IN tmp/${N}_trim.wav --mode cut --no-edgefix --keep-short --cut-min 2.0 --pause 1.0 --map tmp/${N}_trim.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_trim.wav $F16 $OUT ;;
      trim04)     python $R $IN tmp/${N}_trim04.wav --mode cut --no-edgefix --keep-short --cut-min 0.4 --pause 0.3 --map tmp/${N}_trim04.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_trim04.wav $F16 $OUT ;;
      trim04_post) [ -f tmp/${N}_trim04.wav ] || python $R $IN tmp/${N}_trim04.wav --mode cut --no-edgefix --keep-short --cut-min 0.4 --pause 0.3 --map tmp/${N}_trim04.map.json >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_trim04.wav -af "$POST" $F16 $OUT ;;
      trim04_n12f) [ -f tmp/${N}_trim04.wav ] || python $R $IN tmp/${N}_trim04.wav --mode cut --no-edgefix --keep-short --cut-min 0.4 --pause 0.3 --map tmp/${N}_trim04.map.json >/dev/null
                  python $B/noisefill.py tmp/${N}_trim04.wav tmp/${N}_trim04n.wav --level -12 --floor -55 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_trim04n.wav -af "$POST" $F16 $OUT ;;
      trim_n12f)  python $R $IN tmp/${N}_trim.wav --mode cut --no-edgefix --keep-short --cut-min 2.0 --pause 1.0 --map tmp/${N}_trim.map.json >/dev/null
                  python $B/noisefill.py tmp/${N}_trim.wav tmp/${N}_trimn.wav --level -12 --floor -55 >/dev/null
                  ffmpeg -nostdin -v error -y -i tmp/${N}_trimn.wav -af "$POST" $F16 $OUT ;;
      *) echo "unknown method $M"; exit 1 ;;
    esac
    echo "made $OUT ($(ffprobe -v error -show_entries format=duration -of csv=p=0 $OUT) s)"
  done
done
