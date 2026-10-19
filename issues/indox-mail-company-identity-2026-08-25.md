# Company identity for mail-origin documents — measured truth (2026-08-25)

Owner order: the SYNC must settle who the sender is; either it decides the company, or it hands
the mail on and ALL selection happens in exactly two places (base selector + per-type selector),
losing no logic. Then: every mail document must find its company — 100%.

## 1. THE NUMBERS (live DB, this hour)

Mail-origin documents: **7,493**, of which **1,463 have no COMPANY_ID = 19.5%**.
Terminal split: `MISSING_COMPANY_ID` **1,334** · GARBAGE 81 · OLD 24 · MERGED 14 · DOUBLE 6 · rest 4.

Per pipe (current-era rows carrying sync provenance):

| pipe | docs | no company | % | what that lane is |
|---|---|---|---|---|
| gmail-link | 374 | 173 | **46.3%** | INTERMEDIARY mail (invoice-one / morning / senzey / invoice-maven) |
| gmail-doc | 2,327 | 365 | 15.7% | attachment mail, mostly direct senders |
| gmail-bs | 136 | 10 | **7.4%** | the OLD complex downloader (sender选 + COMPANY_HINT) |
| mail-private | 2 | 2 | — | paused duplicate |

**The old, "complicated" BS lane is the BEST performer by 6×.** Its sender/hint logic is not
legacy cruft — it is the only lane that currently converts sender knowledge into company.

## 2. WHY THE BASE SELECTOR CANNOT DECIDE COMPANY TODAY (root cause)

**The sender is never persisted.** `incoming_documents` has COMPANY_ID / COMPANY_NAME /
AI_COMPANY_ID / SELECTED_COMPANY_ID / LOCAL_COMPANY_ID — and **no sender, from, or subject
column**. `SOURCE_LIST` (the sync-era provenance blob) carries hash, message_id, registry name,
connections… and `"mailbox": null`. Verified on live MISSING_COMPANY_ID rows.

So the mail's identity dies at the downloader. Any selector — base or per-type — is structurally
unable to use "who sent it", no matter how good its logic is. **This is the whole gap.**

## 3. THE SENDER IS TWO DIFFERENT THINGS (this is the real complexity)

Sampled real missing-company mail (Gmail, live):

**(a) Direct supplier mail — sender IS the company**
- `person188@example.com` → "ויצנר- כרטסת פתוחים" (real BS document)
- `person189@example.com` → Keter

**(b) Intermediary mail — sender is a DELIVERY SERVICE, never the company**
- `person95@example.com` → three different suppliers (סאן דק, פאר נשר, Elram)
- `notify@morning.co` → קונקטופ בע"מ
In every one of these the supplier name is in the **SUBJECT**, not the sender.
`indoxGmailLinkDownloader01` already knows these senders — it has a provider-matching engine
(group A morning/invoice-maven/senzey, group B invoice-one, …) used ONLY to extract the download
URL. It identifies the intermediary and then throws that knowledge away. That is exactly why the
link lane is at 46% missing.

**(c) Not documents at all** — the same missing-company pool holds marketing blasts
(Keter product announcements to 80+ CC recipients) and an insurance-renewal reminder. They were
ingested as documents and then failed company detection because there is no company to find.
An intake-precision question, not an identification one.

## 4. THE COMPANY TABLE IS THE OTHER HALF — and it is 11.5% populated

`public.companies` (1,183 rows) already has the mapping columns: **`מייל 1`** and **`מייל 2`**,
holding either a full address (`person86@example.com`) or a bare domain (`hbv.co.il`,
`pazlub.co.il`, `neumansteel.co.il`) — domain-or-address matching by design.
**Only 136 rows (11.5%) have `מייל 1`; 6 have `מייל 2`.** `trusted_suppliers` is EMPTY (0 rows).
Even with the sender persisted, sender→company resolves for ~1 in 9 companies until this is filled.

## 4b. THE OLD BS LOGIC, EXACTLY (one code node — `Balance Doc Properties`, BS dl :360-557)

There is **no `COMPANY_HINT`** — anywhere in the repo or the schema (grep: 0 hits). What the owner
remembers as "the hint" is this five-rule sender resolution, all inside one node:

1. base = `from.value[0].address` (:501)
2. **Gaviti unwrap** (:503-507) — for `person46@example.com` the real client address is in the
   DISPLAY NAME; `extractEmailFromName()` pulls it out. One address otherwise collapses many
   clients into one wrong company.
3. **forwarded-chain unwrap** (:428-466) — splits the body on 5 indicators
   ("---------- Forwarded message", "Begin forwarded message", "From:", …), extracts every address,
   filters system senders (`no-reply|noreply|mailer-daemon|donotreply`, :396-401) and the
   settings-driven `gmail_docs_download_ignored_mails`.
4. **precedence: the forwarded sender BEATS the actual From** (:518-521) — for this tenant the
   From is very often the owner's own mailbox.
5. **lookup = exact email, then DOMAIN** (`findCompany`, :472-485) against
   `settings.company_name_by_mail`; if that fails, a **second sweep over every address in the
   chain** (:526-531); then id = `settings.companies[name].identifiers[0]`.

Then the answer travels **two** ways: `COMPANY_ID` on the row, and — undocumented — the company
NAME is prefixed onto the FILENAME (:566-579, `"<company> <MM.YY>.pdf"`), which is what
`SelectBase01`'s `NAME Company Match` (anchored prefix, ≥5 chars) later reads. That accidental
string channel is the only reason the sender's answer survives into the new selector at all.

**Two ready-made assets nobody uses**: `indoxSettings01` already builds and exports
`company_id_by_mails` (email→COMPANY_ID, :373) — **zero consumers in the repo**; and
`/webhook/company?email=` exists (:816-829) but is **exact-match only, no domain fallback**, so
swapping the code node for the endpoint would silently lose rule 5.

## 4c. LIVE CHECK OF THE OVERWRITE RISK — measured, mostly benign

`SelectBase01` is live (32 runs in 3h) and does `if (companyPick.val) out.COMPANY_ID = ...` — it
can overwrite the sender-derived id with an OCR answer. Measured on the 68 gmail-bs docs that
have been through it (comparing the final company against the sender-derived filename prefix):

| outcome | count |
|---|---|
| agreed (sender answer preserved) | **50** |
| sender FAILED (`unknown …`), OCR rescued it | **17** |
| harmful override (sender had a name, OCR replaced it) | **1** |

So today OCR helps 17× more than it harms. The correct fix is therefore NOT to put the sender
above OCR globally — it is to make the sender a **fourth leg with provenance** so that
(a) the 17 rescues keep working, (b) the 1 override becomes visible/decidable, and (c) the
still-unresolved cases get the sender leg they never had. Note the live debug vocabulary
(`AGREE / LOCAL_ONLY / AI_ONLY / NONE`) has no sender token at all — proof the leg is absent.

## 5. WHAT 100% ACTUALLY REQUIRES (four things, in order)

1. **Persist the mail identity on the row** — sender address, sender display name, subject, and
   the intermediary flag. Written by the sync/downloader (it already holds all of it), consumed
   by the selectors. Without this nothing else matters.
2. **Classify the sender at sync time**: direct vs intermediary (the provider list already exists
   in the link downloader — promote it to a setting/table both lanes read). The sync's ONE
   decision is "who is the sender, and is that identity meaningful" — not which company.
3. **Fill `companies.מייל 1/2`** from real traffic: the sender census of direct-supplier mail
   yields the domain list; every unmatched direct sender becomes a company row or an alias.
   This is the only path to 100% for lane (a).
4. **Company-from-subject for intermediaries** (lane b): the supplier name is in the subject in
   100% of the sampled intermediary mail. The base selector needs the subject + the existing
   name-matching leg (BASEX's NAME_MATCH third company leg) to close this lane.

Then — and only then — the two-place model works: the sync decides IDENTITY (sender, subject,
intermediary flag, type hint), the base selector decides COMPANY+TYPE from the whole row, and the
per-type selector decides the type's values. No logic is lost: the BS lane's hint becomes an input
to the base selector rather than a decision made in the downloader.

## 6. THE RESTART TRAP (must not be skipped)

`MISSING_COMPANY_ID` is **terminal in both feeders** (indoxApi01's poll and the drainer):
only `DOUBLE`, `ACTION_RESTART`, `MISSING_LINK` are re-admitted. So the 1,334 parked mail
documents will NOT re-process themselves when the new selection lands — they need an explicit
`ACTION_RESTART` wave. Doing it BEFORE items 1-4 above just re-parks them (they would hit the
same empty-sender gap) and burns a full pipeline cycle, so the order is: persist identity → fill
companies → land select_base → then restart the 1,334 and measure the drop from 19.5%.

## 7. WHY `syncV3Deliver0001` IS UNREADABLE — half of it is dead in production

47 nodes on one canvas, which decompose into **six fused pipelines**:

| block | nodes | purpose |
|---|---|---|
| entry + routing | 5 | `Route Mode` (proc vs inline) × `Route Kind` (drive/mail/link) × `Route Proc Kind` |
| **processor mode** | 5 | Drive/Mail Proc Payload → **Run Drive/Mail Processor** → Record Req P |
| inline drive | 3 | Drive Row → Call DELIVER → Record Req |
| inline mail attachments | 8 | Get Message → Split Attachments → Has Attachments? → Loop Attach → Upload Doc → Gmail Row → Call DELIVER G → Record Req G |
| inline link | 8 | Get Link Msg → Extract Link → Download Link → Upload Link Doc → linked_ → Link Row → Call DELIVER L → Record Req L |
| ledger + feedback | 10 | Call RECORD → Post Record Route → Proj Kind → Move Req/Call Move, Label Req/Call Label, Synced Label Ops → Apply Synced Labels |
| failure lane | 6 | Attempt Req → Call ATTEMPT → Fail Label Route → Failed Label Ops → Apply Failed Labels → Result Fail |

**Measured on the live instance (last 8h of Deliver executions): 6/6 took the `proc` path**
(`Run Drive Processor` / `Run Mail Processor`); `Split Attachments`, `Download Link` and the
inline `Call DELIVER*` legs fired **zero times**. Every registry pipe declares a `processor_wf`
(SyncProcGDoc0001 / SyncProcBS000001 / indoxGmail{Doc,BS,Link}Downloader01), so `Route Mode`
always leaves on `proc` and **~19 of the 47 nodes are a second, unused implementation** of what
the downloaders already do — including its own mail-attachment splitter and link extractor.

That is the answer to "why so loaded": two generations live on one canvas — the v3 inline
delivery engine and the delegate-to-processor path that actually runs — plus feedback and
failure lanes. Retiring the inline branches (after confirming no registry can ever set
mode≠proc) removes ~40% of the nodes and most of the crossing edges, with zero production
behaviour change. That also removes the duplication that matters here: the inline link path is a
second copy of the intermediary/provider logic discussed in §3.

## 8. Where the other agent's work fits

The parallel INDOX (data-quality) session is building exactly the two-place model —
`apps/indox/issues/selection-consolidation-plan-2026-08-25.md`: two verbs `select_base` /
`select_type`, `SELECTED_*` retired, extraction writes only `LOCAL_*`/`AI_*`, and the selector
receives the WHOLE ROW (all versions + filename + source + settings). Its own blocking risk is
the same terminal-door problem as §6 (it solves it by gating `select_base` ABOVE the company/type
gates so the row stays IN_PROGRESS and eligible).
**The mail identity fields of §5.1 are the missing INPUT to that design** — the selector it is
building can only decide company from the source if the source data reaches the row. These two
work streams meet exactly there.
