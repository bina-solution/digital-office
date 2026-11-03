# apps/meet/tools/restore — recover speech from a chopped Jibri recording

## When to use

A recording whose sound is **chopped into short bursts separated by exact digital silence**. Cause: the recorder
(Jibri's Chrome + ffmpeg) was CPU-throttled; the audio reached ffmpeg in pieces and its `aresample=async=1`
filled the missing time with zeros (Jibri's command: `-f pulse -i default -acodec aac -b:a 128k -ar 44100
-af aresample=async=1`). Symptoms: the meeting item's transcript is a handful of words and "תודה רבה" lines;
in the waveform every word is a picket fence of 30–75 ms bursts with 30–50 ms holes, plus longer holes.
Reference case: `fpg103_2026-10-26-13-10-48` and `fpg104allanwilliam_2026-10-26-13-26-15` on the FPG office
(root cause and fix: `issues/meet-recorder-throttled-to-half-a-core-recordings-lose-sound-and-time.yaml`).

Diagnose first (any machine with Python + numpy + soundfile):

    ffmpeg -i REC.mp4 -vn -ac 1 -ar 44100 -c:a pcm_s16le rec44.wav
    python restore.py rec44.wav /dev/null --mode none --stats stats.json && cat stats.json

A healthy recording has a few zero runs (real silence). fpg103 had 1,326 bursts and 101 s of sound in 861 s;
fpg104 7,596 bursts and 404 s in 2,860 s. In the speech stretches 45–55 % of every second was zeros
(fpg103 235–424 s: 1,151 zero runs, hole median 38 ms, burst median 63 ms; fpg104 1–191 s: 1,305 runs).

## What can and cannot be recovered — measured, not guessed

The sound inside the holes never reached the file; nothing brings it back. The question was how many of the
spoken words the transcriber can still get, and which processing helps. This was measured on a ground-truth
benchmark: **FLEURS Hebrew** (google/fleurs `he_il` test, CC-BY-4.0), 72 read sentences (all male — the set is
787/792 male) joined into four streams of 146–179 s, **1,242 reference words**, damaged with the **exact zero
masks extracted from fpg103 (235–424 s) and fpg104 (1–191 s)** and then passed through the recorder's own chain
(AAC 128 kbps, 44.1 kHz; the simulated burst edges match the real ones: fade-in −61/−56/−49/−8 dB per ms vs
−62/−56/−52/−44/−14 dB in the recording). Scoring: Hebrew normalisation (niqqud/punctuation stripped) and word
alignment (`score.py`, jiwer): **recall** = correctly recognised reference words / reference words; WER =
substitutions + deletions + insertions; **ins** = inserted (hallucinated) words; precision = correct / output words.

Three damage variants, because a long zero hole in the real recording may be lost speech or a real pause:
*full* (every hole applied), *speech-holes* `_s` (holes > 0.3 s applied only where the real recording had
speech-level sound next to them — the best estimate of what was actually lost; fpg103: 11 of 59 long holes,
fpg104: 45 of 81), and *throttle-only* `_t` (holes > 0.3 s treated as pauses; upper bound).

Physical ceiling under the full masks (word spans from the clean transcription): 30–38 % of the words keep less
than 30 % of their samples and 18–23 % are erased completely by mask103 → **≥ 80 % recall is impossible under the
full-mask assumption; only ~65–70 % of the words are physically recognisable**. Under the `_s` variant 85 % of the
word-samples survive and only 1–2 % of the words are erased.

### A. Baselines, all 4 streams (turbo beam 5, temp 0)
| tag | method | mask | streams | N | recall | WER | ins | precision |
|---|---|---|---|---:|---:|---:|---:|---:|
| turbo_b5 | clean | clean | s0,s1,s2,s3 | 1242 | 0.899 | 0.111 | 13 | 0.896 |
| turbo_b5 | damaged | mask103 | s0,s1,s2,s3 | 1242 | 0.458 | 0.560 | 22 | 0.584 |
| turbo_b5 | damaged | mask104 | s0,s1,s2,s3 | 1242 | 0.447 | 0.560 | 8 | 0.628 |

### B. Signal-processing methods, screening stream s0 (307 words; turbo beam 5, temp 0)
| tag | method | mask | streams | N | recall | WER | ins | precision |
|---|---|---|---|---:|---:|---:|---:|---:|
| turbo_b5 | clean | clean | s0 | 307 | 0.919 | 0.094 | 4 | 0.910 |
| screen | raw_post | mask103 | s0 | 307 | 0.577 | 0.430 | 2 | 0.797 |
| screen | floor | mask103 | s0 | 307 | 0.560 | 0.459 | 6 | 0.771 |
| turbo_b5 | damaged | mask103 | s0 | 307 | 0.557 | 0.456 | 4 | 0.763 |
| screen | noise12f | mask103 | s0 | 307 | 0.554 | 0.459 | 4 | 0.759 |
| screen | plc_cut | mask103 | s0 | 307 | 0.524 | 0.482 | 2 | 0.752 |
| screen | cut_st60 | mask103 | s0 | 307 | 0.524 | 0.482 | 2 | 0.739 |
| screen | cut | mask103 | s0 | 307 | 0.518 | 0.492 | 3 | 0.743 |
| screen | cut_st75 | mask103 | s0 | 307 | 0.511 | 0.492 | 1 | 0.734 |
| screen | plc_f | mask103 | s0 | 307 | 0.505 | 0.502 | 2 | 0.752 |
| screen | inpaint | mask103 | s0 | 307 | 0.463 | 0.541 | 1 | 0.793 |
| screen | plc | mask103 | s0 | 307 | 0.397 | 0.619 | 5 | 0.689 |
| screen | inpaint | mask104 | s0 | 307 | 0.492 | 0.515 | 2 | 0.774 |
| screen | floor | mask104 | s0 | 307 | 0.489 | 0.515 | 1 | 0.765 |
| turbo_b5 | damaged | mask104 | s0 | 307 | 0.485 | 0.518 | 1 | 0.550 |
| screen | noise12f | mask104 | s0 | 307 | 0.479 | 0.524 | 1 | 0.766 |
| screen | raw_post | mask104 | s0 | 307 | 0.479 | 0.524 | 1 | 0.774 |
| screen | plc_cut | mask104 | s0 | 307 | 0.476 | 0.534 | 3 | 0.655 |
| screen | cut_st75 | mask104 | s0 | 307 | 0.472 | 0.541 | 4 | 0.633 |
| screen | plc_f | mask104 | s0 | 307 | 0.459 | 0.547 | 2 | 0.746 |
| screen | plc | mask104 | s0 | 307 | 0.453 | 0.554 | 2 | 0.702 |
| screen | cut_st60 | mask104 | s0 | 307 | 0.436 | 0.580 | 5 | 0.620 |
| screen | cut | mask104 | s0 | 307 | 0.430 | 0.583 | 4 | 0.677 |

### C. ASR-side variants, s0
| tag | method | mask | streams | N | recall | WER | ins | precision |
|---|---|---|---|---:|---:|---:|---:|---:|
| turbo_tf | damaged | mask103 | s0 | 307 | 0.564 | 0.450 | 4 | 0.772 |
| turbo_cond | damaged | mask103 | s0 | 307 | 0.560 | 0.450 | 3 | 0.764 |
| turbo_tf | noise12f | mask103 | s0 | 307 | 0.554 | 0.459 | 4 | 0.762 |
| turbo_b10 | damaged | mask103 | s0 | 307 | 0.554 | 0.459 | 4 | 0.759 |
| turbo_vad | noise12f | mask103 | s0 | 307 | 0.544 | 0.463 | 2 | 0.773 |
| turbo_cond | noise12f | mask103 | s0 | 307 | 0.534 | 0.485 | 6 | 0.554 |
| large_b5 | damaged | mask103 | s0 | 307 | 0.489 | 0.524 | 4 | 0.765 |
| large_b5 | noise12f | mask103 | s0 | 307 | 0.476 | 0.531 | 2 | 0.764 |
| turbo_b10 | noise12f | mask103 | s0 | 307 | 0.433 | 0.573 | 2 | 0.760 |
| turbo_vad | damaged | mask103 | s0 | 307 | 0.407 | 0.599 | 2 | 0.812 |
| large_b5 | damaged | mask104 | s0 | 307 | 0.508 | 0.492 | 0 | 0.839 |
| turbo_tf | damaged | mask104 | s0 | 307 | 0.502 | 0.502 | 1 | 0.733 |
| turbo_tf | noise12f | mask104 | s0 | 307 | 0.502 | 0.502 | 1 | 0.716 |
| turbo_b10 | damaged | mask104 | s0 | 307 | 0.489 | 0.577 | 20 | 0.464 |
| turbo_cond | damaged | mask104 | s0 | 307 | 0.485 | 0.518 | 1 | 0.842 |
| turbo_vad | noise12f | mask104 | s0 | 307 | 0.482 | 0.521 | 1 | 0.744 |
| large_b5 | noise12f | mask104 | s0 | 307 | 0.479 | 0.531 | 3 | 0.707 |
| turbo_b10 | noise12f | mask104 | s0 | 307 | 0.472 | 0.531 | 1 | 0.771 |
| turbo_cond | noise12f | mask104 | s0 | 307 | 0.472 | 0.531 | 1 | 0.819 |
| turbo_vad | damaged | mask104 | s0 | 307 | 0.427 | 0.573 | 0 | 0.804 |

### D. The real-file chain measured: trim 0.4 s + raw/post/noise12f, temperature fallback (s0+s1)
| tag | method | mask | streams | N | recall | WER | ins | precision |
|---|---|---|---|---:|---:|---:|---:|---:|
| trim | trim04 | mask103 | s0,s1 | 633 | 0.517 | 0.490 | 4 | 0.775 |
| trim | trim04_post | mask103 | s0,s1 | 633 | 0.499 | 0.507 | 4 | 0.775 |
| trim | trim04_n12f | mask103 | s0,s1 | 633 | 0.482 | 0.523 | 3 | 0.719 |
| trim | trim04 | mask104 | s0,s1 | 633 | 0.491 | 0.515 | 4 | 0.702 |
| trim | trim04_post | mask104 | s0,s1 | 633 | 0.479 | 0.526 | 3 | 0.706 |
| trim | trim04_n12f | mask104 | s0,s1 | 633 | 0.447 | 0.561 | 5 | 0.694 |

### E. Final chain, full masks, all streams: single systems (tf), ROVER, LLM layer
| tag | method | mask | streams | N | recall | WER | ins | precision |
|---|---|---|---|---:|---:|---:|---:|---:|
| turbo_tf | damaged | mask103 | s0 | 307 | 0.564 | 0.450 | 4 | 0.772 |
| turbo_tf | noise12f | mask103 | s0 | 307 | 0.554 | 0.459 | 4 | 0.762 |
| llm_full | llm | mask103 | s0,s1,s2,s3 | 1242 | 0.487 | 0.525 | 15 | 0.762 |
| fin | raw_post | mask103 | s0,s1,s2,s3 | 1242 | 0.477 | 0.536 | 16 | 0.726 |
| rover_full | rover | mask103 | s0,s1,s2,s3 | 1242 | 0.472 | 0.541 | 16 | 0.793 |
| fin | damaged | mask103 | s1,s2,s3 | 935 | 0.449 | 0.569 | 17 | 0.691 |
| fin | noise12f | mask103 | s1,s2,s3 | 935 | 0.418 | 0.600 | 17 | 0.678 |
| turbo_tf | damaged | mask104 | s0 | 307 | 0.502 | 0.502 | 1 | 0.733 |
| turbo_tf | noise12f | mask104 | s0 | 307 | 0.502 | 0.502 | 1 | 0.716 |
| llm_full | llm | mask104 | s0,s1,s2,s3 | 1242 | 0.461 | 0.545 | 7 | 0.707 |
| fin | raw_post | mask104 | s0,s1,s2,s3 | 1242 | 0.448 | 0.563 | 13 | 0.668 |
| rover_full | rover | mask104 | s0,s1,s2,s3 | 1242 | 0.443 | 0.565 | 10 | 0.765 |
| fin | damaged | mask104 | s1,s2,s3 | 935 | 0.432 | 0.574 | 6 | 0.657 |
| fin | noise12f | mask104 | s1,s2,s3 | 935 | 0.407 | 0.603 | 10 | 0.614 |

### F. Speech-holes variant (_s): what was really lost

### G. Per-utterance set (36 FLEURS sentences, 651 words, mask103 full; turbo tf)
| set | N | recall | WER | ins | precision |
|---|---:|---:|---:|---:|---:|
| clean utterances | 651 | 0.897 | 0.111 | 5 | 0.897 |
| damaged, unprocessed | 651 | 0.564 | 0.439 | 2 | 0.735 |

Single sentences recognise better than 3-minute streams under the same mask (0.564 vs 0.477), because each
sentence meets a different stretch of the mask and whisper decodes it in one window.

### What this means

* **Chosen chain** (restore_recording.sh + restore_transcript.sh): holes ≥ 0.4 s shortened to 0.3 s, everything shorter kept as it is (zeros included) — the trim is transparent for the recogniser (table D) and makes a 48-min recording 25 min; three ASR inputs (raw / +highpass-compressor-loudnorm / +LPC-noise fill −12 dB and a −55 dBFS floor); faster-whisper turbo int8, beam 5, temperature fallback 0→1.0; then the LLM layer choosing among the three hypotheses. On all 1,242 words it gives recall 0.492 / 0.461 (mask103 / mask104, full masks; precision 0.79 / 0.71) against 0.458 / 0.447 for the damaged audio as it is and 0.477 / 0.448 for the best single system; under the speech-holes variant 0.770 / 0.579 (precision 0.83 / 0.74) against 0.758 / 0.567 raw. No signal-processing method recovers words that whisper does not already get from the zero-gapped audio: Opus Deep PLC (0.397 / 0.453 on s0), LPC inpainting (0.463 / 0.492), the previous cut chain (0.518 / 0.430 vs 0.557 / 0.485 raw) are all worse or equal; the processing buys precision (fewer hallucinated words) and listenability.
* **The 80 % target is not reached.** Best-estimate damage (`_s`): 77 % of the spoken words for fpg103's damage pattern (per stream 80 / 77 / 74 / 76 %), 58 % for fpg104's (its long holes sit in speech far more often); if every hole was lost speech: 49 % / 46 %. The limit is physical, not algorithmic: with fpg103's mask 30 % of the words keep less than 30 % of their samples and 18 % are erased completely; with the `_s` mask still 8 % (fpg103) and 16–21 % (fpg104). The clean upper bound of the same recogniser on this material is 0.899. The listening version keeps the original timeline; the long holes stay audible as holes.
* Spontaneous meeting speech (cross-talk, Opus microphones, Hebrew slang) recognises worse than read FLEURS even
  when undamaged, so the real recordings sit below the benchmark numbers; the benchmark's clean upper bound is
  0.899 recall (proper nouns dominate the errors).

## Methods that were tried (all in this folder; numbers above)

| method | timeline | what |
|---|---|---|
| `raw` | kept | nothing — whisper on the zero-gapped audio |
| `raw_post` | kept | highpass 80 Hz + compressor + loudnorm (the previous chain's post-filter) |
| `floor` | kept | a −55 dBFS pink floor so nothing is digital silence |
| `noise12f` | kept | phonemic-restoration fill: LPC(16)-shaped noise at −12 dB in holes ≤ 0.3 s + the floor |
| `inpaint` | kept | pitch-period / chunk-mirror extrapolation from both sides (restore.py) |
| `plc` / `plc_f` | kept | libopus 1.5.2 **Deep PLC**: each hole ≤ 120 ms is a lost 10-ms SILK packet, decoder complexity 10 |
| `cut` | compressed | the previous chain: holes < 0.3 s removed (2-ms crossfades), longer → 0.25 s, edge fix, post-filter |
| `cut_st60/75` | compressed | `cut`, then slowed with `atempo` |
| `plc_cut` | compressed | Deep PLC for holes ≤ 60 ms, then `cut` |
| `trim04` | nearly kept | holes ≥ 0.4 s shortened to 0.3 s, everything else untouched (the final chain's ASR timeline) |

ASR: faster-whisper, `ivrit-ai/whisper-large-v3-turbo-ct2` int8 on CPU, beam 5, `condition_on_previous_text`
off, VAD off, word timestamps; **temperature fallback 0→1.0** (adopted); beam 10, VAD, conditioning and the
non-turbo `whisper-large-v3-ct2` were measured and rejected (table C). `rover.py` votes across variants;
`llm_layer.py` is the separate, clearly labelled LLM reconstruction (DeepSeek chat): it may only choose among the
hypotheses and fix split/merged words — its invention rate was measured (0.5–1.4 % of its words occur in no
hypothesis) together with its precision.

## How to run on a recording (a workstation, never the office VPS)

Requirements: Python 3.12 with `numpy soundfile soxr scipy faster-whisper jiwer` (CPU, int8), ffmpeg; for the
Deep-PLC experiments libopus ≥ 1.5.2 built with `--enable-deep-plc` (`build_opus.sh`). The DeepSeek key file for
the LLM layer (`~/.deepseek_key`), or use `--rover`.

    export VENV=/path/to/venv                      # optional
    bash restore_recording.sh /path/fpg103_2026-10-26-13-10-48.mp4 /path/out
    bash restore_transcript.sh /path/out fpg103-restored2_2026-10-26-13-10-48 "<method text>" "<benchmark text>"

`restore_recording.sh` writes the listening files `<room>-restored2_<stamp>.ogg/.mp4` (original timeline, original
video, noise-filled holes, −22 LUFS), the ASR inputs, `transcript.json`, `trim.map.json` and `stats.json`;
`restore_transcript.sh` writes `comment.html/.txt` with timestamps on the ORIGINAL clock. Memory: a 48-min
recording needs ~2 GB for the trim step; the whisper process takes 1.3–1.6 GB; run one heavy step at a time
in a 5 GB VM. Time: whisper turbo ≈ 0.3× real time per worker on 6 ARM cores (fpg104: 2 inputs × 1,473 s took 46 min).

Upload next to the originals so the meet workflow files them as their own items (it did: MEET-31 for
fpg103-restored2): `scp` to `/var/lib/docker/volumes/fireplace_meet_recordings/_data/recordings/<session>/`,
`chown 1000:1000`, `sha256sum` on both sides (`upload_restored.sh`). Post the comment from inside the
project-pln container (`pl_post.sh` → `pl_comment.py`; the key comes from `plan.api_key()` and is never printed).

## Reproducing the benchmark

    python mask_extract.py rec44.wav mask.json --densest 190            # or --region START:END
    python make_bench.py fleurs/ data/ --masks mask103.json mask104.json --n-utt 72 --stream-max 180 --variants full,t,s
    bash methods.sh "s0_mask103 s0_mask104 …" "raw_post noise12f cut plc …"
    python asr_run.py asr.json --temp 0,0.2,0.4,0.6,0.8,1.0 stream/*.wav dmg16/*.wav proc/*/*.wav
    python table.py data/refs.json asr.json --md ;  python ceiling.py asr.json data s0 mask103 mask104

FLEURS: `data/he_il/test.tsv` + `audio/test.tar.gz` from huggingface.co/datasets/google/fleurs. No ungated
human-transcribed conversational Hebrew set was available (ivrit-ai's crowd/eval sets are gated; audio-v2-40s has
machine transcripts), so the conversational case is not benchmarked.
