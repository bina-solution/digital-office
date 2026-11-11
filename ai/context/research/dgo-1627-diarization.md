# DGO-1627 — speaker diarization inside the office: every speaker is «שלמה» today

Research and design only (no installs, no container changed). Written 2026-11-09 for MEET-28.
Read in the repo: `apps/meet/AGENT.md`, `apps/meet/README.md` («Transcripts → Plane», DGO-834/DGO-955),
`apps/meet/blueprint/n8n/meetRecordings01.workflow.ts`, `apps/meet/tools/flow/build_flow.py`,
`ai/context/local-asr-research.md` (the ASR benchmark), `ai/context/dgo-herd.md` (the Dell).
Every third-party claim carries the URL it was read from; anything I could not verify is marked.

**Recommendation: put diarization inside the transcription pass, not next to it — assign a speaker to
each **ASR segment** with ivrit.ai's own `ivrit` engine (SpeechBrain ECAPA-TDNN embeddings +
clustering, MIT code, Apache-2.0 model, **no Hugging Face account**), and let `build_flow.py` take
`who` from that segment instead of from the analysis. It costs a fraction of the ASR's own time. Keep
pyannote 3.1 (via ivrit's **ungated** fork) as the accuracy upgrade if a two-voice crosstalk test says
the cheap engine mixes speakers — measure that once on the Dell before choosing. The owner's step is
**naming** the labels, not downloading anything: the gated-download fear is real for pyannote's own
models but does not apply to the two repos we would actually use (evidence in §4).

---

## 1. What the pipeline does today, exactly

```
meet-jibri ──► recordings/<session>/<room>_<time>.mp4      (one mixed stream: Jitsi composites)
   │
   └─ n8n meetRecordings01 (runs on the HP, DGO-945):  audio ─► speech twice
        speech #1  ivrit.ai  (faster-whisper, whisper-large-v3-turbo-ct2, int8, language=he)
        speech #2  Whisper   (auto language, "untranslated", DGO-955)
                   └─► {model, segments:[{start, end, text}]}   ← NO speaker, by construction
   ▼
Plane MEET item (both transcripts)
   ▼
«קדימה» ─► analysis JSON (an agent writes it) ─► build_flow.py ─► flow/data.js ─► the meeting page
```

The line that makes every speaker «שלמה» is in `apps/meet/tools/flow/build_flow.py`:

```python
speaker = str(an.get("speaker") or (an.get("who") or ["משתתף"])[0])       # line 145
turns = [{"id": …, "s": a, "e": b, "who": speaker, "text": t, …} for (a, b, t) in segments(he)]
```

Every turn gets that one name, and the flow's stage block then claims
`"speakers": {"state": "done", "detail": ", ".join(people)}` — a **stage marked done on a name nobody
measured**. (The name comes from the analysis, which the agent writes from the transcript: the office
owner is the one constant, so every line becomes his.)

Two structural facts decide the design:

1. **The recording is a single mixed stream.** `meet-jibri` records a composited 1280×720 mp4; Jitsi
   does not hand us per-participant audio. So there is nothing to separate by track — a diarization
   *algorithm* is the only way to get «who spoke», exactly as the item says.
2. **The page's unit is the ASR segment.** `turns` are the ASR segments (one line each, with
   `s`/`e` on the recording's clock). So the question is not "when does the voice change" but
   **"which of these ~400–900 lines belongs to whom"** — a *segment-level* assignment. Word-level
   alignment is therefore not required, and neither is whisperX's alignment pass.

## 2. Where a label has to land (the design)

```
speech (apitools-asr)  ──►  {segments:[{start,end,text, speaker}]}        ← one new field
        ▲                        │
        └─ diarize(audio, segments) ┘  (same container, same CPU, same job)
   ▼
n8n workflow: passes the JSON through unchanged (it already stores it on the item)
   ▼
build_flow.py: turns[].who = seg["speaker"] (mapped to a name), colors per speaker,
               stages.speakers.detail = the labels actually found, state "done" only if ≥1 label
   ▼
the meeting page: a colour and an initial per speaker, the way it already draws «who»
```

This is one field through the existing path, one line changed in `build_flow.py`, and one new stage
inside the transcriber's own job — not a new container, not a new service, not a new queue. It stays
inside DGO-1407: the model runs on the Dell, the audio never leaves the office.

**Anonymous labels are honest.** Diarization gives `SPK_0`, `SPK_1`, … (`num_speakers` optional). The
names are the owner's: the meeting page asks once («SPK_1 — מי זה?»), the answer is stored with the
flow, and the page re-renders. That is the one `בעלים` step in this item, and it is by design — an
algorithm must not invent a person's name.

## 3. The candidates, on the three axes that matter here

CPU column = a projection for **the Dell (2 cores, 2015 class, 16 GB, no GPU)**; see §5 for the
arithmetic and for why it is an estimate, not a measurement.

| option | licence (read 2026-11-09) | account/token? | per audio hour on 2 old cores | Hebrew | fits after the ASR pass? |
|---|---|---|---|---|---|
| **ivrit-py, `engine="ivrit"`** — ECAPA-TDNN embeddings of each ASR segment + agglomerative/K-means (best of three by silhouette), `num_speakers` optional | **MIT** code ([README](https://github.com/ivrit-ai/ivrit-py)); model `speechbrain/spkrec-ecapa-voxceleb` **Apache-2.0**, ungated | **none** (verified: HF `gated=False`) | **≈ 0.5–2 min** (one forward per segment, no frame pass) | built by ivrit.ai for their Hebrew audio; **no published DER** (see §6) | **native**: `transcribe(…, diarize=True, diarization_args={"engine":"ivrit"})` already returns segments with speakers |
| **pyannote 3.1 via `ivrit-ai/pyannote-speaker-diarization-3.1`** (frame-level segmentation + wespeaker embeddings + agglomerative) | checkpoint **MIT**, ungated; `ivrit-ai/pyannote-segmentation-3.0` ungated; `pyannote/wespeaker-voxceleb-resnet34-LM` **CC-BY-4.0**, ungated | **none** | **≈ 90–280 min** worst case, ≈ 20–60 min best (CPU evidence in §5) | language-agnostic (speaker embeddings, no text); the best-documented accuracy in the field | yes — pyannote turns → assign each ASR segment by maximum overlap |
| **stock pyannote** (`pyannote/speaker-diarization-3.1`, v4 `community-1`) | 3.1 MIT / community-1 CC-BY-4.0 | **YES — gated**: the model page answers `401 … You must have access … Please log in` ([measured](https://huggingface.co/pyannote/speaker-diarization-3.1)), HF API `gated=auto` | as above | as above | same as above, but the download is the **owner's** step (`hf` account + accept terms + token in the vault) — the fork above removes it |
| **whisperX** | **BSD-2-Clause** ([repo](https://github.com/m-bain/whisperX)) | its diarization **is** pyannote (`HF_TOKEN` by default); a Hebrew alignment model exists (`imvladikon/wav2vec2-xls-r-300m-hebrew`, `whisperx/alignment.py`) | ASR again + alignment + pyannote: the most expensive of the four | Hebrew alignment present; word timestamps are its point | **wrong tool**: it wants to re-transcribe and re-align to get word times we do not need, and it pulls the gated pyannote pipeline |
| **NeMo** (toolkit **Apache-2.0**, v3.0.0) + `nvidia/diar_sortformer_4spk-v1` | toolkit Apache-2.0; model **CC-BY-NC-4.0** (non-commercial), ungated | none | GPU-oriented; on CPU a torch-heavy stack for a 4-speaker cap | no Hebrew claim; English-focused models | no: **NC licence blocks an office's commercial use**, and 2 old cores is the wrong box for it |
| **simple-diarizer** | **GPL-3.0**, last push 2024-05 | none | small (ECAPA + clustering), but unmaintained | no | no: GPL in our image for a stale 40-line idea we already have (ivrit's engine) |
| **sherpa-onnx** (Apache-2.0) offline diarization | Apache-2.0 repo; ONNX conversions of pyannote segmentation + 3D-Speaker/NeMo embeddings | none | lightest floor (ONNX Runtime, **no torch**) | no Hebrew claim (embedding-only, so text-free) | a valid fallback, but a second inference stack next to the ASR; only if the ivrit engine is refused |

**Why the ivrit engine is the first choice and not a hack:** the wrapper we already deploy
(`ivrit-py`) ships two engines in `ivrit/diarization.py` — a pyannote one (derived from WhisperX,
BSD-2) and an **"ivrit"** one built on SpeechBrain ECAPA with a cluster-selection loop. It takes the
transcription segments as input, which is exactly the shape our pipeline already has. Reusing it means
no new model family, no new gate, no second stack.

## 4. The download question, answered with evidence (this is what could have made it the owner's step)

| model repo | HF `gated` | licence |
|---|---|---|
| `pyannote/speaker-diarization-3.1` (stock) | **auto** — page returns 401 «must have access» | MIT |
| `pyannote/speaker-diarization-community-1` (v4) | **auto** | CC-BY-4.0 |
| `pyannote/segmentation-3.0` | **auto** | MIT |
| **`ivrit-ai/pyannote-speaker-diarization-3.1`** | **False** | MIT (fork of pyannote 3.1, its README says so) |
| **`ivrit-ai/pyannote-segmentation-3.0`** | **False** | none declared on the copy (upstream is MIT) |
| **`pyannote/wespeaker-voxceleb-resnet34-LM`** | **False** | CC-BY-4.0 |
| **`speechbrain/spkrec-ecapa-voxceleb`** | **False** | Apache-2.0 |
| `nvidia/diar_sortformer_4spk-v1` | False | **CC-BY-NC-4.0** |

And the pipeline that the ivrit checkpoint pulls is exactly those ungated repos
(`config.yaml`: `segmentation: ivrit-ai/pyannote-segmentation-3.0`,
`embedding: pyannote/wespeaker-voxceleb-resnet34-LM`). **So the honest answer to the item's question
is: no account and no token are needed for either engine we recommend** — the gate exists on
pyannote's own pages, and ivrit.ai already paid the work of removing it. Only the *names* need a
person. (Two caveats: the fork is a fork — 3.1-level quality, not v4; and its copies carry no licence
metadata, so the credit line in the image should name pyannote.)

## 5. Cost on the Dell — the arithmetic, and what must be measured

Measured facts we already have:
* ivrit.ai ASR on 2 vCPU: **RTF 0.29–0.35** (≈ 3× slower than real time) — `ai/context/local-asr-research.md`,
  measured 2026-10-06 on the HP's cores. The Dell is older, so a one-hour meeting is a night job
  already (`ai/context/dgo-herd.md`: «on the Dell it is a night job»).
* pyannote 3.1 on CPU, published in its own issue tracker: a 2-minute sample took **22 s on an M1
  CPU**; on a Colab CPU, **559 s for a 2-minute audio** (v3.1 vs **116 s** for v3.0.1) —
  [issue #1621](https://github.com/pyannote/pyannote-audio/issues/1621). That spread is why a
  benchmark on the actual box is required and a web number is not.

Projection for **one audio hour** on the Dell:

| engine | what it does per hour of audio | CPU (projected) | vs the ASR's ~180 min |
|---|---|---|---|
| ivrit (ECAPA + clustering) | ~400–900 segment embeddings (1–3 s crops) + decoding + clustering | **0.5–2 min** | **+0.3–1 %** — free |
| pyannote 3.1 (frame-level) | 720 windowed segmentation passes + ~300–800 turn embeddings + clustering | **20–280 min** (machine-dependent, see the 22 s vs 559 s spread) | **+11 % to +155 %** — could double the night |
| whisperX | ASR again + alignment + one of the above | more than both | no |

**The measurement to run before any choice** (one job, ~15 min, no install in production — a throwaway
container from the ASR image with the model baked in, or a venv in `/tmp` on the Dell):
a 10-minute cut of a real recording from `/הקלטות` or the meetings volume, timed end to end for each
engine, and the same 10 minutes hand-labelled by the owner (or by two of us listening) for
speaker-attribution errors. Two numbers out: **minutes per audio hour** and **how many lines carry the
wrong name** in a two-voice stretch. That is the acceptance test for this item's next step.

## 6. Hebrew accuracy — what exists, honestly

* **No published DER for Hebrew** for any of these engines that I could find in this session; I did not
  find an ivrit.ai diarization benchmark. Do not quote one.
* The *method* is language-agnostic: both engines classify **voices** (ECAPA / wespeaker embeddings),
  not words, so Hebrew is not a special case for them. What *is* Hebrew-specific is the audio
  (often two voices on one mixed track, telephone-ish WhatsApp audio, crosstalk).
* The ivrit engine is the one ivrit.ai built for their own Hebrew users (it is the wrapper's default
  alternative to pyannote), which is weak evidence of fitness but the only Hebrew-specific fact there is.
* whisperX's Hebrew word-alignment model exists (`imvladikon/wav2vec2-xls-r-300m-hebrew`) — worth
  knowing, but our page needs segment-level labels, so it is not needed.
* Consequence: **the accuracy claim has to come from our own recordings** (§5's test), not from a
  vendor page. Until then the honest stage state on the meeting page is «דוברים: זוהו 3 קולות» and the
  names stay the owner's.

## 7. Recommendation, in order

1. **Implement segment-level diarization inside the ASR job** with the `ivrit` engine
   (`ivrit.load_model(engine="faster-whisper", …).transcribe(path, language="he", diarize=True,
   diarization_args={"engine":"ivrit","device":"cpu","num_speakers":N})`), writing `speaker` into each
   segment of the JSON the workflow already stores. No new container; the models come in at image build
   (like the ASR model, 1.6 GB, downloaded once).
2. **`build_flow.py` takes `who` from the segment**, colours per label, and states the labels it
   actually found; `an["speaker"]` survives only as the fallback for a meeting with one voice.
3. **The names: one question per meeting on the page** («מי זה SPK_1?»), stored with the flow — the
   `בעלים` step, and the only one.
4. **Measure the 10-minute two-voice sample** (§5). If the cheap engine confuses speakers on crosstalk,
   switch the engine to `pyannote` with the **ivrit fork** checkpoint (still no account), accepting the
   CPU risk on the Dell — and if that is too slow there, `num_speakers` + sherpa-onnx is the floor.
5. **`num_speakers`**: the meeting's item knows the participants from Jitsi's roster (`meet` writes who
   joined). Use it as the hint (`max_speakers`), never as truth.

**What would change this:** per-participant audio from Jitsi (the real fix for accuracy — the recorder
would have to capture tracks separately, a much bigger change), or a Hebrew diarization benchmark that
contradicts the above.

## 8. Not verified here

* No engine was run: nothing was installed, no container changed (the item is research).
* The CPU projections for the Dell are arithmetic + the published spread, not measurements —
  §5 names the test that replaces them.
* pyannote's v4 (`community-1`) behaviour on CPU was not read beyond its HF metadata; the
  recommendation deliberately pins 3.1 via the ivrit fork.
* NeMo's own model zoo (`diar_msdd_*`) was not read (the HF lookup returned nothing under that name);
  the sortformer model's licence (`CC-BY-NC-4.0`) is what rules NeMo out, not its capabilities.

## Sources (read 2026-11-09)

* `ivrit-py` (MIT) — README (`transcribe(diarize=…)`, `diarization_args`) and `ivrit/diarization.py`
  (the two engines, the checkpoint names, the ECAPA + clustering method) —
  https://github.com/ivrit-ai/ivrit-py
* Hugging Face model metadata (gating and licence) — the `/api/models/<repo>` answer for
  `ivrit-ai/pyannote-speaker-diarization-3.1` (gated False, MIT), `ivrit-ai/pyannote-segmentation-3.0`
  (False), `pyannote/wespeaker-voxceleb-resnet34-LM` (False, CC-BY-4.0),
  `pyannote/speaker-diarization-3.1` (auto; the page itself answers 401),
  `pyannote/speaker-diarization-community-1` (auto, CC-BY-4.0), `pyannote/segmentation-3.0` (auto),
  `nvidia/diar_sortformer_4spk-v1` (False, **CC-BY-NC-4.0**), `speechbrain/spkrec-ecapa-voxceleb`
  (False, Apache-2.0)
* pyannote 3.1 CPU timings — https://github.com/pyannote/pyannote-audio/issues/1621
* whisperX (BSD-2) — https://github.com/m-bain/whisperX ; Hebrew alignment entry in
  `whisperx/alignment.py`
* sherpa-onnx (Apache-2.0) offline diarization — https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html
* NeMo toolkit Apache-2.0 v3.0.0 — PyPI metadata (`nemo_toolkit`)
* In-repo: `apps/meet/tools/flow/build_flow.py` (line 145 and the `turns` block),
  `apps/meet/blueprint/n8n/meetRecordings01.workflow.ts`, `apps/meet/AGENT.md`,
  `apps/meet/README.md` § «The target: the transcriber on the Dell»,
  `ai/context/local-asr-research.md` (RTF 0.29–0.35, model size, RSS), `ai/context/dgo-herd.md` § Dell.
