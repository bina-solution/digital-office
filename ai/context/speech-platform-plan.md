# Speech in the office — API standards, the contract we serve, and the end-to-end plan

Companion to [local-asr-research.md](local-asr-research.md) (the measurement/feasibility pass: ivrit.ai
"אליעזר"/@BenYehudaBot, model sizes, RTF, RAM, idle-unload design). This document is the *product*
half: what a standard transcription surface looks like in 2026, what the office will expose as a
capability, and how a recording button in בינה reaches it end to end — short notes, long recordings,
video, live dictation, subtitles.

Written 2026-10-07. Everything marked **[measured]** was run on `computer_local-local` (2 vCPU,
no GPU) in this session; **[doc]** means it comes from a vendor/spec page (link given);
**[unverified]** means nobody has confirmed it here.

---

## 0. The decisions this document argues for

| # | Decision | Why |
|---|---|---|
| D1 | One capability, `speech`, served by apitools; engine in a sidecar container `apitools-asr` | Consumers (`bina`, `indox`, `chat`, n8n, `drive`) resolve it like `ocr`; no app reaches into another's volume |
| D2 | Two surfaces: **job API** (upload/URL → id → poll/webhook → result) and **session API** (WebSocket, partial/final) | Every commercial vendor splits exactly this way; the split is what makes 20-hour files and live mic the same product |
| D3 | The job API is **OpenAI-compatible** (`POST /v1/audio/transcriptions` + `…/translations`, formats json/text/srt/vtt/verbose_json/diarized_json) and the session API speaks a **documented subset of the OpenAI Realtime transcription events** | Drop-in for existing clients and skills; a later move to a cloud model (or an inbound OpenAI-compatible client) costs nothing |
| D4 | Canonical result is a **format-independent object** (segments + words + speaker + confidence + revision state); VTT/SRT/TXT/DOCX are rendered from it | SRT has no spec and is lossy; VTT is the standard; editing and live revisions need the object |
| D5 | **Live is a policy, not a promise.** Naming/behaviour must reflect what the box can do: dictation while speaking = transcript grows every ~5–15 s; *true* <1 s captions need a GPU | **[measured]** one 6 s rolling-window decode costs 12–18 s of this CPU (§2) |
| D6 | Every long job is **resumable and bounded**: chunked (tus-shaped) upload, duration/size caps checked *before* download, per-class queue with fixed parallelism, night window for bulk | The failure mode of a transcription service is not bad text, it is an OOM at 03:00 |
| D7 | A `transcription` **skill** teaches the agent to listen; the UI puts the mic in the composer | The owner's ask: "the agent knows to use a transcription skill to listen" |

---

## 1. What "standard" means — the convergent contract

Five vendors' APIs were read this session (Deepgram, AssemblyAI, Google STT v2, AWS Transcribe,
Azure AI Speech). They disagree on transport and vocabulary and agree on ten concepts — that list
*is* the standard to implement:

1. **Job/request id** — a durable handle (`request_id`, transcript `id`, LRO `name`, `TranscriptionJobName`) you poll, retry, cancel.
2. **Submit** — synchronous for short audio, id-returning for long.
3. **Poll *or* webhook** — status enum (`queued|processing|completed|error`, `QUEUED|IN_PROGRESS|COMPLETED|FAILED`), never a promise.
4. **Partial ("interim") result** — provisional text that *will* change (`is_final:false`, `Turn{end_of_turn:false}`, `IsPartial:true`, `Recognizing`).
5. **Final result** — the committed segment (`is_final:true`, `end_of_turn:true` + `turn_is_formatted:true`, `Recognized`).
6. **Endpointing / turn detection** — a configurable silence/confidence rule closing an utterance (`endpointing`, `min_turn_silence`/`max_turn_silence`, `SegmentationSilenceTimeoutMs`, server VAD).
7. **Word timing + confidence**, plus a *display* form of each word (punctuated/ITN).
8. **Diarization** — speaker on words and on utterances; always capped and usually billed extra.
9. **Format allow-list in** (wav/mp3/m4a/flac/ogg-opus/webm…) **and subtitle/segment export out** (SRT, VTT, JSON).
10. **Quota & limits** — max size/duration, concurrency, and the keep-alive/reconnect rule that keeps a long-lived stream alive and billable.

Vendor-specific, i.e. *not* standard: direct binary upload (Deepgram/AssemblyAI/Azure yes; AWS S3-only, Google GCS-only) and a resumable stream (AWS restarts a new session, Google caps a stream at 5 minutes, AssemblyAI keys off `expires_at`).

### 1a. The OpenAI surface, precisely (because D3 adopts it)

- `POST /v1/audio/transcriptions` — `multipart/form-data`; `file` (required), `model`, `language` **or** `languages[]`, `prompt`, `response_format` ∈ {json, text, srt, verbose_json, vtt, diarized_json}, `temperature`, `timestamp_granularities[]` ∈ {word, segment} (requires `verbose_json`), `chunking_strategy` (`auto` | server-VAD shape), `include[]` ∈ {logprobs}, `stream` (SSE), `keywords[]`, `known_speaker_names[]`/`known_speaker_references[]`.
  Responses: `verbose_json` = `{task, language, duration, text, segments[{id:number, seek, start, end, text, tokens[], temperature, avg_logprob, compression_ratio, no_speech_prob}], words[{word, start, end}], usage}`; `diarized_json` = `{task, duration, text, segments[{type:"transcript.text.segment", id:string, start, end, text, speaker}]}` with the top-level text speaker-prefixed. Trap: `segment.id` is a **number** in `verbose_json` and a **string** in `diarized_json`. SSE events are `transcript.text.delta` / `transcript.text.done`.
- `POST /v1/audio/translations` — same shape, output always English, `whisper-1` only, no diarization/streaming/timestamps.
- **Realtime (session) surface**: `wss://…/v1/realtime`, and the *current* transcription session is `session.update` with `session.type:"transcription"` (the old `?intent=transcription` / `transcription_session.update` pair is legacy Beta and no longer documented). Audio input is **PCM16 mono @24 kHz** (or G.711 μ-law/A-law) — *not* 48 kHz; ≤15 MiB per `input_audio_buffer.append`. Client events: `session.update`, `input_audio_buffer.append|commit|clear`. Server events that matter: `session.created|updated`, `input_audio_buffer.committed|cleared`, `input_audio_buffer.speech_started|speech_stopped`, and the transcript pair `conversation.item.input_audio_transcription.delta` (interim, append-only deltas) → `.completed` (final `transcript` for that `item_id`). Reconciliation is **by `item_id`**, because completion events of different turns are explicitly not ordered. Errors arrive as an `error` event and **do not close the socket**.
- Limits: **25 MB** per file for the REST transcriptions endpoint; no documented duration cap. Formats: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm. No published numeric rate limits.
  Sources: [speech-to-text guide](https://developers.openai.com/api/docs/guides/speech-to-text.md), [transcriptions reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create.md), [realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription.md), [realtime client events](https://developers.openai.com/api/reference/resources/realtime/client-events.md), [openai-python typedicts](https://raw.githubusercontent.com/openai/openai-python/main/src/openai/types/audio/transcription_create_params.py).

### 1b. Formal/vendor standards worth holding ourselves to

| Concern | Standard | Note |
|---|---|---|
| Captions | **WebVTT** ([W3C CRD](https://www.w3.org/TR/webvtt1/)) | `HH:MM:SS.mmm --> …`, cue settings, `<v Speaker>`, NOTE/STYLE blocks |
| Legacy captions | SRT | **no spec**, comma decimals, no speaker/styling → a one-way export, never the store |
| Broadcast interchange | IMSC 1.2 / TTML2 | only if a broadcaster ever asks |
| Capture | [Media Capture and Streams](https://www.w3.org/TR/mediacapture-streams/) + [MediaStream Recording](https://w3c.github.io/mediacapture-record/) | `getUserMedia` (secure context), `MediaRecorder(timeslice)` — chunk N alone is *not* playable, only the concatenation is; `isTypeSupported()` deprecated → `mediaCapabilities` |
| Raw audio | `AudioWorklet` | 16 kHz mono PCM16 LE, 100 ms = 3200 bytes; `ScriptProcessorNode` is deprecated and never fires on mobile Safari |
| Transport | [WebSocket RFC 6455](https://www.rfc-editor.org/rfc/rfc6455) | binary = audio, text = control, audio on its own socket; **no backpressure** — gate on `bufferedAmount` |
| Resumable upload | [tus 1.0](https://tus.io/protocols/resumable-upload) / S3 multipart | 412 on version mismatch; S3: ≤10 000 parts, 5 MiB–5 GiB each |
| Long-form sources | [HLS RFC 8216](https://datatracker.ietf.org/doc/html/rfc8216), RTSP/RTMP, [yt-dlp](https://github.com/yt-dlp/yt-dlp) | what "complete" means for ingestion |
| VAD | [Silero VAD](https://github.com/snakers4/silero-vad) | ~2 MB, <1 ms per 30 ms chunk, runs server-side *and* in-browser (ONNX Web) |

Latency tiers in the industry are **product tiers, not standards**: <300 ms = voice-agent barge-in,
~1 s = live captions, 2–3.5 s = conference readability ([AA streaming benchmark](https://artificialanalysis.ai/));
`whisper_streaming`'s LocalAgreement-2 reports 3.3 s on unsegmented long-form
([ufal/whisper_streaming](https://github.com/ufal/whisper_streaming)). Non-inference floors dominate
what a user feels: `getUserMedia` cold open ~2 s, model cold load 10–58 s **[measured]**.

---

## 2. What this box can actually do — measured

From [local-asr-research.md](local-asr-research.md), plus a live-loop experiment run for this document:

| Shape | Numbers | Verdict |
|---|---|---|
| Batch, dense Hebrew speech, 2 threads, beam 5 | RTF **0.29–0.35** (3× slower than real time) | usable for queued work |
| Batch, one thread/one CPU | RTF **0.36** | **pin ASR to one core**; 2 cores add ~20% |
| Batch, a real 32 s WhatsApp note | 32.8 s (RTF 0.97) / 18.8 s with VAD (RTF 1.69) | real notes are faster than the worst case |
| Model load | 57.9 s cold · 10–16 s warm · RSS 1.0 GB · peak ≈2.5 GB | lazy-load + idle unload; pre-quantized model on disk |
| **Live loop (6 s window re-decoded every 2 s, beam 1)** | **12–18 s per decode; cpu_per_stream_second 5.8** | **not sustainable — live captions with this model on this CPU are impossible** |

Why the live loop is so bad, and why it is not a tuning bug: Whisper pads every window to 30 s of mel
frames, so a 6 s window costs almost the same as a 30 s one. Windowed re-decoding pays the encoder
price over and over; only VAD-chunked, *long* segments are efficient. **Consequence for the design:**
on CPU-only, "live" means *dictation* — capture locally, cut at speech boundaries, transcribe 20–30 s
segments in a pipeline, and let the transcript grow every ~5–15 s. True low-latency captions are a
GPU feature (RunPod, ~$0.03/audio-hour per ivrit.ai's own number) or a small-model feature (a model
that does not exist yet for Hebrew at ivrit's quality). This is the main honest constraint in the plan.

---

## 3. The contract the office serves

### 3.1 Capability `speech` (declared in `apps/apitools/app.json`)

```
name: speech  ·  type: protocol  ·  endpoint http://apitools:8080
ops (job):     transcribe · transcriptionStatus · transcriptionResult · exportTranscript
ops (media):   extractAudio            (video → 16 kHz mono, kept for re-runs)
ops (live):    liveSession             (WebSocket, advertised as a passthrough path)
ops (admin):   speechHealth · speechModels
```

Internal-only sidecar `apitools-asr` (own memory/CPU caps, no router, no public door), exactly as
`apps/sites` splits off `sites-render`. The public surface stays apitools' SSO'd door, plus one
**websocket passthrough** on the console host for live sessions (`module.passthrough[].transport:
"websocket"` — the mechanism `bina-ds` already uses for `/api`, see `platform/schema/app.schema.json`).

### 3.2 The two protocols

**Job protocol** (long recordings, video, batch):

```
POST /v1/audio/transcriptions        # OpenAI-compatible; multipart or {"url": "…"} / {"drive_id": "…"}
  → 202 {id, status:"queued", position, eta_seconds}      # when duration > ~60 s or queue non-empty
  → 200 <transcript>                                      # only for short clips, synchronously
GET  /v1/audio/transcriptions/{id}    # {status, progress, queue_position, result?, error?}
GET  …/{id}/vtt | /srt | /txt | /json # rendered exports
POST …/{id}/cancel
POST /v1/audio/upload                 # tus-shaped: POST create → PATCH chunks → complete (50 MB chunks)
```
Statuses are the convergent enum: `queued | processing | completed | error`, with `error.code` a
stable string (`too_long`, `unsupported_format`, `queue_full`, `model_unavailable`, …).

**Session protocol** (live/dictation), modeled on the Realtime vocabulary so a client that speaks one
can speak the other:

```
→ {type:"session.start", language:"he", model:"ivrit-turbo", mode:"dictation"|"captions", interim:true}
← {type:"session.created", session_id, audio:{format:"pcm16/16000/mono", chunk_ms:100}}
→ binary: PCM16 mono 16 kHz frames (100 ms), text: {type:"audio.commit"} | {type:"audio.clear"}
← {type:"speech.started"|"speech.stopped", at}
← {type:"transcript.delta",  segment_id, text}     # append-only interim for the OPEN segment
← {type:"transcript.segment", segment_id, start, end, text, is_final:true}
← {type:"transcript.updated", segment_id, …}       # the final re-pass REPLACED an earlier segment
← {type:"session.ended", usage:{audio_seconds, compute_seconds}, transcript_url}
← {type:"error", code, message, fatal:false}       # a bad event never closes the socket
```
Two rules that are the whole point of the protocol: **interim text is append-only and may be
superseded** (never dedupe by substring), and **every result carries a `segment_id` + a revision
state** — that is what makes "editing while speaking" possible.

### 3.3 The canonical object and its exports

```jsonc
{"id":"tr_…","created":"…","source":{"kind":"upload|url|drive|mic","name":"…","duration_s":31.98},
 "language":"he","model":{"name":"ivrit-ai/whisper-large-v3-turbo-ct2","revision":"<hf sha>","compute":"int8"},
 "segments":[{"id":"s1","start":0.0,"end":4.06,"text":"…","speaker":"A","confidence":0.91,
              "words":[{"w":"טוב","start":0.0,"end":0.4,"confidence":0.9}],"revision":2}],
 "revisions":[{"at":"…","by":"user|model:repass","segments":["s1"]}],
 "usage":{"audio_seconds":31.98,"compute_seconds":32.8,"rtf":0.97}}
```
Exports: `vtt`, `srt`, `txt`, `json`, `docx`, and a **speaker-prefixed plain text**. VTT from the
object, SRT as a lossy render (SRT has no speaker/styling by construction), line-breaking per the
[Netflix style guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)
(≤2 lines, 20-frame minimum, no orphan conjunctions).

---

## 4. End-to-end flows

**F1 — a voice note the owner sends the agent** (today: `apps/chat/.../group_agent.js:299` refuses).
attach audio in בינה → the harness stores it as a session attachment (`bbox agent upload` → receipt →
`attachments/v1/files/<aa>/<sha>/…`) → the agent's `transcription` skill calls `transcribe` with that
path → job runs on `apitools-asr` (one core, queued) → the transcript is posted back in the chat as a
**deliverable file** plus an inline quote. No browser audio API involved; this is the cheapest path and
should be P1.

**F2 — a long recording or a video** (interview, lesson, meeting).
`drive` holds the media (ops `upload`/`download`) → `POST /v1/audio/transcriptions {drive_id}` →
`extractAudio` (ffmpeg → 16 kHz mono FLAC; the intermediate is kept so a later re-run with a better
model costs no decode) → VAD segmentation into ≤30 s windows with ~0.2 s pad, `condition_on_previous_text=false`
→ transcribe in the long queue (one at a time) → stitch on word timestamps → canonical object →
`vtt`/`srt`/`docx` next to the file in drive, and a notification when done. Caps checked **before**
download: duration ≤ N hours, size ≤ 3 GB (ivrit's own product limits), else refuse with the number.

**F3 — live dictation inside the chat** (the owner's ask).
Mic button in the composer (`conversation.input.right` slot) → `AudioWorklet` resamples to 16 kHz mono
PCM (worklet loaded from a Blob URL, so no new static route in the harness) → own WebSocket
(`/api/voice/ws`, binary PCM + text control) → server-side Silero VAD cuts on silence → each 20–30 s
segment is transcribed as a job and pushed back as `transcript.segment` → the composer shows the
**growing, editable** transcript; the owner can fix words while the next segment is still decoding →
on Stop, a final pass re-transcribes the whole utterance (word timestamps, punctuation,
`condition_on_previous_text=false`) and emits `transcript.updated` for any segment it changed → "send
to agent" uses the edited text. Expected cadence on this box: first text after ~10–30 s, then every
5–15 s; **not** sub-second captions (§2).

**F4 — incoming voice notes in INDOX.** Same job API, called by n8n/indox when a WhatsApp voice note
arrives on a supplier thread: transcript attached to the incoming document instead of a dead end.
This is where the office's real volume is, and where the night window / quota policy earns its keep.

**F5 — subtitles for the office's own content** (`sites` videos, `drive` films): F2 + VTT export, and
optionally burn-in with `ffmpeg -vf subtitles=` (careful: the filter re-opens the file, so `-ss` needs
`-copyts` and a second `-ss`).

---

## 5. בינה: the button, the skill, and editing-while-live

- **Where the mic goes.** A new client plugin in `apps/bina-ds/plugins/` (the same shape as
  `brand-bina/lib/client.js`: a `window.__ModuleLoader__.load` closure factory that registers into
  host slots). The composer exposes `conversation.input.left`, `conversation.input.right`,
  `conversation.input.overlay` and `conversation.composer.dock` — the button registers into
  `conversation.input.right`; the live transcript panel into `conversation.input.overlay`; a level
  meter can reuse the same PCM stream.
- **The editing model** (what "עריכה תוך כדי" means concretely): a segment has a state
  `interim → committed → user-edited → model-revised`. Model revisions **never overwrite a
  user-edited segment** — they arrive as a *suggestion* on the same segment id, and the UI shows a
  diff. That single rule is what keeps a live transcript trustworthy; it is also why the canonical
  object carries `revision` per segment.
- **The `transcription` skill** — a new directory in the preset:
  `apps/bina-ds/harness/profile/agent-presets/azaria/skills/transcription/SKILL.md` (skills are
  discovered from `skills/` via `customSkillDirs` in `agent.cordis.yml`, so nothing else changes).
  It teaches: how to call the `speech` capability (job vs session), the caps, how to hand a long
  transcript back (a file + a summary, not a wall of text), how to search a transcript, when to
  re-run the final pass, and that a voice note is content to *quote*, not to paraphrase.
- **A recording affordance in the agent's own reach**: `bbox agent` already has `upload`; the skill
  documents the flow "audio arrives as an attachment → transcribe it → answer from the transcript",
  which is exactly what the owner demonstrated with the WhatsApp note at the start of this thread.

---

## 6. Governance (extends §5 of the measurement doc)

| Control | Shape |
|---|---|
| Queues | two classes with fixed parallelism, ivrit-style: `short ≤20 min` (1 parallel / 8 queued), `long >20 min` (1 / 4). Live sessions are **not** queued — they get the transcriber slot immediately, and a batch job yields (priority) |
| Caps | max duration (configurable, default 4 h), max size (3 GB), duration probed with `ffprobe` **before** download; media ≤600 s for the mic path |
| Upload | tus-shaped: 50 MB chunks, `Upload-Offset` resumable, expiry; no arbitrary-URL fetch at the edge (SSRF: block link-local/RFC1918, the trap `murmurai` documents) |
| Resources | `cpus: '1'`, `memory: 2G`, `cpu_shares` below apitools/DB; G30/G65 sum the caps against the `ci-small` profile |
| Idle | lazy load, unload after 300 s idle (measured 10–16 s to reload warm), pre-quantized int8 on disk so a cold load is not 2.5 GB of peak |
| Accounting | debit **audio seconds** per caller, refund on failure; `/speech/status` publishes queue depth, minutes today, RTF EWMA, state `idle|cold|loading|busy`, model revision |
| Windows | bulk (video, YouTube, >1 h) runs in the night window; interactive voice notes always jump the queue |
| Privacy | files content-hashed, deleted after TTL; transcripts never logged above DEBUG; the audio never leaves the office network |

---

## 7. Rollout

| Phase | Deliverable | Acceptance (a real check, not a demo) |
|---|---|---|
| P1 | `apitools-asr` container + model volume + `prepare` hook; **F1** (attachment → transcript) and a `transcription` skill | the WhatsApp note transcribed end-to-end through the capability, not by hand; RTF/RSS reproduce §2 |
| P2 | job protocol + canonical object + `vtt/srt/txt` exports; queues, caps, idle unload | a 1 h file and a 200 MB video transcribe unattended; kill -9 mid-job leaves no temp file and no stuck slot |
| P3 | `speech` capability in `app.json`; apitools endpoints; passthrough declared | `reconcile validate/plan` green; gates G30/G65/G31 green; `GET <endpoint>/manifest` lists the ops |
| P4 | mic button + live session in בינה; edit-while-live; final re-pass on stop | 3 minutes of speech dictated in the chat, edited mid-flight, and the final pass replaces only unedited segments |
| P5 | **F2/F4**: video → VTT into `drive`; INDOX voice notes | a real video gets subtitles next to it; an INDOX voice note stops being a dead end |
| P6 (optional) | promote to its own app (`apps/speech`) with a transcripts screen, if it grows a store and a UI | only if the list/edit/export surface outgrows the chat |

---

## 8. Unverified / must be checked before promising

- **Live captions at <1 s on this host** — measured *against* (§2). Needs RunPod GPU or a smaller Hebrew model.
- Whether `AudioWorklet` from a Blob URL is accepted by the harness's CSP/served origin (P4 spike, 1 hour).
- The 1–2 s overlap/stitch heuristic for long windows (industry practice, no normative spec).
- Opus as an intermediate for the office's own audio (WER cost unmeasured; FLAC is the safe default).
- Numeric pricing for Deepgram/Google/AWS/Azure (their pricing pages are JS-rendered and unreadable to a text fetcher) — only AssemblyAI ($0.15–0.21/audio-hour pre-recorded, $0.15–0.45/session-hour streaming) and ivrit.ai's RunPod figure (~$0.03/audio-hour) are verified.

---

## P1 — landed 2026-10-07 (measured, not estimated)

What exists now: the `speech` capability in `apps/apitools/app.json` (`http://apitools-asr:8987`),
the service itself (`apps/apitools/asr/`, `Dockerfile.asr`, its own service in the app's compose with
`cpus: 1` / `memory: 2.5G` / `cpu_shares: 256`, no traefik labels), the app's own brief
(`apps/apitools/AGENT.md`, now rendered into the agent registry), and the agent skill
(`apps/bina-ds/…/skills/transcription/SKILL.md`).

End-to-end proof — the office's own WhatsApp note (31.82 s, Opus mono 48 kHz) transcribed through the
capability, not by hand:

| Step | Measured |
|---|---|
| Model download, pinned revision, once | **19.1 s** (1 621 669 451 bytes) |
| Load, page-cache warm, `int8`, 1 thread | **5.5 s** |
| Inference (−→ sync answer) | **23–42 s** (`rtf 0.75–1.4`, varies with how busy the box is) |
| Resident with the model | **1.11 GiB** |
| cgroup peak during a job (fp16+int8 both live while quantising) | **1.94 GiB** |
| Idle after release (300 s) | **53 MB**, `/healthz` still 200, container not restarted |
| Whole first request, cold container | 48.5 s wall |

Two findings that changed the code rather than the document:

* **`vad_filter=True` costs real words.** On this note it removed 7.2 s of audio and with it the
  trailing "בואו!" (`vad=false` transcribed it). The default is therefore **off**; `?vad=true` is the
  opt-in for long recordings, where trimming silence is worth more than a trailing interjection.
* **The 2 GiB cap had 68 MB of headroom** (peak 1.94 GiB). Raised to 2.5G, with the measurement in
  the compose comment. Pre-quantising the model to int8 on disk — P2 — removes the double copy and
  lets it come back down.

Open, and not mine to decide alone: `.generated/cpu-budget.yml` is stale (`perf-profile-apply` has
not been re-run), so this new service is currently the **only** container whose declared CPU cap is
not scaled by the budget overlay. Gates that already failed before this change and still do:
`image-pin-lint` (four apps on a floating `:latest`), `memory-budget-lint` G30 (≈7 GiB over before,
9.1 GiB after), `cpu-budget-lint` G65 (21.35 → 22.35 vCPU over), `app-coupling-lint` G33 (8
chassis→app references in `platform-base/`). Everything else in the app gate set passes:
compile G12, healthcheck G18, capability-use G25, data-volumes G26, compose-invocation G7,
profile-passthrough G31, registry-drift G8, engine-bypass G32, layering, theme-token.


---

## P4 — dictation landed 2026-10-07 (`apps/bina-ds/plugins/voice`)

The owner asked for a recording button in בינה and live transcription that can be edited while it runs.
What exists now:

* **`apitools-asr` live sessions** — `voiceStart` / `voiceSegment` / `voiceStatus` / `voiceFinish` /
  `voiceCancel` (declared as `optional_ops` of the `speech` capability). A session is a record, and
  each segment is an ordinary job: the bounded queue, the single worker, the caps and the restart
  safety are inherited, not rebuilt. `finish` joins the segments (decoded and re-encoded to one
  16 kHz mono WAV — WebM/Opus segments are separate containers and cannot be concatenated by bytes)
  and runs the accurate second pass.
* **The browser cuts the audio, not the server**, because only the browser knows where an utterance
  ends. MediaRecorder is restarted per segment: the spec is explicit that `timeslice` chunks need not
  be individually playable, so they cannot be posted piecemeal.
* **The relay is a harness plugin**, not a new edge route: `plugins/voice` registers exact
  `/api/voice/*` Fetch routes (`ctx.connection.fetch.register`) on the harness's own `/api` handler —
  the origin the browser is already authenticated against — and forwards to `apitools-asr`. The
  browser never sees a second origin, a CORS preflight or a new credential.
* **Sending is the harness's own composer**: `conversation.input.shell(id).setDraft(text)` +
  `submit("queue")` is what pressing Enter does; the plugin falls back to `session/prompt` over the
  action token when that service is not reachable.

Measured while building it (all on the office box):

| Thing | Result |
|---|---|
| 10.6 s segments (3 of them) | **19–22.5 s per segment** → RTF ≈ 0.5 |
| the same audio as one 31.8 s recording | **23–40 s** → RTF ≈ 0.8–1.4 |
| why | Whisper pads every window to 30 s of mel frames, so a short segment pays the encoder for audio it does not have — **the segment length is a throughput decision, and 30 s is the right one** |
| the accurate pass (`finish`) | RTF ≈ 0.8 on the joined file |

Traps found by running it in a real browser (chromium + `--use-file-for-fake-audio-capture`, so the
"microphone" is the office's own voice note):

* **A client plugin's registered id must equal its package name.** A mismatch is not a warning: the
  entry fails to import and the whole בינה UI renders "Failed to load plugins" — the office agent
  stops rendering because of a dictation button. `apply()` is therefore wrapped in try/catch, so a
  later change can only cost the button.
* A **list** slot registration needs `{ id, name }`; without the id it throws
  (`list slot "conversation.input.right" requires options.id`).
* The plugin packages must be installed by pnpm into the profile's tree — a hand-made symlink that
  points outside it is refused by the static handler (404), and the entry then fails to import.
* **The conversation id and the live session id are two different things.** The first version used
  one ref for both: every segment POST and every poll went to
  `/v1/voice/sessions/<conversation-id>/…` and 404'd, and the panel stayed empty while the UI looked
  perfectly healthy. A live session is now opened per recording (`POST /api/voice/session`) and kept
  in its own ref.
* A fresh profile shows a **developer-preview modal** that swallows the first click; a browser test
  must dismiss it first (the office's own profile has already seen it).

**Rejected and rebuilt (owner, same day).** The first UI was a floating panel of my own design, and on
the owner's phone in the dark theme it rendered as a white card with white-on-white button labels
covering the conversation. The mistake was structural, not cosmetic: it invented a surface instead of
using the one the harness already has. The rewrite draws **no overlay at all** —

* the transcript is written into the **composer draft** (`conversation.input.shell(id).setDraft`), so
  it appears where the owner types, is editable, and is sent with the harness's own send button;
* the only chrome added is a 32 px microphone in the composer's trailing row and **one caption line**
  inside the composer card (`conversation.input.overlay` — *not* `composer.dock`, which only renders
  in the composer variant and therefore never appeared on the blank-session hero), painted entirely
  from the harness's own `--dsw-alias-*` tokens so both themes come from the harness;
* the draft is only overwritten while it is empty or still exactly what we last wrote — the moment the
  owner types, the strip offers "הוסף לתיבה" instead of clobbering their words;
* the status line clears itself once the queue drains — chrome, not history.

**Verified end to end**, in a throwaway harness built from this image and driven by headless
chromium whose "microphone" is a 16 kHz WAV of the office's own voice note, **at a phone viewport in
the dark theme** (the owner's own conditions)
(`plugins/voice/tools/verify-voice.cjs`): the mic button renders in the composer, recording starts,
the segment is uploaded, the panel shows 192 characters of Hebrew produced by the model, and
"שלח לבינה" lands the same text in the conversation — with zero console errors. The server side of the
same flow was measured separately: a live session with three 10.6 s segments, each 19–22.5 s of
inference, and `finish` joining them into one 31.8 s WAV and re-transcribing it accurately.


---

## The self-update that never landed (2026-10-07, found the same evening)

The redesign above was built, rebuilt into an image and handed to `bina-ds-self-update` — twice — and
the office kept running the OLD image, so the owner kept seeing the thing he had rejected. The log
told the story:

```
15:52:47 handed off: 'up ' of bina-ds to bina-ds-self-update (previous image 94fc97d7fed1)
15:53:09 waiting for a quiet moment before restarting bina-ds: 1 agent command(s) running
… every 10 minutes for an hour …
16:53:17 office still busy after 3600s (1 agent command(s) running) — applying the update now
16:53:27 bina-ds: an update of bina-ds is already in progress (container bina-ds-self-update)
```

`busy_reason()` counted every process in the container whose `comm` was not `node`/`MainThread` as "an
agent command" — and since `init: true` was added to this app's compose (2026-09-30, so `docker-init`
reaps orphaned agent processes), **PID 1 has been counted too**. One permanent false positive:

* the office could never look quiet, so every hand-off waited the full `MAX_WAIT` (60 min);
* two hand-offs an hour apart then collided on the helper container, and the second one returned
  "already in progress" — a race that reports success-looking output while changing nothing;
* the practical effect is what the owner experienced: an update that appears to be scheduled and never
  arrives.

The fix is one `awk` clause (`$1!=1 && $2!="docker-init"`) with the measurement in the comment. Worth
generalising: **a "wait until it is quiet" gate must name what quiet means, and a container's own init
process is never work.** Silent-by-construction gates like this one fail in the direction of "nothing
happens", which is indistinguishable from "no news".
