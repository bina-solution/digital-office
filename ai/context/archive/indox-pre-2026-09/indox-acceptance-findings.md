# INDOX 150-doc fresh-start acceptance — findings & fix plan

Goal: fresh reset → 30 docs × 5 sync registries (=150 source files) all COMPLETED within **20 min**,
**100%** local extraction (verified vs AI), all BS lines opened+completed, system at rest, smooth+stable.

## Harness (built, reusable)
- `scripts/acceptance-run.sh <seed|clear|reset|trigger|measure|full> [N]` — seed 30×5, clear table+locks
  (no re-queue of accumulated), trigger scanner, scorecard.
- `scripts/_inject_gmail_direct.py --doc/--bs/--link N` — gmail seeder (doc=DOC_TO_SYNC, bs=BS_TO_SYNC,
  link=DOC_LINK_TO_SYNC w/ pdfsrv PDF URL). Drive via `highload-inject.py --drive-inv/--drive-bs N`.
- `scripts/acceptance-measure.py` — scorecard: per-source done/total, extraction (SELECTED_* non-null +
  local-vs-AI), BS lines, rest. NOTE: amount lives in `SELECTED_DOC_AMOUNT` (not TOTAL_AMOUNT);
  `ERROR` is a non-fatal log, not a failure flag.
- `pdfsrv` container (python http.server on traefik-network, serves data-set-2/invoice/files) for gmail-link.

## Run #1 result (seed 150 → clear → trigger)
~93% complete (878/949 rows; 150 source explode to ~949 incl ~820 BS line-rows), **stable (0 OOM,
~1% transient gmail-throttle errors)**, extraction ~100% vs AI on completed, BS docs+lines healthy.
**Did NOT meet 20-min or 100%.** Two gaps:

### GAP A — Throughput (the 20-min target)  [~5× short]
- Source registration ~1.5–2/min (need 7.5/min). OCR itself is fast (~2s); the 56s/doc is the
  extraction round-trips + (gmail) throttle.
- Root: the **scanner dispatches docs serially** (`SyncScanner00001` Call Scan Unit + `SyncScanUnit0001`
  Call Processor are `mode=each`, awaited). Completion (main-WF supabase poll) already parallelizes (~8–11/min);
  registration does not.
- BS-line explosion (60 BS docs → ~820 lines) **starves** source-doc processing in the shared poll.
- Gmail IMAP throttle creeps under burst (2→7s/cmd) — fewer-commands/doc helps (noop+metadata fetch done).
- **Fix:** make registration poll-driven/parallel like completion (scanner claims fast → pending rows →
  parallel downloader poll), OR run the 5 **disjoint** sync units concurrently via async dispatch
  (n8n `mode=each` awaits — needs webhook/HTTP async + an overlap-safe atomic claim). Isolate BS-line
  processing so it doesn't starve source. Pace gmail.

### GAP B — Completion (the 100% target)
- ~16 gmail docs parked **UNKNOWN + ACTION_REQUIRED with NO AI extraction** (AI_TYPE/AI_COMPANY/
  AI_EXTRACTION_COMPLETED all null). 6 of them DID extract a company (OCR worked) yet type=UNKNOWN and
  the **Gemini AI fallback never ran** → parked. (Drive completion healthy ~90%.)
- Root (suspected): gmail-attachment download/OCR quality under throttle → poor/blank content → UNKNOWN;
  and/or the Determine-Action AI fallback gate not firing for these UNKNOWN docs (cf.
  `incoming-docs-classification-fallback`).
- **Fix:** ensure the Gemini AI_TYPE fallback runs+adopts for UNKNOWN-but-has-content docs; harden gmail
  attachment fetch under throttle (the downloader needs full bytes — distinct from the metadata classify fetch).

## Verified-good (do not re-litigate)
5 syncs work; gmail-bs/link fixed (state-ownership refactor in Scan Unit `Apply Outcome`; Build Units
`search_extra` propagation bug fixed); extraction ~100% on completed (local matches/beats AI; date-missing
are genuinely dateless); BS lines complete; OCR fast; noop-amplifier + http-timeout(120s) deployed.

## Status
Both gaps are real, careful engineering on core sync architecture / main-WF flow — implement reviewed,
incrementally, with verify+revert (stability is a goal criterion). System left stable + correct.

## Gap-A fix attempt — pscan (parallel disjoint-sync dispatch)
IMPLEMENTED safely (orchestration-level, no workflow edits, reversible): `scripts/_parallel_scan.js` +
`acceptance-run.sh pscan` fire all 7 disjoint sync units CONCURRENTLY via REST `/run`+pinData.
- **Result:** initial registration burst ~7/min (vs ~1.5/min serial, ~4–5×), NO OOM at 30-doc scale.
  The mechanism works (standalone unit trigger + pinData params verified).
- **Limits found:** (1) pscan fires ONCE per call (each unit processes one `search_take` batch then
  finishes) → needs a re-fire LOOP to drain >batch. (2) Under gmail throttle the gmail processor
  download errors and the unit errors UPSTREAM of `Apply Outcome`, so the on-fail cleanup never runs →
  docs stuck in `in_progress` (claimed, unregistered, excluded from re-search). (3) The gmail IMAP
  throttle remains the fundamental wall for the gmail portion (90 docs) regardless of dispatch parallelism.
- **Next (careful):** (a) pscan loop until to_sync empty; (b) harden on-fail: claim-release/failed-tag even
  when the processor errors (move `Apply Outcome` to always-run / continueOnError on Call Processor at the
  unit's claim level); (c) the gmail-90-in-20min likely needs Gmail-side throttle relief or fewer
  commands/doc — drive(60) parallelizes fine, gmail is the ceiling.

## Refinement: pscan parallelism is ACROSS-unit only
pscan runs the ~7 sync units concurrently, but EACH unit still processes its claimed batch SERIALLY
(Call Processor mode=each). So max parallelism = #units (~7 streams) x serial-within. For true per-doc
parallelism (and to hit 150/20min), registration must be poll-driven per-doc (mirror the main-WF
completion poll): scanner claims fast -> pending rows -> a poll-triggered downloader processes each in
parallel across workers. That + gmail-throttle relief is the path to the full goal. pscan + retry-hardening
are the safe partial wins shipped this window.

## Gap-B fix location (gmail UNKNOWN -> AI fallback)
Active main WF: Incoming Documents 0.1.7 (sv5xxRBVGxvV0kXx). The Gemini fallback node
"Action: Extract Invoice Google AI" -> "Call 'invoice Extractor - Gemini 3.1 pro'" is gated by node
"3a. GDOC Action Switch1". UNKNOWN-type gmail docs with OCR content are NOT routed to that AI-extract
branch (they fall through to ACTION_REQUIRED with no AI_TYPE/AI_EXTRACTION). FIX: add a switch route so
TYPE=UNKNOWN (with content / not yet AI-extracted) goes to "Action: Extract Invoice Google AI", then the
existing AI_TYPE-adoption completes them. Careful main-WF change (core loop) - test on the 16 parked docs.

## Gap-B precise location (CORRECTION)
The "3a. GDOC Action Switch1" is a string-switch on $json.ACTION (just ROUTES the decided action).
The real gate is the **"Determine Action" code node** (0.1.7) which DECIDES the next ACTION per doc.
For TYPE=UNKNOWN docs it does not assign an AI-extract action -> they fall to action_required with no AI.
FIX (careful, core decision logic): in Determine Action, when TYPE=UNKNOWN and AI_EXTRACTION not done and
there is OCR content, assign ACTION=extract_invoice_ai (the value that routes to "Action: Extract Invoice
Google AI") before falling through to action_required. Then existing AI_TYPE adoption completes the doc.
Test on the 16 parked docs; revert via bbox n8n push if regression.

## Gap-B exact ACTION value
The AI-extract branch = GDOC Action Switch outputKey "extract_invoice_google_ai" (output 19) ->
"Action: Extract Invoice Google AI". So the Determine-Action fix: for TYPE=UNKNOWN with OCR content and
AI_EXTRACTION_COMPLETED null, set ACTION="extract_invoice_google_ai" (before any action_required
fallthrough). Gap-B is now fully specd to the literal value.

## Gap-B CORRECTION (supersedes the route-add specs above)
The AI-fallback route ALREADY EXISTS in Determine Action:
  line 331: if (doc.API_TOOLS_ID && !doc.AI_EXTRACTION_COMPLETED) return "extract_invoice_google_ai";
  line 219-221: if (TYPE=="INVOICE" && !AI_EXTRACTION_COMPLETED) return "extract_invoice_google_ai";
  line 349-350: if TYPE in (UNKNOWN/UNKNWON) && AI_TYPE known -> adopt AI_TYPE.
So NO route needs adding. The 16 parked UNKNOWN docs do not reach line 331 -> most likely they have NO
API_TOOLS_ID (gmail-attachment OCR produced no apitools id) OR an earlier action-precedence return.
Real fix = runtime-trace the parked docs (scripts/indox-doc-trace.py) to see which field is missing, then
address THAT (likely gmail-attachment OCR quality), NOT a Determine-Action route change. Do not implement
the earlier (wrong) route-add spec.

## INCIDENT 2026-06-27: Docker Desktop crashed mid-window
Docker Desktop fully exited (engine pipe gone, no process) -> deployment offline. Recovered by restarting
Docker Desktop (host); 36 containers auto-restarted (restart:unless-stopped); n8n/supabase/inbox/redis
back up + functional. Consistent with long-heavy-session Docker degradation (see docker-desktop memory).
