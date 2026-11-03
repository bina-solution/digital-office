---
id: speech.status
title: The office's transcriber — is a model ready, and what waits in its queue
title_he: מצב התמלול של הלשכה
when:
  - מה מצב התמלול
  - התמלול עובד
  - תמלולים בתור
  - מודל התמלול
  - speech status
  - transcription status
  - transcription working
inputs: {}
reaches_people: false
link: false
check: 'one line per model (ivrit, whisper) with its state, then the jobs waiting and running — or that the transcriber, or the check itself, did not answer'
---
1. `./bbox apitools speech-health` — the speech service's own health (asr/app.py), read only. It runs inside the apitools web container.
2. A line starting `apitools:` or a non-zero exit: say the check could not run (the web container or the transcriber did not answer), never "idle". `status: ok` only means the process answers, not that a model works.
3. One line per entry of `models`: its name and `state` — `ready` (in memory now), `cached` (on disk; it loads on the next job that asks for THAT model — one is in memory at a time, so whisper `cached` beside ivrit `ready` is normal), `absent` (not downloaded: the first job that asks for it downloads it), `downloading`, `loading`, or `error` with `last_error` as it is — and "busy" when `busy` is true.
4. Then `jobs`: waiting is `counts.queued`, and `current` names a job running now. Jobs waiting with no `current` is a stalled worker: say so. `counts` is every job on record by status (kept 30 days, across restarts); `counts.error` includes jobs a restart interrupted and submissions refused by a full queue, and a `ready` model with errors rising is not working. `./bbox apitools speech-jobs` names the recent ones.
5. This only reads. Asked to transcribe, cancel, load or download, say that this only read and nothing was done.
