# Local Hebrew speech-to-text — ivrit.ai ("אליעזר" / @BenYehudaBot) evaluated for apitools

Scope: add a **local** Hebrew transcription capability to `apps/apitools`, measured on the box that
runs this office. Written 2026-10-06 after a real benchmark on `computer_local-local`
(2 vCPU AMD EPYC 9354P, AVX-512+VNNI, 7.9 GB RAM, no GPU, no `/dev/dri`).

## 1. What the thing actually is

"אליעזר בן עזריה" is one project seen from two doors: **ivrit.ai**'s WhatsApp bot is named
**אליעזר**, and the same bot on Telegram is **@BenYehudaBot** (בן יהודה). It is a non-profit Israeli
project that built the largest Hebrew speech corpus (>22,000 h) and fine-tuned Whisper on it.

| Piece | What it is | License | Last activity |
|---|---|---|---|
| [ivrit-ai models](https://huggingface.co/ivrit-ai) | `whisper-large-v3-turbo[-ct2]`, `large-v3[-ct2]`, Yiddish variants | **apache-2.0** | turbo-ct2 2025-10-27 · turbo 2025-05-22 · yi 2026-02 |
| [ivrit-py](https://github.com/ivrit-ai/ivrit-py) (`pip install ivrit`) | wrapper: engines `faster-whisper`, `stable-ts`, `whisper-cpp`, `runpod`; file/URL/blob input, diarization | MIT | 0.2.7 — 2026-10-06 |
| [runpod-serverless](https://github.com/ivrit-ai/runpod-serverless) | ready template for a RunPod GPU endpoint | MIT | 2026-05-31 |
| [transcribe-service](https://github.com/ivrit-ai/transcribe-service) | the site transcribe.ivrit.ai (FastAPI, upload, editor, quota) | MIT | 2026-10-06 |
| [eliezer](https://github.com/ivrit-ai/eliezer) | the bot: hub + edges (`whatsapp_bot.py --local` runs faster-whisper on a local GPU) | MIT | 2026-10-05 |
| datasets (`audio-v2`, `eval-whatsapp`, `crowd-transcribe-v5`) | training/eval audio | "ivrit.ai license" — commercial AI training allowed | — |

Peer review: Interspeech 2025, *Building an Accurate Open-Source Hebrew ASR System through
Crowdsourcing* — 314 h crowd-transcribed, **up to 29 % fewer errors** than existing Whisper
solutions, notably verbatim output. There is **no public developer API**: transcribe.ivrit.ai is an
OAuth web app with a 420 min/week human quota, so it is not an integration surface. The ivrit.ai
route to a hosted API is "deploy our RunPod template" — their own number: **~$0.03 per transcribed
audio hour**.

Operational note: since **2026-10-01** they stopped delivering transcripts inside WhatsApp (WhatsApp
pricing) — delivery moved to their Communicator app or the Telegram bot. Recordings still go in over
WhatsApp.

## 2. What was measured, and how

`faster-whisper` + `ivrit-ai/whisper-large-v3-turbo-ct2`, `device=cpu`, `compute_type=int8`,
in a container capped at `--cpus 2 --memory 2400m`, audio = 10 public Hebrew clips
(`google/fleurs` config `he_il`, 5–16 s each, 84.5 s total). WER computed locally against the FLEURS
reference (punctuation stripped, whitespace tokenized).

| Measurement | Value |
|---|---|
| Model on disk (`model.bin` + tokenizer) | **1621.7 MB**; cold download over this host's link **27.6 s** |
| First load, model not in page cache | **57.9 s** |
| Load with the file in page cache | **10.4 s** (second instance in-process: 16.4 s) |
| Steady RSS while transcribing (int8) | **≈ 1.0–1.2 GB** |
| Container peak (load quantizes fp16→int8 in RAM) | **≈ 2.5 GB** |
| RTF — 2 threads, beam 5 (library default) | **0.29–0.35** (i.e. 3× slower than real time) |
| RTF — 2 threads, beam 1 | 0.40–0.41 |
| RTF — **1 thread, 1 CPU** (`--cpus 1`), beam 5 | **0.36** |
| Quality — FLEURS read speech, WER | mean **0.18–0.19**; two short clips **0.00** |
| Config sweep (beam 5 / +VAD,temp 0 / beam 1+VAD,temp 0) | WER **0.191 / 0.191 / 0.176** — the defaults are already fine; VAD/repetition knobs did **not** change the outcome on this set |

Practical translation for this box: **a 30-second voice note costs ≈ 75–100 s of one core**, and a
5-minute recording ≈ 14 min. Errors cluster in the *longest* clips (tail loss and one reordering,
e.g. "הפארק הלאומי קרוגר" resurfacing at the end of a 13 s clip), which is the classic Whisper
long-window behaviour and the reason a chunk-with-overlap pass is worth having.

**Caveat that must not be lost:** FLEURS is clean read speech. Real WhatsApp voice notes are noisy,
and every number above is from *this* host while the office was live (load ≈5.5 on 2 cores). Treat
the RTF as "what it costs on a busy 2-core box", not as a model benchmark.

## 3. What those numbers force

1. **Asynchronous, never a blocking request.** Between model load (10–58 s) and 3× real time, a
   synchronous HTTP call cannot answer inside any sane request budget. The gap today is a one-line
   refusal in `apps/chat/src/whatsapp/group_agent/group_agent.js:299` ("cannot transcribe audio") —
   the right replacement is "queued, here is the job id", with the transcript arriving later.
2. **One core is enough; two are barely better** (0.36 vs 0.29–0.35). Pin the transcriber to a
   single CPU so the office always keeps a core. This is a measured decision, not a guess.
3. **The peak is the load, not the run** (≈2.5 GB once vs ≈1.0–1.2 GB resident). On a box with
   1.2–1.8 GB free + swap, an unlucky cold load will thrash. Two ways out — both belong in the
   build: pre-quantize the model to int8 on disk (≈810 MB, no double-resident conversion), and/or
   keep the model warm during known busy windows instead of loading per job.
4. **Idle must be genuinely idle.** This deployment runs the `ci-small` profile
   (`host_mem: 7G`, `mem_overcommit: 5.5`, `host_cpus: 4`, `cpu_overcommit: 4.0`): declared caps on
   this box are already far above the machine, and services here *have* been OOM-killed before
   (`incoming-documents`, `drive`). A resident 1–2 GB transcriber would be the largest single
   discretionary consumer on the host.

## 4. The architecture

The office already has the exact pattern to copy: `apps/sites` ships **two** containers, and its
compose header states the rule — the renderer is split out because a render costs 400–700 MB and
"it is pointless to run when nothing is being scored". ASR is the same class of thing, one notch
heavier.

```
apps/apitools/
  docker-compose.yml        + service `apitools-asr`  (internal only: no traefik labels, no route)
  Dockerfile.asr            python:3.12-slim + ffmpeg/libopus, faster-whisper, model on a NAMED VOLUME
  asr/                      the worker: HTTP (queue, status, health) + one transcriber thread
  hooks/prepare             (existing verb, run by `bbox run`) — fetch/pin/verify the model once
  src/api/…                 apitools' own /transcribeVoiceNote → enqueue, proxy status
  app.json                  new capability `speech` (protocol, http://apitools:8080) with the ops
                            `transcribeVoiceNote`, `transcriptionStatus`
```

- **capability `speech`, ops `transcribeVoiceNote` / `transcriptionStatus` / (later) `getTranscript`.**
  Consumers (`chat`, `indox`, n8n) resolve it the way they resolve `ocr` today — nothing hardcodes a
  container name. `reconcile.py validate` will refuse an op that is declared and not served.
- **Internal-only service.** `apitools-asr` gets no router: the office talks to it through apitools
  (which is SSO'd at the edge, and whose `.localhost` twin was already fixed to carry SSO after the
  spoofed-Host incident). One public door, not two.
- **Model as a pinned artifact, not a runtime download.** A named volume (`apitools_asr_models`),
  populated by a `prepare` hook from a **pinned HF revision**, with a size/checksum check. Inference
  then needs no egress at all — same discipline as the Docker 28.5.2 pin.

## 5. Control and governance (שליטה ובקרה)

| Control | Shape |
|---|---|
| **Admission** | Bounded queue (depth ≤ 8) + **one** transcriber thread (`ASR_CONCURRENCY=1`), mirroring `SITES_RENDER_CONCURRENCY: 1`. Over the limit → `429` with `Retry-After`, never unbounded growth. |
| **Input caps** | Max audio seconds (600, the same cap Eliezer uses), max upload bytes, accepted formats; anything longer is refused with the number, not silently truncated. |
| **Deadline** | Per-job wall-clock cap + SIGKILL, poison-job protection, temp file removed on every exit path. |
| **Resource caps** | `deploy.resources.limits.cpus: '1'`, `memory: 2G`, `cpu_shares` below apitools/DB, `memswap_limit` set. G30 (`memory-budget-lint`) and G65 (`cpu-budget-lint`) **will sum these** against the profile — adding them means re-checking the `ci-small` envelope, and `perf-profile-apply` scales declared caps down to fit, so the declared number is a share of a small budget, not a reservation. |
| **Priority / windows** | Interactive voice notes bypass the batch queue; bulk/archive work is deferred to the quiet window (night) — one job at a time is cheap for the office at 03:00 and expensive at 11:00. |
| **Quota & accounting** | Per-caller minutes per period, debited from **audio seconds** (not wall time), refunded on failure — the token-bucket idea from their hub. Exposed on `/asr/status`: queue depth, minutes today, RTF EWMA, state (`idle|cold|loading|busy`), model revision. |
| **Truthful health** | `/healthz` must answer 200 while idle-and-unloaded (otherwise autoheal restarts a healthy worker); a load failure is a job failure with a named reason, and `loading` is visible so nobody diagnoses "slow" as "down". |
| **Privacy** | Audio is the client's data: content-hash filenames in the app's own volume, deleted after the job (or a TTL), transcripts never logged above DEBUG, no arbitrary-URL fetching at the API edge. |
| **Model version = a change with an eval** | The pinned HF revision lives in one place; a swap is accepted only against a **fixed eval set** (a frozen slice of `ivrit-ai/eval-whatsapp` + our own voice notes) with a recorded WER, the way the Docker pin is a decision rather than a drift. |

## 6. Efficiency when nothing is being transcribed

Layered, cheapest first — the first two are the whole answer on this box:

- **L0 — the web process never holds the model.** apitools (gunicorn, 4 workers) stays a thin
  client; only `apitools-asr` ever grows.
- **L1 — lazy load.** The model loads on the first job of a busy window, not at boot. Cost when the
  file is in page cache: ~10–16 s (measured).
- **L2 — idle unload.** After `ASR_IDLE_UNLOAD_SECONDS` (default 300) with no jobs, the worker drops
  the model, `gc.collect()`s and returns to a ~60 MB RSS. That is the state the `mem_overcommit`
  ratio in `perf-profiles.yml` already assumes — "services are not all hot at once".
- **L3 — the process/container asleep between bursts** is *not* an app's job here: it needs the
  engine socket, which is exactly what gate G32 (`engine-bypass-lint`) forbids apps to touch. If the
  office later wants true scale-to-zero it belongs to a platform mechanism (an enable/disable verb or
  a compose profile driven by `dc`), and it should be decided in `platform-base`, not smuggled into
  an app.
- **L4 — make each job cheaper before making more hardware.** int8 (note the trap: `ivrit`'s own
  default `compute_type` on CPU is **float32** — slower and 3× the RAM; the eliezer edge would hit
  that default on a CPU-only machine), a pre-quantized model on disk, one pinned core, VAD trim so
  silence is not transcribed, `beam_size=1` for interactive notes (measured 0.40 RTF vs 0.29, WER on
  the eval set unchanged), and batched inference only inside the night window (it multiplies RAM).
- **L5 — defer instead of thrash.** A cold load is ~10–58 s of pure waste; if the request is not
  interactive and the model is cold, batch it into the night window rather than paying a load per
  note.

## 7. Rollout, in phases (each ends with a real check)

1. **P1 — the container, offline.** `Dockerfile.asr` + model volume + `prepare` hook; a CLI that
   transcribes one file. Check: the measured RTF and RSS above reproduce on this host.
2. **P2 — the worker + queue.** HTTP surface (`enqueue`, `status`, `healthz`), caps and deadlines,
   idle unload. Check: kill -9 mid-job leaves no temp file and no stuck slot; a second job queues.
3. **P3 — apitools op + capability.** `speech` capability in `app.json`, `reconcile validate/plan`
   green, gates G30/G65/G31 (any new `APITOOLS_*` knob must be plumbed in compose) green.
4. **P4 — one real caller.** The chat voice-note path replaces the "cannot transcribe audio" line
   with an enqueue + a later answer; the message itself says it is queued.
5. **P5 — the eval harness.** A frozen set + recorded WER, so the next model swap (or a switch to
   the Yiddish/turbo variants) is measured, not felt.

## 8. Alternatives, and when they win

| Route | When it is the right answer |
|---|---|
| **This local CPU service** | Privacy, no external dependency, low volume (voice notes are minutes per day, not hours). Cost of the box is already paid. |
| **RunPod + ivrit's template** (their `ivrit` package, `engine="runpod"`) | Bursts of hours, or a deadline ("transcribe this 2-hour recording now"). ~$0.03 per audio hour ⇒ a 30 s note ≈ $0.00025. Needs a RunPod account + endpoint + key as a `connections` provider. |
| **A second machine** (the fleet in `computers`, or the office's portable box) | When ASR must not share a core with OCR at all. Same app, different host — this is why the capability indirection matters. |
| **`parakeet-tdt-0.6b-hebrew` / newer Hebrew ASR** | If CPU throughput becomes the binding constraint: 0.6 B parameters is roughly an order of magnitude cheaper to run than Whisper-large, at unverified quality. Belongs in the P5 eval, not in the first rollout. |

## 9. Not verified (do not claim these)

- Quality on **real WhatsApp voice notes** — the office's actual input. Everything here is FLEURS.
- Whether pre-quantizing to int8 on disk really removes the 2.5 GB load peak on this host (it should,
  mechanically — it has not been run here).
- Long-audio behaviour: >20 min files, chunking with overlap, diarization (the latter needs
  pyannote + torch: not feasible on this host).
- The `ci-small` numbers after G30/G65 are re-run with the new service declared.
