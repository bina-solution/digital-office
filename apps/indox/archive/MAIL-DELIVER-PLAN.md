# The final mail deliver lane — plan and predicted end state

*Design, 2026-08-27. Every number is measured live on this estate; projections are marked as such.*

## STATUS — updated 2026-08-27 17:2x

| step | state |
|---|---|
| 1. gmail-bs: stop writing canonical `TYPE` | **DONE, pushed, PROVEN live** |
| 2. gmail-doc: save-before-extract + sender chain | not started |
| 3. gmail-link: same | not started |
| 4. mail-private: add `ATTACHMENT_TEXT` / `TYPE_BY_SOURCE` | not started |
| 5. retire `mode:'proc'` for mail | not started |
| 6. backfill 13,998 already-typed rows | **blocked — owner decision** |

**Step 1 proof, `doc_mtbpnp4q6n4oae`** (born 16:02:01, gmail-bs, fresh document 991204):

```
16:10:35 extract_base_doc   ← impossible before the change; the gate requires !doc.TYPE
16:11:11 select_base
16:11:18 get_company_name
16:11:27 extract_per_type   ← requires API_TOOLS_ID, which base had just produced
16:11:54 select_base        ← designed re-selection (BASE_SELECTION_HASH changed)
16:12:00 link_documents
16:12:14 select_type
16:12:24 mark_completed
```

Final row: `STATUS=COMPLETED`, `API_TOOLS_ID=42a6a69e2e528113c1da4008b0ec8887`,
`BASE_EXTRACTION_COMPLETED=true`, `PER_TYPE_EXTRACTION_COMPLETED=true`,
`TYPE=BALANCE_SHEET` (from `AI_TYPE`+`LOCAL_TYPE`, after extraction),
`TYPE_BY_SOURCE=BALANCE_SHEET` (evidence), company 512774019 אוהב ציון. **109 seconds.**

**Key secondary finding: the apitools uploader is not broken.** Given a real `LINK` it produced an
id on the first attempt. The 37/38 `wrong_input` failures are purely the ordering defect (§1), so
steps 2–3 need no uploader change.

Estate as of this snapshot: 25,981 docs, **9,165 COMPLETED (35.3%)**, `pertype_ready` still **66**,
**13,998** live typed rows still locked out of base. Last 24h by pipe:

| pipe | rows | api_id | completed |
|---|---|---|---|
| gmail-doc | 26 | **0** | **0** |
| gmail-link | 2 | **0** | **0** |
| **gmail-bs (fixed)** | 1 | **1** | **1** |

## 0. The one rule

**Ingest CARRIES EVIDENCE. Ingest NEVER WRITES A VERDICT.**

A verdict is `TYPE` or `COMPANY_ID`. Evidence is the sender chain, the subject/body text, the
registry's hint, and — above all — **the saved file**. The state machine owns the only two
sanctioned resolution points (`extract_base_doc`, then `select_base`), which is what the
two-point rule already says.

Every defect below is one violation of that rule, or of its corollary:

**Nothing may be extracted before it is saved.**

## 1. Root cause, proven

`BaseDocEx01` and every child it calls are **fetch-by-URL**. They take `LINK` / `LINK_CONNECTION`
and go get the bytes. But the mail processors invoke them *before* the attachment has been
persisted to Drive.

Live trace, `doc_mtbfi84oo0cpa8` (execution [3675621](http://n8n.localhost/workflow/indoxGmailDocDownloader01/executions/3675621)):

| time | step |
|---|---|
| 11:16:59 | `Process Document` → `indoxProcessDocument01` [3675643](http://n8n.localhost/workflow/indoxProcessDocument01/executions/3675643) |
| 11:17:07 | `BaseDocEx01` [3675661](http://n8n.localhost/workflow/BaseDocEx01/executions/3675661) — `Doc In` gets `HASH` set, **`LINK_CONNECTION: null`, `LINK` absent** |
| 11:17:08 | `indoxV2UploadApiTools01` [3675662](http://n8n.localhost/workflow/indoxV2UploadApiTools01/executions/3675662) → `wrong_input`, `file_id: null`, `ok: false` |
| 11:17:16 | `Extract Base via Webhook` → **`LINK: null, error: missing_link`** |
| **11:17:34** | `Upload Document` → Drive id `lf1a042f08d5cd8f7f5322` ← **the file is saved 35s too late** |
| 11:17:50 | row created, `TYPE=INVOICE`, `API_TOOLS_ID` null |

Both extraction legs failed for the same reason, and **n8n recorded every execution as
`success`**. `BaseDocEx01` line 334 reads `API_TOOLS_ID: {{ $('Upload+OCR').item.json.file_id }}`
— a null `file_id` silently becomes a null `API_TOOLS_ID`.

Scale: `indoxV2UploadApiTools01` returned `wrong_input` on **37 of 38** runs in 24h (**33 of 33**
today). `BaseDocEx01` returned `file_id: null` on **37 of 38**. Zero `API_TOOLS_ID` produced by
any proc pipe in 7 days.

The binary cannot be passed as a workaround: `indoxV2UploadApiTools01`'s trigger declares
`workflowInputs = [LINK, HASH, ID, LINK_CONNECTION]`, so n8n strips everything else — including
the `binary-test` flag its own `If Binary test` node reads. That branch is unreachable by
construction.

## 2. Why thin already works

A thin row is saved first and typed never, so when `extract_base_doc` runs it passes the row's own
`LINK` (`indoxV2ActionsGlobal01` line 1834) and the file is there.

Measured, last 7 days:

| pipe | lane | rows | company % | `API_TOOLS_ID` | typed at birth |
|---|---|---|---|---|---|
| **mail-private** | **thin** | 12 | **91.7%** | **11** | untyped |
| gmail-doc | proc | 221 | 19.0% | **0** | **100%** |
| gmail-link | proc | 14 | 14.3% | **0** | **100%** |
| gmail-bs | proc | 7 | 57.1% | **0** | **100%** |

All-time completion: mail-private **58.4%**, gmail-bs 51.2%, gmail-link 42.0%, gmail-doc **28.1%**.

The thin lifecycle, observed on `doc_mt1mum6tith4oh`:

```
extract_base_doc → get_company_name → extract_per_type → action_merge_doubles
```

One action each. No restart. No double action. `extract_base_doc` has ever run for **551**
mail-private documents and **21** gmail-doc documents.

## 3. What each lane does wrong

**`indoxGmailDocDownloader01` (2,056 lines, 24 nodes)** — extracts before saving (§1); writes
`document_type` as canonical `TYPE`, locking the row out of base forever; drops the sender; emits
a 12-key upsert payload carrying no `API_TOOLS_ID`, `AI_TYPE`, or `BASE_EXTRACTION_COMPLETED`;
loses `LINK_CONNECTION` on **197 of 707** rows.

**`indoxGmailLinkDownloader01` (2,337 lines)** — same shape: `Process Document` (node 642) before
`Upload Document` (node 688).

**`indoxGmailBSDownloader01` (1,817 lines)** — the closest to right: no OCR, no `BaseDocEx01`. Its
one fault is the hard-coded `TYPE: 'BALANCE_SHEET'` at line 838. Its `Balance Doc Properties` node
is the piece to keep.

**thin (`mail-private`)** — right order, no evidence: `LINK`+`LINK_CONNECTION` on **4,418/4,418**,
but **0** `ATTACHMENT_TEXT` and **0** `TYPE_BY_SOURCE`, so `select_base` has nothing to reason
with when the page is unreadable.

## 4. The piece to reuse — `Balance Doc Properties`

The BS lane already solved relay senders. Its own note:

> intermediary senders print the SaaS letterhead and name the supplier only in the subject

Chain, in order: `From` → **display-name unwrap** (`person46@example.com` hides the real address in
the display name) → **forwarded-chain extraction** (drop `no-reply`/`noreply`/`mailer-daemon`/
`donotreply` and ignore-listed) → lookup in `company_name_by_mail` **by email, then by domain** →
`companies[name].identifiers[0]`. It emits `senderCandidates` (ordered) and `sourceText`
(subject + first 100 chars of body), computed **once per mail** and stamped onto **every**
attachment, each keeping its own binary.

This is exactly the `noreply@DocServer.app` → קבוצת נגב case. Estate-wide today: `SENDER` on
**106 of 3,031** mail rows, `COMPANY_BY_SENDER` on **25 of 25,972**.

## 5. Target — ONE mail deliver lane

Replaces all three mail processors. Registry differences (`fallback_type`, `type_hint`, dest
folder, label keys) stay in the registry: configuration, not code paths.

```
Get Message
 └─ Split Attachments          one item per attachment, binary preserved
     └─ Filter Irrelevant      size / mime / name rules from settings
         └─ Mail Facts         Balance Doc Properties, generalised — ONCE per mail
             └─ Save To Drive  → LINK + LINK_CONNECTION, always, BEFORE anything reads the file
                 └─ Build Row  evidence only
                     └─ Upsert
                         └─ Tag Mail   synced / failed, from label_keys
```

No OCR. No `BaseDocEx01`. No `indoxProcessDocument01`. No type decision. ~10 nodes replacing ~24.

### Row contract

**Writes (evidence):** `SOURCE_TYPE`, `SOURCE_ID` (thread id), `SYNC_NAME`, `SYNC_REGISTRY_ID`,
`LINK` + `LINK_CONNECTION` (**both, always** — a row without a connection can never extract),
`NAME` (attachment filename, *not* company-derived), `ATTACHMENT_TEXT` (= `sourceText`), `SENDER`,
`SENDER_CANDIDATES`, `COMPANY_BY_SENDER`, `TYPE_BY_SOURCE`, `STATUS='IN_PROGRESS'`.

**Never writes:** `TYPE`, `COMPANY_ID`, `COMPANY_NAME`, `API_TOOLS_ID`,
`BASE_EXTRACTION_COMPLETED`, `AI_*`, `LOCAL_*`.

`COMPANY_NAME` stays a pure join on `COMPANY_ID`; neither is written here, so the invariant holds
by construction.

### Then the state machine, unchanged

```
extract_base_doc → select_base → get_company_name → extract_per_type → mark_completed
```

`extract_base_doc` fires because `TYPE` is empty, and succeeds because `LINK` exists.
`select_base`'s `typeBySource` fallback becomes *correct* — it only ever fires after the engines
have spoken.

### Retire `mode: 'proc'` for mail

`syncV3Deliver0001` infers `const mode = j.mode || (j.processor_wf ? 'proc' : 'thin')`. `proc`
exists for v1 parity — *"run the UNCHANGED v1 processor workflow… preserved verbatim"*. That
parity is now the defect: the v1 steps it preserves are the ones that extract before saving and
write verdicts at ingest. Once mail runs the lane above, `proc` has no mail callers.

## 6. Order of work

1. **Fix the apitools hand-off.** Either give `indoxV2UploadApiTools01` a real LINK, or stop
   calling it before the file exists (§5 does the latter by construction). Make `ok === false`
   raise instead of being swallowed — this failure was invisible for 24h+ at 97%.
2. **Build the unified lane** against the row contract; prove on `gmail-bs` (82 rows, smallest).
3. **Migrate** `gmail-doc` → `gmail-link` → `mail-private` (which also gains `ATTACHMENT_TEXT` /
   `TYPE_BY_SOURCE`).
4. **Retire** `proc` for mail; drop `indoxProcessDocument01` from the mail path.
5. **Backfill** — separate, owner-approved: **14,264** live typed rows cannot re-enter base while
   they hold a `TYPE`.

## 7. Predicted end state

Baseline today: 25,972 documents, **8,486 COMPLETED (32.7%)**, `pertype_ready` **66**, apitools
success **1 in 38**, completions **0 since 03:00**.

**Measured, therefore expected with confidence** (these are current thin-lane numbers, not
guesses):

| metric | now (proc mail) | after (thin mail) | basis |
|---|---|---|---|
| apitools upload success | 1/38 (2.6%) | ~100% | LINK exists before the call |
| `API_TOOLS_ID` on new mail | 0/242 | ~11/12 rate | mail-private, last 7d |
| company resolved at ingest | 19.0% | ~91.7% | mail-private + sender chain |
| typed at birth | 100% | 0% | contract forbids it |
| actions per document | 2, then parked | 4–5, then COMPLETED | observed thin lifecycle |

**Projected, lower confidence** — new-mail completion should move from gmail-doc's **28.1%**
toward mail-private's **58.4%**, and higher still once the sender chain lifts company resolution
above what mail-private gets today. I would not promise a number beyond "materially above 28%"
until step 2 is measured on gmail-bs.

**What this does NOT fix:**

- **1,983 `MISSING_LINK`** — a different cause (no fetchable link at all); untouched here.
- **14,264 already-typed rows** — need step 5. Until then the estate's COMPLETED count moves only
  with new mail.
- **`pertype_ready`** returns to ~3,148 only after step 5; new mail alone will not restore it.

**Steady state, once 1–5 land:** mail arrives → saved → row of evidence → `extract_base_doc`
succeeds → `select_base` picks from real engine output → company/type resolved or honestly
`MISSING_*` → per-type → `COMPLETED`. One action each, no restart, no double action — the
lifecycle the thin pipe already demonstrates today.
