# mailview → daily business platform: final-state plan

Status: DESIGN (2026-07-09). Owner: mail fork. App: production/mailview (mail.localhost)
over the inbox abstraction (env-swappable local/gmail backend — proven on both).

## 1. Honest diagnosis — why today's app is "far from ready"

Looking at the real account through it makes the gap obvious:

1. **It renders mail, not meaning.** A daily operator's question is not "what mail
   arrived" but "what documents are in flight / failed / need me". Today every row
   shows 4–6 label chips (the state machine's *journey*, designed for machines).
   The one bit that matters — current state — drowns in chip soup.
2. **Flat dump.** `limit=100`, newest-first, "100 הודעות" even when the mailbox has
   thousands. No pagination, no day grouping, no threading (per-doc link mails ×
   supplier correspondence make many near-identical rows), no per-label counts.
3. **No bridge to the pipeline.** A נכשל chip is a dead end: you can't see WHY it
   failed, what the extractor read, or jump to the file in drive/morning. The data
   exists (`incoming_documents`: STATUS, TYPE, LINK, SOURCE_ID=gmail id, amounts,
   company) — the app just doesn't join it.
4. **No triage surface.** Landing page is "all mail". The daily loop should start at
   "דורש טיפול": failures, unidentified, stuck. Zero clicks to the work.
5. **Demo noise.** The real mailbox now carries synthetic battery mail (subjects
   stamped `הזרקת בדיקה`/lane markers). Real usage needs a hide-test-mail default.

Strategic call (recommended): the endgame is a **document-intake operations console**
where email is one lens (drive + whatsapp are peer sources feeding the same
`incoming_documents`). Build mailview toward that: mail parity where it serves
triage, not Gmail-clone completeness. No compose/reply — read + tags stays the
mutation surface (tags ARE the pipeline's control plane).

## 2. Phases

### Phase 1 — Signal over noise (UI-only, fastest visible win)
- **One derived status per row.** Precedence over the label set:
  נכשל/פעולה נכשלה > לא מזוהה > באמצע טיפול > לטיפול > טופל/נשמרה/בוצעה > (ללא).
  Render ONE colored badge column; remaining labels collapse behind `+N` (click =
  chip popover). Journey chips stay visible in the reader drawer.
- **Sidebar becomes a status board.** Group by doc-type (דוחות גיול / מסמכים כללי /
  חשבוניות / תעודות משלוח…) with per-state counts (new `/api/counts`, see Phase 2)
  instead of one nav row per raw label.
- **Default landing = "דורש טיפול"** (union of failure/unidentified labels), with
  "כל הדואר" one click away.
- **Day-group headers** (היום / אתמול / השבוע / earlier) + thread collapse by
  `threadId` (gmail mode has X-GM-THRID; local id==thrid so it's a no-op there).
- **Hide test mail** by default (`-subject:"הזרקת בדיקה"` style filter, toggleable).

### Phase 2 — Scale + counts (backend contract additions to inbox)
- **Cursor pagination:** `/search` gains `before_uid`/`page_size`; returns
  `{messages, total_estimate, next_cursor}`. UI: infinite scroll. Statusbar tells the
  truth: "מציג 50 מתוך ~1,240".
- **`/labels/counts`:** per-label total+unread. gmail mode = ESEARCH COUNT per
  labeled query (cache 60s server-side — 30 labels × ESEARCH is too hot per view);
  local mode = STATUS on mirror folders (free).
- **Single-part attachment fetch:** `/message` gains `part=<n>` (BODYSTRUCTURE part
  number) so previewing one PDF doesn't download every attachment of the message.
- **Explicit read-state action:** mark-read/unread as a visible user action (PEEK
  everywhere else keeps the read-only promise honest).

### Phase 3 — Operations console (the actual business value)
- **Doc context join.** New `/api/doc-context/<gmail_id>` in mailview → calls the
  n8n API layer (indoxApiRouter01 webhook; per architecture rule, nothing reads the
  DB directly) → `incoming_documents` by SOURCE_ID: STATUS, TYPE, company, amounts,
  extraction fields, LINK (drive), COMPANY_DOC_ID (morning).
- **Reader drawer gains a "מסמך במערכת" panel:** live pipeline state, last error,
  extracted totals vs. document, buttons: פתח בדרייב / פתח בפנקס / שלח לעיבוד מחדש
  (= add לטיפול label, exists today) / סווג מחדש (set type + requeue).
- **Attention queue as a real view:** failures + לא מזוהה + *stuck* (in-flight with
  stale NEXT_RETRY_AT — that signal only exists in the DB, another reason for the
  API join). Each row: reason + one-click fix.
- **Inline PDF/image preview** in the drawer (same pattern as localdrive's viewer) —
  operators decide by *looking at the document*, not the email text.

### Phase 4 — Daily-driver polish
- Bulk select + bulk tag (requeue 20 failures at once), keyboard nav (j/k/Enter/x),
  saved views, empty/skeleton states, mobile-usable layout.
- CI: mailview health-* + an integration-* that walks list → filter → open → tag
  against the local backend battery.

### Phase 5 — Unification (strategic horizon)
- "מייל" grows into **"קליטה" (intake)**: one console over gmail + drive (+ whatsapp
  later), rows = documents from `incoming_documents`, email/file view = detail lens.
  Everything in Phases 1–4 survives as the email lens of that console.

## 3. Sequencing + effort

| Phase | Effort | Unblocks daily use? |
|---|---|---|
| 1 | ~half day | Yes — the "chip soup" complaint dies here |
| 2 | ~1 day | Truthful at real-mailbox scale |
| 3 | ~1–2 days | This is the platform part |
| 4 | ~1 day | Comfort + CI safety |
| 5 | separate design | Product decision |

Recommended order: 1 → 3 → 2 → 4. Phase 3 before 2 because triage value beats
pagination truth for a mailbox the operator filters by label anyway.

## 4. Open questions for the operator
- Attention-queue semantics: is stale-in-flight (stuck) triage worth surfacing in v1,
  or are the failure labels enough to start?
- Should "שלח לעיבוד מחדש" clear failure labels itself, or leave the journey visible
  and let the state machine re-stamp?
- Real-account hygiene: the synthetic battery mail on solutionsbina — hide-by-filter
  (this plan) or actually clean the mailbox (user action; deletion is out of scope
  for automation)?
