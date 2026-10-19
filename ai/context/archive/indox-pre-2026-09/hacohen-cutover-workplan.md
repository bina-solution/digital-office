# Hacohen cutover — the honest state and the work plan

**Date:** 2026-07-17. Written after 19 defects in one night. Read this before touching anything.

## The one-line truth

**We proved CONNECTIVITY, not the PIPELINE.** drive lists 600 real folders; mail lists 850 real
messages; 45,839 documents loaded and reconciled. **Not one document has gone mail→COMPLETED on
this deployment.** INDOX is currently OOM-looping on the very data we migrated. Everything that
looks green is a probe that never called anything.

## Why it feels shaky — because it is

| symptom | evidence |
|---|---|
| INDOX processes nothing | 0 docs progressed in 45 min; 357 crashes/hr; `max(updated_at)` frozen at the load |
| alerts are dead | ~1,700 real errors, `התראות` shows **0** — broken in 3 independent places |
| health is fabricated | `connections/app.py:325` invents `derived:<sha>` from the secret key when the value is EMPTY → `probe: present` → **healthy** |
| drive ops fail | 253 errors: n8n's Google creds have `data` length **0** |
| 4 apps unreachable | my-docs/drive/wadmin/supabase-studio 404 on the domain |

## Defects — 19 found, by what they cost

### P0 — active harm (DISARMED 2026-07-17, verify before re-enabling)
1. **Staging reported into the CLIENT'S PRODUCTION GlitchTip** — 1,888 events tagged
   `environment: production`, indistinguishable from real client errors. `N8N_SENTRY_DSN` empty →
   the committed URL (`glitchtip.hacohen…` = 31.97.196.129) stood. Workflow `glitchtipReporter01`
   deactivated; count frozen 1888→1888 over 75s (verified).
2. **`WhatsApp Send Document` was ACTIVE against the client's production bot**
   (`wadmin.hacohen…`). 0 runs — luck, not design. `whatsappSendDoc01` deactivated.
   ⚠ Both are deactivated in the LIVE DB only. The blueprint still ships them `active: true`, so
   **the next `bbox n8n push` re-arms them.** Fix at the source before any push.

### P0 — lies (the class that makes everything else untrustworthy)
3. **`/readyz` silently substitutes local.** Active pointer unresolvable → readyz still
   `ready:true`, naming a DIFFERENT connection. n8n trusts ONLY readyz ⇒ drive ops would run on
   local disk while the owner believes it is his Google Drive. Contract §2 violated.
4. **`probe: present` returns healthy for placeholders.** `GEMINI_API_KEY` = `your-…-key` →
   "בדוק חיבור" → `{"ok":true,"status":"healthy","detail":"env"}`. It never calls Google.
   `google-vision-key` DOES probe for real (`HTTP 200`) — the capability exists, applied to one key.
5. **`derived:<sha>` fabrication** (above). Under the comment *"green only if it actually works"*.
6. **Alert path dead ×3**: reporter → wrong host; staging GlitchTip **never provisioned**
   (`glitchtip-push` runs only from `scripts/ci-verify.sh`, never from bring-up); `notifications`
   has no token → 401. Telegram fallback returns `{"error":"Not Found"}` but `continueOnFail`
   makes it report **success**.
7. `notifications /healthz` → `{"ok":true,"token":false}` — 200 + Docker-healthy while knowing it
   is blind.

### P1 — pipeline
8. **`Call INDOX GETALL` does `select "ID" from incoming_documents` with NO LIMIT** → 45,839 rows →
   worker heap 1536MB → OOM → restart → repeat. **This is what wedges INDOX.** Fix first.
9. 66 executions stuck `running` forever (orphaned by dying workers); triggers still say "started".
10. **n8n Google creds are EMPTY** (`KirWFwoFdEFmnN0R`, `e2knIZpw8YF0QBAB`, `DfQPc6wpof8GdkFo`)
    while connections reports the grant `healthy`. The grant lives in connections and was never
    injected — and `DRIVE_BACKEND=google` still routes n8n's drive ops through those creds.
11. Only **88 of 116** active workflows have an `errorWorkflow`.

### P2 — fixed earlier tonight (11 defects)
`wa_media` (0/45 services started) · `kong-entrypoint.sh` non-exec (supabase dead on Linux) ·
19 name-only tags (0/121 workflows imported) · `CONSOLE_BASE_URL`/`CONNECTIONS_BASE_URL` undeclared ·
portainer password file · `CONNECTIONS_PUBLIC_URL` unset (OAuth impossible) · console→connections
oauth 404 · `N8N_OWNER_*` not passed to connections · Secure cookie over internal http ·
**`vault_write` per-PID tmp → concurrent writers silently destroy the whole vault** · mail
`active:null` on a fresh install.

## The sync question — what must be established (NOT yet known)

The owner's requirement: **every sync source that works in production must work here.** The
`sync_registry` refactor makes the current shape unclear. Establish, from the LIVE production
system, not from memory:

1. **What production actually syncs.** `sync_registry` is a double-JSON-encoded string in an n8n
   `settings` row. 5 entries today: `drive-bs`, `drive-gdoc` (3 folder pairs), `gmail-link`,
   `gmail-bs`, `gmail-doc`. For each: source type, the real Drive folder IDs / Gmail labels, the
   processor workflow, batch/schedule. **Compare against the legacy production registry** — ours
   may have drifted.
2. **The two end-to-end journeys, node by node:**
   - **mail → COMPLETED**: new mail → `tag_rules` label → `SyncScanner` → `SyncScanUnit` →
     `syncV3Deliver0001` (gmail get → drive upload → label swap) → `incoming_documents` row →
     `indoxV2Driver01` → Decide → Actions → OCR (apitools) → extractors (JsonQueryExV3) →
     COMPLETED.
   - **drive → COMPLETED**: invoice/aging report lands in `DocumentsToProcessFolder` → the same
     state machine via folder moves instead of label swaps.
   Both are the SAME state machine (`to_sync → in_progress → synced/failed`) — folder-move vs
   label-swap are two implementations of one transition.
3. **Run the tests.** `scripts/indox-test.py --lanes` / the `*-e2e-lane` webhooks / the INDOX UI
   בדיקות tab drive the suites (sync_kernel, sync_sources, sync_full, gdoc, pipeline). These exist
   and must pass HERE, on real accounts — not only on local/GreenMail.
4. **Performance**: the bar from [[indox-expected-behaviour]] is 100+ docs/type/10min.

## Plan — in this order, no skipping

**Phase 0 — stop the bleeding (done + verify)**
- [x] disarm the 2 client-production leaks (live DB)
- [ ] fix them in the BLUEPRINT so a push cannot re-arm them
- [ ] `N8N_SENTRY_DSN` → staging's own GlitchTip; run `glitchtip-push` from bring-up, not only CI

**Phase 1 — make green mean green** (nothing below is trustworthy until this lands)
- [ ] `probe: present` → reject placeholders; real probes where a real probe exists
- [ ] kill the `derived:<sha>` fabrication — empty must read empty
- [ ] `/readyz` must FAIL when the active pointer does not resolve (never substitute local)
- [ ] `notifications /healthz` must be red when `token:false`
- [ ] remove `continueOnFail` from the alert path — a rejected alert is a failure

**Phase 2 — unwedge INDOX**
- [ ] LIMIT/paginate `Call INDOX GETALL` (the OOM root)
- [ ] reap the 66 zombies; confirm workers stop cycling
- [ ] inject the Google grant into n8n's creds — OR finish the refactor so n8n stops holding them

**Phase 3 — establish the syncs (the owner's core ask)**
- [ ] document what production syncs, from production
- [ ] port every source; both journeys traced node-by-node on THIS deployment
- [ ] run the E2E suites against the real accounts; publish pass/fail per lane

**Phase 4 — prove it live**
- [ ] a real mail → a COMPLETED document, unattended
- [ ] a real invoice + aging report on Drive → COMPLETED
- [ ] measure against 100+/type/10min; then the UX audit's remaining journeys (mail, INDOX)

**Phase 5 — cutover**
- [ ] disable the legacy syncs (else two systems fight over the same mail)
- [ ] fix the live legacy bug on the way in: `מייל-מספק` = "Rule too long" (~300 suppliers inlined)
- [ ] full-day audit

## The rule for all of it

**A check that cannot fail is not a check.** Every defect above is the same disease: something
reported success without doing the work. Do not accept a green until you have seen the thing it
claims.

Related: [[fresh-vps-staging-bringup]], [[platform-service-contract]],
[[product-ux-acceptance-audit]], [[hacohen-legacy-migration-spec]], [[indox-expected-behaviour]].

---

## INCIDENT 2026-07-17 ~01:30 — staging wrote to the CLIENT'S LIVE MAILBOX

**What happened.** The INDOX agent ran `bbox n8n push` to deploy its OOM fix. n8n-push builds its
active set from each blueprint file's `active` field, and the blueprint ships `Sync Scanner`
active:true (correct for production). So the push **re-armed Sync Scanner on staging**, whose mail
connection was pointed at the client's REAL person9@example.com with write scopes.

**Confirmed impact** (inbox access log, 100-min window):
```
10× POST /labels/add      ← real label writes on the client's mailbox
10× POST /labels/remove
11× GET /message · 14× POST /search   (reads)
```
`Sync Scanner` ran 5×; `Sync v3 Deliver` (the write stage) 11 success / 24 canceled / 1 crashed.
Drive writes almost certainly did NOT land — n8n's Google creds are empty (defect #10), so drive ops
403. The exposure is Gmail label swaps on ~10 messages, i.e. the to_sync→in_progress→synced
transition, on a mailbox the LEGACY PRODUCTION is also processing.

**Why it stopped.** Two independent things, one deliberate: I re-paused Sync Scanner (verified `f`),
and separately the mail pointer was lost in a rebuild, falling back to `mail_imap_app_password-env`
whose password is a placeholder → AUTHENTICATIONFAILED. No further writes are possible.

**Not yet known — do this first:** exactly WHICH messages and WHICH labels. The inbox access log
records the calls, not the arguments; the label names live in the n8n execution data for the 11
`Sync v3 Deliver` successes. Recover them from there before anything else, so the swaps can be
reverted and so we know whether production double-processed those 10.

**The lesson, and it is not "be careful".** A staging pause that lives only in the live DB is not a
control — it is a note. The blueprint re-asserts itself on every push, by design. Staging must be
STRUCTURALLY incapable of touching a client's live account:
- the account selection is the real switch — staging should point at a test mailbox, not the
  client's; or
- the scanner's schedule must be env-driven (like the backends were) so a deployment declares
  whether it syncs, instead of inheriting production's answer.
Both are the same principle as the leak fix: **fix the ADDRESS, not the flag.** The flag flipped
back within the hour — exactly as the flag before it did.

**Also found:** the mail service's active pointer did not survive a container rebuild. The client's
selected account silently reverted to a broken env default. `/readyz` reports it honestly (503,
AUTHENTICATIONFAILED) — the new truth-telling working — but a selection that evaporates on redeploy
is its own defect.
