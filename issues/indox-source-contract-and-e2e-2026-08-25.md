# The source contract (sync ⇄ select) + the end-to-end proof — 2026-08-25

Owner's split, implemented verbatim:

> **The SYNC** settles, per sync, exactly **who the sender is**, **which sync delivered it**, and
> **what text came with it** → `SENDER` · `SYNC_REGISTRY_ID` · `ATTACHMENT_TEXT` (+ `SEND_DATE`).
> **The SELECT** derives the new data → `COMPANY_BY_SENDER` · `TYPE_BY_SOURCE`, and then uses them
> **as part of all the options for each datum**.

## 1. What shipped (live, pushed, validated)

| layer | change |
|---|---|
| schema | `SENDER`, `SYNC_REGISTRY_ID`, `ATTACHMENT_TEXT`, `SEND_DATE`, `COMPANY_BY_SENDER`, `TYPE_BY_SOURCE` (+ fixtures/schema.sql) |
| `indoxGmailBSDownloader01` | emits the FULL ordered candidate chain it already computed (gaviti-unwrap → forwarded chain → raw From) + subject/first-100-chars + SEND_DATE |
| `indoxGmailDocDownloader01` | same five rules, **newly implemented in this lane** (it only ever logged the From) |
| `indoxGmailLinkDownloader01` | same — the lane that needs it most (46% company-less) |
| `SyncProcBS000001` / `SyncProcGDoc0001` | drive lanes: SENDER = the folder that handed the file over, ATTACHMENT_TEXT = the ORIGINAL filename, SEND_DATE = the file's createdTime, SYNC_REGISTRY_ID = ctx.sync_name |
| `SelectBase01` | derives + stores `COMPANY_BY_SENDER` / `TYPE_BY_SOURCE` and uses them as legs after LOCAL/AI |

### The full-list decision (owner's correction, and it was right)
A single `SENDER` address **loses company figuring**. Proven in SQL on live data: a chain
`person190@example.com, person191@example.com, person9@example.com` contains two real companies —
under "unambiguous only" the leg returns **nothing**; under chain order it returns **איטונג**
(position 9) over טמבור (position 29), which is exactly the BS lane's historical rule
("first candidate that resolves wins"). All three mail lanes now emit the ordered chain, and the
SQL leg resolves by `position(...)` ascending, longest mapping breaking ties.

Nothing from the old BS logic is dropped: display-name unwrap for system senders, the forwarded
chain in order, the system-sender filter, the settings-driven `gmail_docs_download_ignored_mails`,
address-then-domain matching, and the whole-chain second sweep.

## 2. The E2E proof — what was actually sent and what happened

**11 distinct synthetic Hebrew documents** generated (PIL, real OCR-able PDFs, verified RTL).

**5 real emails sent from the owner's own Gmail account** (via the stack's mail service, the same
account the browser is signed into) at 15:28 UTC:

| mail | content | label the ENGINE applied (unprompted) | lane |
|---|---|---|---|
| E2E-1 | חשבונית מס 770001 (1 file) | `לטיפול-אוטומציה-שמירת-מסמכים` | gmail-doc |
| E2E-2 | חשבונית + תעודת משלוח (2 files) | `לטיפול-אוטומציה-שמירת-מסמכים` | gmail-doc |
| E2E-3 | דוח גיול (1 file, "דוח גיול" in the text) | **`לטיפול-אוטומציה-שמירת-דוחות-גיול`** | gmail-bs |
| E2E-4b | link to an invoice (0 files) | sender-gated rule — see §4 | gmail-link |
| E2E-5 | דוח גיול + חשבונית (2 files) | (queued behind the engine's 10-per-run cap) | gmail-bs |

The label engine routed by CONTENT exactly as designed — the aging-report mail went to the BS lane
purely because its text says "דוח גיול".

**Drive side**: a service account **cannot** create files in Drive (no personal storage; the
adapter refuses explicitly and correctly — Google would answer 403). New Drive files therefore
need the owner's own account. The 4 synthetic Drive documents are staged for that at
`…/scratchpad/e2e/`. To prove the Drive lanes *now*, two real owner-owned documents were MOVED
into `drive-gdoc-scanned` and `drive-gdoc-chat-export` to_sync (the SA may move, just not create).

## 3. Live proof of the new contract (drive lane, within minutes)

`doc_mt8trot3mn4ntg` — delivered by the chat-export lane and written by the patched processor:

```
SENDER            drive-folder:1DYzDE5T3c2PGFOfNwnmCP3jjSqr2DiBx
SYNC_REGISTRY_ID  drive-gdoc          (→ ctx.sync_name after the fix; first run wrote 'drive')
ATTACHMENT_TEXT   ברייטקום ב-35196.jpg
SEND_DATE         17/03/2026
```

All four source facts populated by the sync, deciding nothing — exactly the contract.

## 4. Two REAL defects the proof exposed (both fixed live)

**(a) The drive-gdoc processor closed a document over a hole it had itself detected.**
It stamped `STATUS=COMPLETED` on its `Is OK` flag alone, while its own `REQUIRED_ACTION` read
**"Missing company name"** — and it renames the file to `unknown-<id>`, destroying the only company
signal the filename carried. `COMPLETED` is TERMINAL (excluded from both feeders), so `select_base`
never ran and the company was never resolvable. Measured: `doc_mt8trot3mn4ntg` COMPLETED with no
`COMPANY_ID`, while its `ATTACHMENT_TEXT` reads "ברייטקום ב-35196.jpg" and **"ברייטקום ב" is
company 515273175** — resolvable the instant selection is allowed to run.
**Fix:** the lane now stamps COMPLETED only when it has BOTH a company and a real type; otherwise
the document is handed to the state machine as `IN_PROGRESS`. This is the same class as the
`MISSING_COMPANY_ID` terminal-door problem, one layer earlier.

**(b) `SYNC_REGISTRY_ID` was derived from the wrong ctx field** (wrote `drive` instead of the
registry name). Fixed to `ctx.sync_name` — caught by the first live run, not by reading code.

## 5. Still open

- The 4 synthetic Drive documents need the owner's account to enter Drive (SA cannot create).
- The gmail-link lane's label rule is sender-gated (18 provider addresses), so a self-sent link
  mail is not labelled by the engine — by design. E2E-4b therefore tests the DOWNSTREAM lane only.
- The label engine processes **10 messages per 15-minute run** and each mailapi `/search` is
  currently taking ~44s (the IMAP saturation already filed) — that is the pacing limit on how fast
  new mail becomes documents.
