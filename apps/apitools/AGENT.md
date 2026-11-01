# Operating `apitools` — כלי מסמכים (documents, OCR, and the office's Hebrew speech-to-text)

Three capabilities live here. `ocr` and `ledger` serve the document pipeline; `speech` is the
office's transcriber (ivrit.ai's Hebrew Whisper, running on this machine — no cloud, no key).

Read `GET <endpoint>/manifest` for the live contract of each. The basics a caller must know:

## `speech` — תמלול עברית (Hebrew speech-to-text)

Two containers serve this app: the web container (`apitools:8080`, OCR + ledger) and
`apitools-asr:8987`, which owns the model. The capability's endpoint is the ASR one.

Two surfaces, one pipeline — the difference is only how the answer comes back:

```bash
# a voice note or any audio file (multipart) — short audio answers inline, long audio becomes a job
curl -s -X POST http://apitools-asr:8987/transcribe -F file=@note.ogg -F language=he -F response_format=json
curl -s -X POST http://apitools-asr:8987/v1/audio/transcriptions -F file=@note.ogg   # the standard (OpenAI) shape

# long media: ask for the job, then poll
curl -s -X POST 'http://apitools-asr:8987/v1/audio/transcriptions?async=1' -F file=@lesson.mp4
curl -s http://apitools-asr:8987/transcriptionStatus?id=tr_ab12cd34ef56
curl -s http://apitools-asr:8987/v1/audio/transcriptions/tr_ab12cd34ef56/vtt   # vtt|srt|txt|docx|verbose_json
curl -s http://apitools-asr:8987/speechHealth          # model state, queue depth, limits
```

- **Short vs long is decided by the audio's own duration** (`SPEECH_SYNC_MAX_SECONDS`, default 120 s)
  unless the caller passes `?async=1` or `Prefer: respond-async`. `json` returns exactly
  `{"text": …}`; `verbose_json` returns the canonical object (segments + per-word timings +
  confidence + revision).
- **The canonical object is the store; VTT/SRT/TXT/DOCX are views.** SRT is a one-way export
  (no speaker field, no styling) — never read it back as the transcript.
- **Measured on this host** (2 vCPU, no GPU, 2026-10-07): ~3× slower than real time for dense
  speech (RTF 0.29–0.35), about real time on an ordinary voice note; one job at a time; the model is
  released after 5 idle minutes and the next job pays 10–16 s to reload it (58 s if the file is not
  in the page cache). A 30-second voice note is ~20–40 s of work, so **never put this in a chat
  reply's critical path without saying it is queued**.
- **Jobs are records.** Each has `/data/jobs/<id>.json`; transcripts survive a restart, and a
  completed job can be re-rendered into another format without re-running the model. Uploads are
  content-addressed (the same file twice costs one copy) and pruned by TTL.
- **Traps:** one worker and a bounded queue of 8 — a full queue answers `429` with `Retry-After`,
  and that is the correct answer, not an error to retry in a tight loop. Duration is probed from the
  header *before* the work is queued, so an over-long file is refused with a number in it
  (`413`). Only multipart uploads or a `path` inside the service's own `/data` are accepted —
  **there is no URL input**, deliberately (no SSRF surface). Diarization is not available on this
  hardware (it needs pyannote + torch), so do not promise "who said what".
- **Live sessions (dictation).** `POST /voiceStart` → `{id}`, then one job per segment:
  `POST /voiceSegment?session=<id>` (multipart `file` + field `index`), `GET /voiceStatus?session=`
  for the growing text, `POST /voiceFinish?session=` for the accurate second pass over the whole
  recording, `POST /voiceCancel?session=`. The CLIENT cuts the segments — it is the only thing that
  knows where an utterance ends — and **30 seconds is the right size, measured**: Whisper pads every
  window to 30 s of mel frames, so 10 s segments ran at ~0.5× real time on this box against ~1.4×
  for 30 s ones. Expect the text to grow every 30–60 s, not instantly; a rolling 5-s window costs
  12–18 s per decode here, which is why sub-second captions are a GPU feature and not a setting.
  In the office UI this is the microphone button in the בינה composer (apps/bina-ds/plugins/voice).

## `ocr` — documents

`POST /documentOcr` (multipart `file`) returns a `file_id` (md5 of the content) plus the OCR JSON;
`POST /documentJsonQuery` answers position-based questions over that result. Google Vision is the
engine unless `OCR_ENGINE=local`, and the `google-vision-key` connection probe is this app's
`/health`. Depth: `apps/apitools/README.md`. Traps worth repeating: a query is bounded by
`APITOOLS_QUERY_SOFT_TIMEOUT` and a "find option" over a huge candidate list is what made that a
real limit; the bulkhead's slots are file locks, so two containers have two pools.

## `ledger` — פנקס המסמכים

`business`, `customers`, `items`, `documents`, `issue`, `download` over the office's Postgres
(`supabase-db`, tables declared in `app.json` under `data.sql`). Money-moving calls are the ones to
be careful with; everything else is read-mostly.
